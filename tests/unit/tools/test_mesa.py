"""``consultar_mesa_trabajo`` (S9): la mesa es una proyección del estado, elemento por elemento."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from google.adk.tools import ToolContext

from investmentsys.config import Config
from investmentsys.contracts import (
    CategoriaPizarra,
    Especialista,
    MarketViews,
    MesaDeTrabajoState,
    TipoView,
    View,
)
from investmentsys.tools import CLAVE_MARKET_VIEWS, CLAVE_UNIVERSO, NucleoTools
from investmentsys.tools.ficha import ATIENDE, CLAVE_ANEXO, PREFIJO_NO_VALIDADO
from investmentsys.tools.gestor import GestorTools
from investmentsys.tools.mesa import (
    NOMBRE_TOOL,
    MesaTools,
    SalaIncompletaError,
    componer_sala,
)
from tests.almacen import (
    FuenteFalsa,
    cap_fuente,
    diagnosticar,
    panel_referencia,
    sembrar_gestor,
    serie_sintetica,
)
from tests.conftest import ACTIVOS, FECHA

FIN = panel_referencia().index[-1]
PESOS_USUARIO = {"VOOG": 0.5, "BNS": 0.3, "VB": 0.2}


@pytest.fixture
def gestor_tools(tmp_path: Path, config: Config) -> GestorTools:
    fuente = FuenteFalsa(
        series={"AAPL": serie_sintetica("AAPL", 80, FIN)}, caps={"AAPL": cap_fuente()}
    )
    return GestorTools(sembrar_gestor(tmp_path, config, fuente))


@pytest.fixture
def mesa_tools(gestor_tools: GestorTools, config: Config) -> MesaTools:
    sala = componer_sala(
        [NOMBRE_TOOL, "estimar_mercado", "gestionar_datos_y_fricciones"], ["market_analyst"]
    )
    return MesaTools(gestor_tools.gestor, config, sala)


def _views() -> MarketViews:
    relativa = View(
        tipo=TipoView.RELATIVA,
        coeficientes={"VOOG": 1.0, "VB": -1.0},
        q_anual=0.03,
        confianza=0.6,
        justificacion="Las grandes crecen más que las pequeñas.",
        fuente="tesis del usuario, sin verificar",
    )
    return MarketViews(
        fecha_decision=FECHA, activos=ACTIVOS, horizonte_meses=12, resumen="r", views=(relativa,)
    )


def _filas(salida: dict[str, Any]) -> list[tuple[str, str, bool]]:
    mesa = MesaDeTrabajoState.model_validate(salida["mesa"])
    return [(i.categoria.value, i.origen.value, i.obsoleto) for i in mesa.items]


class TestAperturaDeSesion:
    def test_sesion_nueva_universo_y_restricciones_por_defecto(
        self, mesa_tools: MesaTools, ctx: ToolContext
    ) -> None:
        salida = mesa_tools.consultar_mesa_trabajo(ctx)
        assert salida["status"] == "success" and salida["resultados_obsoletos"] == []
        assert _filas(salida) == [
            ("Universo", "Gestor de Datos", False),
            ("Restricción", "Constructor de Carteras", False),
        ]
        tabla = salida[CLAVE_ANEXO]
        assert f"universo `{salida['universe_version'][:12]}` | VOOG, BNS, IBIT, VB" in tabla
        # Lo que la apertura debe poder decir sin otra llamada: desde cuándo hay datos y qué limita.
        assert "IBIT (datos desde 2024-01)" in tabla and "la limita IBIT" in tabla
        assert "entre 2 % (por defecto de config.yaml) y 70 % (por defecto de config.yaml)" in tabla
        assert salida["universo"]["activo_mas_corto"] == "IBIT"

    def test_no_calcula_ni_deja_nada_en_el_estado(
        self, mesa_tools: MesaTools, ctx: ToolContext
    ) -> None:
        antes = dict(ctx.state.to_dict())
        mesa_tools.consultar_mesa_trabajo(ctx)
        assert ctx.state.to_dict() == antes

    def test_readopta_el_universo_del_disco_como_diagnosticar(
        self, mesa_tools: MesaTools, gestor_tools: GestorTools, tools: NucleoTools, ctx: ToolContext
    ) -> None:
        """Un cambio hecho fuera de la sesión (``make universo``) se ve y se declara."""
        assert tools.estimar_mercado(ctx)["status"] == "success"
        gestor_tools.gestor.retirar("BNS")
        salida = mesa_tools.consultar_mesa_trabajo(ctx)
        assert ctx.state[CLAVE_UNIVERSO]["version"] == salida["universe_version"]
        assert [o["resultado"] for o in salida["resultados_obsoletos"]] == [
            "estimaciones del Estadístico"
        ]

    def test_sin_universo_es_un_error_del_gestor(
        self, mesa_tools: MesaTools, ctx: ToolContext
    ) -> None:
        mesa_tools.gestor.ruta_universo.unlink()
        salida = mesa_tools.consultar_mesa_trabajo(ctx)
        assert salida["status"] == "error" and salida["mensaje"]


class TestQueTenemos:
    def test_cada_resultado_aparece_con_su_especialista(
        self, mesa_tools: MesaTools, tools: NucleoTools, ctx: ToolContext
    ) -> None:
        ctx.state[CLAVE_MARKET_VIEWS] = _views().model_dump(mode="json")
        assert tools.estimar_mercado(ctx)["status"] == "success"
        assert tools.construir_candidatos(ctx)["status"] == "success"
        diagnostico = diagnosticar(tools, PESOS_USUARIO, ctx)
        assert (
            tools.ajustar_restricciones(ctx, limites_por_activo={"IBIT": [0.0, 0.1]})["status"]
            == "success"
        )

        salida = mesa_tools.consultar_mesa_trabajo(ctx)
        assert _filas(salida) == [
            ("Universo", "Gestor de Datos", False),
            ("Vistas", "Analista de Mercado", False),
            ("Estimación", "Estadístico", False),
            ("Carteras", "Constructor de Carteras", False),
            ("Diagnóstico", "Escéptico", False),
            ("Restricción", "Constructor de Carteras", False),
        ]
        tabla = salida[CLAVE_ANEXO]
        assert (
            f"| {PREFIJO_NO_VALIDADO}1 al {FECHA}: VOOG sobre VB +3 % anual, confianza 0.6 |"
            in tabla
        )
        assert PREFIJO_NO_VALIDADO not in tabla.split("**Universo**")[1].split("\n")[0]
        assert "recomendada black_litterman: VOOG 70.0 %" in tabla
        assert "IBIT entre 0 % y 10 % (ajuste del usuario)" in tabla
        # Las cifras del diagnóstico son las de la herramienta del Escéptico, formateadas.
        sharpe = diagnostico["metricas_oos"]["sharpe_oos"]
        caida = diagnostico["metricas_oos"]["max_drawdown"]
        assert (
            f"VOOG 50.0 % / BNS 30.0 % / IBIT 0.0 % / VB 20.0 %: Sharpe OOS {sharpe:.2f}" in tabla
        )
        assert f"caída máxima {caida * 100:.1f} %" in tabla
        assert "EXPLORATORIOS" in tabla

    def test_un_texto_con_barras_o_saltos_no_rompe_la_tabla(
        self, mesa_tools: MesaTools, ctx: ToolContext
    ) -> None:
        tabla = mesa_tools.consultar_mesa_trabajo(ctx)[CLAVE_ANEXO]
        filas = [f for f in tabla.splitlines() if f.startswith("| **")]
        assert filas and all(f.count(" | ") == 3 for f in filas)


class TestObsolescenciaPorElemento:
    def test_un_cambio_deja_obsoleto_lo_sellado_antes_y_vigente_lo_de_despues(
        self, mesa_tools: MesaTools, gestor_tools: GestorTools, tools: NucleoTools, ctx: ToolContext
    ) -> None:
        ctx.state[CLAVE_MARKET_VIEWS] = _views().model_dump(mode="json")
        tools.estimar_mercado(ctx)
        diagnosticar(tools, PESOS_USUARIO, ctx)
        previa = ctx.state[CLAVE_UNIVERSO]["version"]

        assert gestor_tools.retirar("BNS", ctx)["status"] == "success"
        tools.estimar_mercado(ctx)  # el Estadístico rehace lo suyo; el Escéptico, todavía no

        salida = mesa_tools.consultar_mesa_trabajo(ctx)
        assert _filas(salida) == [
            ("Universo", "Gestor de Datos", False),
            ("Vistas", "Analista de Mercado", True),  # son de otra lista de activos
            ("Estimación", "Estadístico", False),
            ("Diagnóstico", "Escéptico", True),
            ("Restricción", "Constructor de Carteras", False),
        ]
        mesa = MesaDeTrabajoState.model_validate(salida["mesa"])
        viejo = next(i for i in mesa.items if i.categoria is CategoriaPizarra.DIAGNOSTICO)
        assert viejo.universe_version == previa != mesa.universe_version
        assert "| **Obsoleto**: pídeselo de nuevo al Escéptico |" in salida[CLAVE_ANEXO]
        assert "| **Obsoleto**: vuelve a pedirlas al analista |" in salida[CLAVE_ANEXO]
        # Auditoría previa: el aviso va arriba de la nota, con la cuenta exacta.
        assert "**Atención: 2 elemento(s) obsoleto(s).**" in salida[CLAVE_ANEXO]

    def test_la_mesa_dice_obsoleto_exactamente_donde_la_herramienta_rechaza(
        self, mesa_tools: MesaTools, gestor_tools: GestorTools, tools: NucleoTools, ctx: ToolContext
    ) -> None:
        tools.estimar_mercado(ctx)
        gestor_tools.refrescar_cap("BNS", ctx, 0.12, "cap bursátil")
        mesa = MesaDeTrabajoState.model_validate(mesa_tools.consultar_mesa_trabajo(ctx)["mesa"])
        assert [i.categoria for i in mesa.obsoletos] == [CategoriaPizarra.ESTIMACION]
        assert diagnosticar(tools, PESOS_USUARIO, ctx)["tipo"] == "ResultadoObsoletoError"

    def test_refrescar_una_cap_no_toca_las_vistas(
        self, mesa_tools: MesaTools, gestor_tools: GestorTools, ctx: ToolContext
    ) -> None:
        """Las vistas opinan sobre activos, no sobre caps: siguen valiendo para el comité."""
        ctx.state[CLAVE_MARKET_VIEWS] = _views().model_dump(mode="json")
        gestor_tools.refrescar_cap("BNS", ctx, 0.12, "cap bursátil")
        assert ("Vistas", "Analista de Mercado", False) in _filas(
            mesa_tools.consultar_mesa_trabajo(ctx)
        )


class TestSala:
    def test_el_roster_sale_de_la_composicion_recibida(
        self, mesa_tools: MesaTools, ctx: ToolContext
    ) -> None:
        salida = mesa_tools.consultar_mesa_trabajo(ctx, vista="sala")
        assert [(s["especialista"], s["conversa"], s["herramientas"]) for s in salida["sala"]] == [
            ("Director", True, [NOMBRE_TOOL]),
            ("Gestor de Datos", False, ["gestionar_datos_y_fricciones"]),
            ("Analista de Mercado", True, ["market_analyst"]),
            ("Estadístico", False, ["estimar_mercado"]),
        ]
        assert (
            "| **Analista de Mercado** | conversa (LLM) | `market_analyst` |"
            in (salida[CLAVE_ANEXO])
        )
        assert "Escéptico" not in salida[CLAVE_ANEXO], "sin herramienta no hay silla"

    def test_una_herramienta_sin_silla_no_entra_a_la_sala(self) -> None:
        with pytest.raises(SalaIncompletaError, match="predecir_precios"):
            componer_sala(["estimar_mercado", "predecir_precios"], [])

    def test_toda_atribucion_apunta_a_un_especialista(self) -> None:
        assert set(ATIENDE.values()) == set(Especialista)


def test_declaracion_visible_para_el_llm(mesa_tools: MesaTools) -> None:
    (tool,) = mesa_tools.function_tools()
    declaracion = tool._get_declaration()
    assert tool.name == NOMBRE_TOOL and declaracion is not None
    assert "¿qué tenemos?" in (declaracion.description or "")
    esquema = declaracion.parameters_json_schema
    assert set(esquema["properties"]) == {"vista"} and not esquema.get("required")


def test_vista_desconocida_es_un_error_que_dice_cuales_hay(
    mesa_tools: MesaTools, ctx: ToolContext
) -> None:
    salida = mesa_tools.consultar_mesa_trabajo(ctx, vista="pizarra")
    assert salida["status"] == "error" and "'mesa' o 'sala'" in salida["mensaje"]
