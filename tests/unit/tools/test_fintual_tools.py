"""``gestionar_datos_y_fricciones``: la tool ÚNICA del Gestor-Fintual (S10, ADR-020)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from google.adk.tools import ToolContext

from investmentsys.config import Config, hash_config
from investmentsys.contracts import (
    DISCLAIMER_OPERATIVO,
    EtapaCorrida,
    MarketViews,
    PlanInercia,
    RunState,
    Veredicto,
)
from investmentsys.data_manager import CierreDiario, Dividendo
from investmentsys.tools import CLAVE_MARKET_VIEWS, CLAVE_UNIVERSO, NucleoTools
from investmentsys.tools.estado import CLAVE_RUN_STATE
from investmentsys.tools.ficha import PREFIJO_NO_VALIDADO, construir_ficha
from investmentsys.tools.fintual import (
    ARGUMENTOS,
    NOMBRE_TOOL,
    OPERACIONES,
    GestorFintualTools,
)
from investmentsys.tools.objetivo import cartera_objetivo
from tests.almacen import FuenteFalsa, cap_fuente, panel_referencia, sembrar_gestor, serie_sintetica
from tests.conftest import ACTIVOS
from tests.unit.tools.conftest import Turnos

FIN = panel_referencia().index[-1]
BNS_PAGOS = (Dividendo(date(2026, 4, 7), 0.792), Dividendo(date(2026, 7, 7), 0.803))


@pytest.fixture
def fuente() -> FuenteFalsa:
    return FuenteFalsa(
        series={
            "AAPL": serie_sintetica("AAPL", 80, FIN),
            "QQQ": serie_sintetica("QQQ", 80, FIN, semilla=11),  # ETF: sin cap en la fuente
        },
        caps={"AAPL": cap_fuente()},
        pagos={"BNS": (Dividendo(date(2020, 1, 7), 0.5), *BNS_PAGOS)},
        cierres={"BNS": CierreDiario(date(2026, 10, 2), 94.07, 93.41)},
    )


@pytest.fixture
def gestor_fintual(tmp_path: Path, config: Config, fuente: FuenteFalsa) -> GestorFintualTools:
    return GestorFintualTools(sembrar_gestor(tmp_path, config, fuente), config)


def _propuesta(tools: NucleoTools, ctx: ToolContext, views: MarketViews) -> dict[str, Any]:
    assert tools.estimar_mercado(ctx)["status"] == "success"
    ctx.state[CLAVE_MARKET_VIEWS] = views.model_dump(mode="json")
    salida = tools.construir_candidatos(ctx)
    assert salida["status"] == "success"
    pesos: dict[str, Any] = salida["candidatos"][salida["recomendado"]]["pesos"]
    return pesos


def _aprobar(tools: NucleoTools, config: Config, ctx: ToolContext) -> RunState:
    """Deja en la sesión el acta de una corrida aprobada, como ``convocar_comite``."""
    assert tools.validar_candidato(ctx)["veredicto"] == Veredicto.APROBADA.value
    estado = ctx.state.to_dict()
    corrida = RunState.model_validate(
        {
            "run_id": "20260930T000000000000Z",
            "creado_en": "2026-09-30T00:00:00",
            "fecha_decision": estado["fecha_decision"],
            "semilla": config.reproducibilidad.semilla,
            "config_hash": hash_config(),
            "activos": ACTIVOS,
            "universo": estado[CLAVE_UNIVERSO],
            "restricciones_sesion": estado["restricciones_sesion"],
            "prior": estado["prior"],
            "etapa": EtapaCorrida.VALIDACION,
            "restricciones": estado["restricciones"],
            "market_views": estado[CLAVE_MARKET_VIEWS],
            "quant_estimates": estado["quant_estimates"],
            "candidatos": estado["candidatos"],
            "validaciones": estado["validaciones"],
        }
    )
    ctx.state[CLAVE_RUN_STATE] = corrida.model_dump(mode="json")
    return corrida


# --------------------------------------------------------------- la declaración que ve el LLM
def test_una_sola_declaracion_con_las_operaciones_enumeradas(
    gestor_fintual: GestorFintualTools,
) -> None:
    (tool,) = gestor_fintual.function_tools()
    declaracion = tool._get_declaration()
    assert declaracion is not None and declaracion.name == NOMBRE_TOOL
    esquema = declaracion.parameters_json_schema
    assert set(esquema["properties"]) == {"operacion", "ticker", "prior_cap", "prior_metodologia"}
    assert esquema["required"] == ["operacion"]
    assert esquema["properties"]["operacion"]["enum"] == list(OPERACIONES)
    assert set(ARGUMENTOS) == set(OPERACIONES)
    for operacion in OPERACIONES:  # el docstring le explica cada una al modelo
        assert f'"{operacion}"' in (declaracion.description or ""), operacion
    # Ninguna cifra de cartera puede llegar por argumentos: ni pesos ni montos.
    assert not {"pesos", "monto", "valor_usd"} & set(esquema["properties"])


# ------------------------------------------------------ custodia de argumentos por operación
@pytest.mark.parametrize(
    ("operacion", "args", "fragmento"),
    [
        ("resolver", {}, "faltan ['ticker']"),
        ("retirar", {"ticker": "BNS", "prior_cap": 3.0}, "no admite ['prior_cap']"),
        ("montos", {"ticker": "VOOG"}, "no admite ['ticker']"),
        ("aceptar_prior_neutral", {"prior_metodologia": "x"}, "no admite ['prior_metodologia']"),
    ],
)
def test_un_argumento_que_no_corresponde_se_rechaza_y_no_ejecuta_nada(
    gestor_fintual: GestorFintualTools,
    ctx: ToolContext,
    operacion: str,
    args: dict[str, Any],
    fragmento: str,
) -> None:
    antes = gestor_fintual.gestor.universo().version
    salida = gestor_fintual.gestionar_datos_y_fricciones(operacion, ctx, **args)  # type: ignore[arg-type]
    assert salida["status"] == "rechazado" and salida["operacion"] == operacion
    assert fragmento in salida["motivo"]
    assert gestor_fintual.gestor.universo().version == antes


def test_operacion_desconocida_lista_las_que_existen(
    gestor_fintual: GestorFintualTools, ctx: ToolContext
) -> None:
    salida = gestor_fintual.gestionar_datos_y_fricciones("vender", ctx)  # type: ignore[arg-type]
    assert salida["status"] == "rechazado" and "montos" in salida["motivo"]


# --------------------------------------------- las operaciones heredadas conservan custodias
def test_incorporar_cambia_el_universo_y_declara_los_obsoletos(
    gestor_fintual: GestorFintualTools, tools: NucleoTools, ctx: ToolContext
) -> None:
    assert tools.estimar_mercado(ctx)["status"] == "success"
    assert gestor_fintual.gestionar_datos_y_fricciones("resolver", ctx, ticker="AAPL")["activo"][
        "prior"
    ]["tiene_cap"]
    salida = gestor_fintual.gestionar_datos_y_fricciones("incorporar", ctx, ticker="AAPL")
    assert salida["status"] == "success" and salida["operacion"] == "incorporar"
    assert ctx.state[CLAVE_UNIVERSO]["version"] == salida["universe_version"]
    assert [o["resultado"] for o in salida["resultados_obsoletos"]] == [
        "estimaciones del Estadístico"
    ]


def test_el_prior_neutral_sigue_exigiendo_un_turno_posterior(
    gestor_fintual: GestorFintualTools, turnos: Turnos
) -> None:
    primero = turnos("inv-1")
    alta = gestor_fintual.gestionar_datos_y_fricciones("incorporar", primero, ticker="QQQ")
    assert alta["estado_prior"] == "pendiente"
    for _ in range(2):  # insistir en el mismo turno no degrada
        salida = gestor_fintual.gestionar_datos_y_fricciones("aceptar_prior_neutral", primero)
        assert salida["status"] == "rechazado" and salida["tipo"] == "ConfirmacionPendiente"
    salida = gestor_fintual.gestionar_datos_y_fricciones("aceptar_prior_neutral", turnos("inv-2"))
    assert salida["status"] == "success" and salida["estado_prior"] == "neutral"


# --------------------------------------------------------------------- dividendos y cierres
def test_dividendos_es_historia_reciente_y_dice_que_no_hay_calendario_futuro(
    gestor_fintual: GestorFintualTools, ctx: ToolContext, config: Config
) -> None:
    salida = gestor_fintual.gestionar_datos_y_fricciones("dividendos", ctx)
    assert salida["status"] == "success"
    assert salida["ex_dividendos"]["BNS"] == [  # el pago de 2020 queda fuera de la ventana
        {"fecha_ex": "2026-04-07", "monto_usd_por_accion": 0.792},
        {"fecha_ex": "2026-07-07", "monto_usd_por_accion": 0.803},
    ]
    assert salida["sin_dividendos_en_el_periodo"] == ["VOOG", "IBIT", "VB"]
    assert salida["dias_de_historia"] == config.fintual.dias_historia_dividendos
    assert "no publica el calendario futuro" in salida["nota"]
    assert salida["disclaimer"] == DISCLAIMER_OPERATIVO
    json.dumps(salida)


def test_cierres_crudo_y_ajustado_con_su_fecha(
    gestor_fintual: GestorFintualTools, ctx: ToolContext
) -> None:
    salida = gestor_fintual.gestionar_datos_y_fricciones("cierres", ctx)
    assert salida["cierres"]["BNS"] == {
        "fecha": "2026-10-02",
        "cierre": 94.07,
        "cierre_ajustado": 93.41,
    }
    assert salida["cierres"]["VOOG"] is None and "VOOG" in salida["sin_cierre_reciente"]


def test_sin_fuente_de_mercado_es_un_error_del_gestor(
    tmp_path: Path, config: Config, ctx: ToolContext
) -> None:
    from investmentsys.data_manager import GestorDatos

    gestor = sembrar_gestor(tmp_path, config)
    sin_fuente = GestorFintualTools(GestorDatos(config, None, raiz=gestor.raiz), config)
    salida = sin_fuente.gestionar_datos_y_fricciones("dividendos", ctx)
    assert salida["status"] == "error" and "fuente de mercado" in salida["mensaje"]


# ------------------------------------------------------------------------------- montos
def test_montos_sin_cartera_sobre_la_mesa_se_rechaza_con_lo_que_falta(
    gestor_fintual: GestorFintualTools, ctx: ToolContext
) -> None:
    salida = gestor_fintual.gestionar_datos_y_fricciones("montos", ctx)
    assert salida["status"] == "error" and salida["tipo"] == "FaltaEnEstadoError"
    assert "no hay una cartera vigente sobre la mesa" in salida["mensaje"]


def test_montos_usa_la_propuesta_de_la_mesa_y_la_cartera_de_config(
    gestor_fintual: GestorFintualTools,
    tools: NucleoTools,
    ctx: ToolContext,
    config: Config,
    views_golden: MarketViews,
) -> None:
    pesos = _propuesta(tools, ctx, views_golden)
    salida = gestor_fintual.gestionar_datos_y_fricciones("montos", ctx)
    assert salida["status"] == "success" and salida["validado"] is False
    assert salida["universe_version"] == ctx.state[CLAVE_UNIVERSO]["version"]
    assert "propuesta por el Constructor (exploratoria)" in salida["cartera_objetivo"]
    assert salida["valor_cartera_usd"] == config.portafolio.valor_usd
    por_activo = salida["por_activo"]
    for activo, peso in pesos.items():
        assert por_activo[activo]["peso_objetivo"] == peso
        assert por_activo[activo]["peso_actual"] == config.portafolio.pesos_actuales[activo]
    total = sum(d["monto_objetivo_usd"] for d in por_activo.values())
    assert round(total, 2) == config.portafolio.valor_usd
    # Con la cartera real del proyecto (VOOG 79 %) frente a la referencia (≈70/7/2/21): VOOG y
    # VB están fuera de su banda de ±5 p.p.; BNS e IBIT, dentro.
    assert salida["orden_global"] == "FUERA_DE_BANDA"
    assert salida["fuera_de_banda"] == ["VOOG", "VB"]
    assert por_activo["BNS"]["orden"] == "HOLD" and por_activo["IBIT"]["orden"] == "HOLD"
    assert "NO es una orden" in salida["nota"] and "ni que venda" in salida["nota"]
    assert por_activo["VOOG"]["situacion"] == "sobreponderado"
    assert por_activo["VB"]["situacion"] == "subponderado"
    assert por_activo["BNS"]["accion"].startswith("HOLD obligatorio")
    assert "no indiques comprar ni vender" in por_activo["VOOG"]["accion"]
    json.dumps(salida)

    ficha = construir_ficha(NOMBRE_TOOL, salida)
    assert ficha is not None and "**Gestor de Datos**" in ficha
    assert all(ln.startswith(f"- {PREFIJO_NO_VALIDADO}") for ln in ficha.splitlines()[2:])


def test_una_cartera_aprobada_por_el_comite_manda_sobre_la_exploratoria(
    gestor_fintual: GestorFintualTools,
    tools: NucleoTools,
    ctx: ToolContext,
    config: Config,
    views_golden: MarketViews,
) -> None:
    _propuesta(tools, ctx, views_golden)
    corrida = _aprobar(tools, config, ctx)
    objetivo = cartera_objetivo(ctx.state)
    assert objetivo.validado and corrida.run_id in objetivo.origen
    salida = gestor_fintual.gestionar_datos_y_fricciones("montos", ctx)
    assert salida["validado"] is True
    ficha = construir_ficha(NOMBRE_TOOL, salida)
    assert ficha is not None and PREFIJO_NO_VALIDADO not in ficha
    assert "ESTIMACIÓN OPERATIVA" in ficha.splitlines()[0]


def test_un_acta_de_otro_universo_no_sirve_de_objetivo(
    gestor_fintual: GestorFintualTools,
    tools: NucleoTools,
    ctx: ToolContext,
    config: Config,
    views_golden: MarketViews,
) -> None:
    _propuesta(tools, ctx, views_golden)
    _aprobar(tools, config, ctx)
    assert gestor_fintual.gestionar_datos_y_fricciones("retirar", ctx, ticker="BNS")["status"] == (
        "success"
    )
    salida = gestor_fintual.gestionar_datos_y_fricciones("montos", ctx)
    assert salida["status"] == "error", "ni el acta ni la propuesta son del universo vigente"


def test_lo_que_devuelve_montos_es_un_plan_de_inercia_valido(
    gestor_fintual: GestorFintualTools,
    tools: NucleoTools,
    ctx: ToolContext,
    views_golden: MarketViews,
) -> None:
    _propuesta(tools, ctx, views_golden)
    s = gestor_fintual.gestionar_datos_y_fricciones("montos", ctx)
    plan = PlanInercia.model_validate(
        {
            "universe_version": s["universe_version"],
            "validado": s["validado"],
            "origen_objetivo": s["cartera_objetivo"],
            "valor_cartera_usd": s["valor_cartera_usd"],
            "orden_global": s["orden_global"],
            "decisiones": [
                {"activo": a, **{k: v for k, v in d.items() if k not in ("situacion", "accion")}}
                for a, d in s["por_activo"].items()
            ],
        }
    )
    assert plan.orden_global.value == s["orden_global"]
