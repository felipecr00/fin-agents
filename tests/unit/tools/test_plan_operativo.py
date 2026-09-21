"""``plan_compra`` y ``forzar_orden`` (S11, ADR-022): plan de compra, filtro consultivo y Override.

La custodia del Override es la secuencia (como el gate del comité): solo tras VER la advertencia,
en otro turno, con el token de ese plan, una vez. Y queda en el acta con la advertencia cruzada.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from google.adk.events.event import Event
from google.adk.tools import ToolContext
from google.genai import types

from investmentsys.config import Config
from investmentsys.contracts import DISCLAIMER_OPERATIVO, ActaOperativa, MarketViews
from investmentsys.tools import CLAVE_CANDIDATOS, NucleoTools
from investmentsys.tools.ficha import (
    CLAVE_ANEXO,
    ETIQUETA_FICHA_OPERATIVA,
    PREFIJO_NO_VALIDADO,
    construir_ficha,
)
from investmentsys.tools.fintual import NOMBRE_TOOL, GestorFintualTools
from investmentsys.tools.plan_operativo import CLAVE_PLAN_OPERATIVO, PlanOperativoTools
from tests.almacen import sembrar_gestor
from tests.unit.tools.conftest import Turnos
from tests.unit.tools.test_fintual_tools import _aprobar, _propuesta

T0 = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
VENTA = "VOOG:vender_hasta_banda"


@pytest.fixture
def config_con_costos(config: Config) -> Config:
    tributario = config.fintual.tributario.model_copy(
        update={"tasa_marginal": 0.10, "usd_clp": 1000.0, "costo_base_usd": {"IBIT": 900.0}}
    )
    fintual = config.fintual.model_copy(update={"tributario": tributario})
    return config.model_copy(update={"fintual": fintual})


@pytest.fixture
def gestor_fintual(tmp_path: Path, config_con_costos: Config) -> GestorFintualTools:
    reloj = iter(T0 + timedelta(minutes=i) for i in range(100))
    tokens = iter(f"token-{i}" for i in range(1, 100))
    operativo = PlanOperativoTools(
        config_con_costos, tmp_path / "runs", lambda: next(reloj), lambda: next(tokens)
    )
    gestor = sembrar_gestor(tmp_path / "almacen", config_con_costos)
    return GestorFintualTools(gestor, config_con_costos, operativo)


def _dice(ctx: ToolContext, texto: str) -> ToolContext:
    """El usuario ESCRIBE ``texto`` en este turno (la procedencia se verifica contra esto)."""
    contenido = types.Content(role="user", parts=[types.Part(text=texto)])
    ctx.session.events.append(
        Event(invocation_id=ctx.invocation_id, author="user", content=contenido)
    )
    return ctx


def _con_cartera_aprobada(
    tools: NucleoTools, config: Config, ctx: ToolContext, views: MarketViews
) -> None:
    _propuesta(tools, ctx, views)
    _aprobar(tools, config, ctx)


def _plan(gf: GestorFintualTools, ctx: ToolContext, **args: Any) -> dict[str, Any]:
    return gf.gestionar_datos_y_fricciones("plan_compra", ctx, **{"aporte_usd": 500.0, **args})


def _forzar(gf: GestorFintualTools, ctx: ToolContext, escenario: str, token: str) -> dict[str, Any]:
    return gf.gestionar_datos_y_fricciones("forzar_orden", ctx, escenario=escenario, token=token)


def test_plan_desde_un_aporte_de_500_con_bandas_activas_y_filtro_consultivo(
    gestor_fintual: GestorFintualTools,
    tools: NucleoTools,
    config: Config,
    turnos: Turnos,
    views_golden: MarketViews,
) -> None:
    ctx = _dice(turnos("inv-1"), "Aporté 500 dólares este mes, ¿qué compro?")
    _con_cartera_aprobada(tools, config, ctx, views_golden)
    salida = _plan(gestor_fintual, ctx)

    assert salida["status"] == "success" and salida["validado"] is True
    assert salida["ventas_usd"] == 0.0 and salida["flujo_usd"] == 500.0
    assert sum(salida["compras_usd"].values()) == pytest.approx(500.0)
    assert "VOOG" in salida["sin_compra"] and "VOOG" in salida["fuera_de_banda_tras_el_flujo"]
    ids = [e["id"] for e in salida["escenarios_fiscales"]]
    assert ids == ["sin_ventas", VENTA, "VOOG:vender_hasta_objetivo"]
    assert salida["perdidas_latentes_usd"].keys() == {"IBIT"}

    bloque = salida[CLAVE_ANEXO]
    assert bloque.startswith("### Plan de Compra Neta — flujo de US$ 500.00")
    assert "No-Trade Zones activas" in bloque and "| VOOG | — |" in bloque
    assert "**Por defecto — sin ventas.** Costo fiscal estimado: $0 CLP. No se vende" in bloque
    assert "siguen fuera de banda: VOOG" in bloque
    assert "Costo fiscal estimado: $" in bloque.split(VENTA)[1]
    assert "tax-loss harvesting" in bloque and "estrategia legítima" in bloque
    assert "tramo marginal 10.0 %, USD/CLP 1000" in bloque
    assert "El sistema no ejecuta órdenes" in bloque
    assert bloque.rstrip().endswith(f"> {DISCLAIMER_OPERATIVO}")  # inyectado por código

    ficha = construir_ficha(NOMBRE_TOOL, salida)
    assert ficha is not None and ETIQUETA_FICHA_OPERATIVA in ficha
    assert PREFIJO_NO_VALIDADO not in ficha and "ventas US$ 0.00" in ficha

    acta = ActaOperativa.model_validate_json(Path(salida["acta_operativa"]).read_text("utf-8"))
    assert acta.run_id_comite == "20260930T000000000000Z" and acta.overrides == ()
    assert Path(salida["acta_operativa"]).parent.name == acta.run_id_comite  # junto al acta
    assert acta.ejecutado_por_el_sistema is False


def test_sobre_una_cartera_exploratoria_el_plan_va_marcado_como_no_validado(
    gestor_fintual: GestorFintualTools,
    tools: NucleoTools,
    ctx: ToolContext,
    views_golden: MarketViews,
) -> None:
    _propuesta(tools, _dice(ctx, "tengo 500"), views_golden)
    salida = _plan(gestor_fintual, ctx)
    assert salida["status"] == "success" and salida["validado"] is False
    ficha = construir_ficha(NOMBRE_TOOL, salida)
    assert ficha is not None and PREFIJO_NO_VALIDADO in ficha
    assert Path(salida["acta_operativa"]).parent.name == "operaciones"


@pytest.mark.parametrize(
    ("dicho", "args"),
    [
        ("quiero aportar algo", {}),  # el LLM inventó 500
        ("aporté 500", {"aporte_usd": 5000.0}),  # o lo cambió
        ("aporté 500", {"dividendos_usd": 12.5}),  # o añadió dividendos que nadie mencionó
    ],
)
def test_un_monto_que_el_usuario_no_escribio_se_rechaza(
    gestor_fintual: GestorFintualTools,
    tools: NucleoTools,
    ctx: ToolContext,
    views_golden: MarketViews,
    dicho: str,
    args: dict[str, float],
) -> None:
    _propuesta(tools, _dice(ctx, dicho), views_golden)
    salida = _plan(gestor_fintual, ctx, **args)
    assert salida["status"] == "rechazado" and salida["tipo"] == "FlujoSinProcedenciaError"
    assert ctx.state.get(CLAVE_PLAN_OPERATIVO) is None


def test_un_monto_con_separador_de_miles_vale(
    gestor_fintual: GestorFintualTools,
    tools: NucleoTools,
    ctx: ToolContext,
    views_golden: MarketViews,
) -> None:
    _propuesta(
        tools, _dice(ctx, "aporté US$ 1.500 y me llegaron 12,37 de dividendos"), views_golden
    )
    salida = _plan(gestor_fintual, ctx, aporte_usd=1500.0, dividendos_usd=12.37)
    assert salida["status"] == "success" and salida["flujo_usd"] == pytest.approx(1512.37)


def test_sin_cartera_sobre_la_mesa_no_hay_plan(
    gestor_fintual: GestorFintualTools, ctx: ToolContext
) -> None:
    salida = _plan(gestor_fintual, _dice(ctx, "aporté 500"))
    assert salida["status"] == "error" and "no hay una cartera vigente" in salida["mensaje"]


class TestOverride:
    @pytest.fixture
    def presentado(
        self,
        gestor_fintual: GestorFintualTools,
        tools: NucleoTools,
        config: Config,
        turnos: Turnos,
        views_golden: MarketViews,
    ) -> dict[str, Any]:
        ctx = _dice(turnos("inv-1"), "aporté 500")
        _con_cartera_aprobada(tools, config, ctx, views_golden)
        return _plan(gestor_fintual, ctx)

    def test_forzar_en_otro_turno_registra_el_override_con_la_advertencia_que_cruzo(
        self, gestor_fintual: GestorFintualTools, turnos: Turnos, presentado: dict[str, Any]
    ) -> None:
        advertencia = next(
            e["advertencia"] for e in presentado["escenarios_fiscales"] if e["id"] == VENTA
        )
        salida = _forzar(gestor_fintual, turnos("inv-2"), VENTA, presentado["token"])

        assert salida["status"] == "success" and salida["override_registrado"] is True
        assert salida["advertencia_cruzada"] == advertencia
        assert salida["flujo_usd"] == pytest.approx(500.0 + salida["venta_forzada_usd"])
        assert advertencia in salida[CLAVE_ANEXO] and DISCLAIMER_OPERATIVO in salida[CLAVE_ANEXO]

        assert salida["acta_operativa"] == presentado["acta_operativa"]  # la MISMA acta
        acta = ActaOperativa.model_validate_json(Path(salida["acta_operativa"]).read_text("utf-8"))
        (override,) = acta.overrides
        assert override.escenario.id == VENTA and override.advertencia_cruzada == advertencia
        assert (override.invocacion_presentacion, override.invocacion_override) == (
            "inv-1",
            "inv-2",
        )
        assert override.presentado_en < override.forzado_en
        assert override.plan_resultante.reinversion_usd == override.escenario.venta_usd
        assert acta.ejecutado_por_el_sistema is False

        repetido = _forzar(gestor_fintual, turnos("inv-3"), VENTA, presentado["token"])
        assert repetido["status"] == "rechazado", "el token vale una sola vez"

    def test_en_el_mismo_turno_del_plan_se_rechaza_sin_quemar_el_token(
        self, gestor_fintual: GestorFintualTools, turnos: Turnos, presentado: dict[str, Any]
    ) -> None:
        """El LLM no puede cruzar la advertencia solo: el usuario aún no la ha visto."""
        salida = _forzar(gestor_fintual, turnos("inv-1"), VENTA, presentado["token"])
        assert salida["status"] == "rechazado" and "mismo turno" in salida["motivo"]
        assert salida["tipo"] == "OverrideRechazadoError"
        assert _forzar(gestor_fintual, turnos("inv-2"), VENTA, presentado["token"])["status"] == (
            "success"
        )

    @pytest.mark.parametrize(
        ("escenario", "token", "fragmento"),
        [
            (VENTA, "inventado", "no hay un plan vigente"),
            ("VB:vender_todo", None, "no es un escenario de este plan"),
            ("sin_ventas", None, "no hay advertencia que cruzar"),
        ],
    )
    def test_token_o_escenario_invalidos_no_registran_nada(
        self,
        gestor_fintual: GestorFintualTools,
        turnos: Turnos,
        presentado: dict[str, Any],
        escenario: str,
        token: str | None,
        fragmento: str,
    ) -> None:
        salida = _forzar(gestor_fintual, turnos("inv-2"), escenario, token or presentado["token"])
        assert salida["status"] == "rechazado" and fragmento in salida["motivo"]
        acta = ActaOperativa.model_validate_json(
            Path(presentado["acta_operativa"]).read_text("utf-8")
        )
        assert acta.overrides == ()

    def test_sin_plan_previo_no_hay_nada_que_forzar(
        self, gestor_fintual: GestorFintualTools, ctx: ToolContext
    ) -> None:
        salida = _forzar(gestor_fintual, ctx, VENTA, "token-1")
        assert salida["status"] == "rechazado" and "plan_compra" in salida["motivo"]

    def test_si_cambia_la_cartera_objetivo_el_plan_presentado_ya_no_se_puede_forzar(
        self,
        gestor_fintual: GestorFintualTools,
        tools: NucleoTools,
        turnos: Turnos,
        ctx: ToolContext,
        views_golden: MarketViews,
    ) -> None:
        primero = _dice(turnos("inv-1"), "aporté 500")
        _propuesta(tools, primero, views_golden)
        token = _plan(gestor_fintual, primero)["token"]
        segundo = turnos("inv-2")
        segundo.state[CLAVE_CANDIDATOS] = []  # como el Director: cada propuesta es la ronda 1
        otra = tools.construir_candidatos(segundo, recomendado="hrp")  # otra cartera en la mesa
        assert otra["status"] == "success"
        salida = _forzar(gestor_fintual, segundo, VENTA, token)
        assert salida["status"] == "rechazado" and "cambiaron" in salida["motivo"]
        assert segundo.state.get(CLAVE_PLAN_OPERATIVO) is None
