"""DoD de S7: el pipeline completo sobre un universo que cambia en caliente.

- End-to-end de 5 activos: los 4 de referencia + uno incorporado por el Gestor de Datos (mock de
  la fuente, cap por argumento) → ``RunState`` con universo, diagnósticos, restricciones,
  snapshot del prior y tabla π con procedencias; el informe la muestra.
- Historia corta: las advertencias llegan hasta el informe.
- Prior pendiente: BL no disponible con mensaje claro; HRP y mínima varianza operativos.
- Degradación aceptada: todo el vector neutral + advertencia estándar en el informe.
- Obsolescencia: un resultado con ``universe_version`` viejo se rechaza.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pandas as pd
import pytest
from google.adk.tools.tool_context import ToolContext

from investmentsys.agents.reporter import renderizar
from investmentsys.config import Config
from investmentsys.contracts import (
    ADVERTENCIA_PRIOR_NEUTRAL,
    EstadoPrior,
    EtapaCorrida,
    MarketViews,
    MetodoPrior,
    OrigenActivo,
    OrigenRestriccion,
    PriorProvenance,
    RunState,
    TecnicaOptimizacion,
    Universe,
)
from investmentsys.data_manager import GestorDatos
from investmentsys.orchestrator import (
    ARCHIVO_REPORTE,
    ARCHIVO_RUN_STATE,
    CLAVE_DIRECTORIO,
    crear_pipeline,
)
from investmentsys.orchestrator.corrida import CLAVE_CREADO_EN, CLAVE_RUN_ID, armar_run_state
from investmentsys.tools import (
    CLAVE_CANDIDATOS,
    CLAVE_FECHA_DECISION,
    CLAVE_MARKET_VIEWS,
    CLAVE_PRIOR,
    CLAVE_UNIVERSO,
    NucleoTools,
)
from tests.almacen import FuenteFalsa, sembrar_gestor, serie_sintetica
from tests.conftest import ACTIVOS, FECHA
from tests.integration.conftest import Llamada, LlmPorAgente, ejecutar
from tests.integration.test_market_analyst import BORRADOR_GOLDEN

FIN = pd.Timestamp(FECHA)
NARRATIVA = "Se incorporó un quinto activo. El validador evaluó la cartera propuesta."


@pytest.fixture
def gestor(tmp_path: Path, config: Config) -> GestorDatos:
    fuente = FuenteFalsa(
        series={
            "QQQ": serie_sintetica("QQQ", 61, FIN, semilla=11, vol_mensual=0.04),
            "NUEVO": serie_sintetica("NUEVO", 20, FIN, semilla=3, vol_mensual=0.04),
        }
    )
    return sembrar_gestor(tmp_path / "almacen", config, fuente)


def _contexto(universo: Universe, views: MarketViews | None = None) -> ToolContext:
    estado: dict[str, Any] = {
        CLAVE_UNIVERSO: universo.model_dump(mode="json"),
        CLAVE_RUN_ID: "prueba",
        CLAVE_CREADO_EN: "2026-10-05T12:00:00+00:00",
    }
    if views is not None:
        estado[CLAVE_MARKET_VIEWS] = views.model_dump(mode="json")
    return cast(ToolContext, SimpleNamespace(state=estado))


def _views_para(universo: Universe, views_golden: MarketViews) -> MarketViews:
    return MarketViews.model_validate({**views_golden.model_dump(), "activos": universo.activos})


def _hasta_validar(
    config: Config, gestor: GestorDatos, universo: Universe, views_golden: MarketViews
) -> tuple[RunState, dict[str, Any]]:
    tools = NucleoTools(config, gestor.provider())
    ctx = _contexto(universo, _views_para(universo, views_golden))
    assert tools.estimar_mercado(ctx)["status"] == "success"
    construir = tools.construir_candidatos(ctx)
    assert construir["status"] == "success", construir
    assert tools.validar_candidato(ctx)["status"] == "success"
    return armar_run_state(ctx.state, config, EtapaCorrida.REPORTE), construir


# ----------------------------------------------------------------- end-to-end, 5 activos
def test_end_to_end_con_un_quinto_activo_incorporado_en_caliente(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    antes = gestor.universo()
    universo = gestor.incorporar(
        "QQQ", prior_cap=22.0, prior_metodologia="capitalización del Nasdaq-100 (subyacente)"
    )
    assert universo.activos == (*ACTIVOS, "QQQ") and universo.version != antes.version

    llm = LlmPorAgente(
        analista=[BORRADOR_GOLDEN],
        constructor=[Llamada("construir_candidatos"), "Pedí Black-Litterman con los límites."],
        reporter=[NARRATIVA],
    )
    pipeline = crear_pipeline(
        config, gestor.provider(), llm, directorio_runs=tmp_path / "runs", universo=universo
    )
    corrida = ejecutar(pipeline)
    carpeta = Path(corrida.estado[CLAVE_DIRECTORIO])
    acta = RunState.model_validate_json((carpeta / ARCHIVO_RUN_STATE).read_text("utf-8"))
    informe = (carpeta / ARCHIVO_REPORTE).read_text("utf-8")

    # Universo y diagnósticos
    assert acta.activos == (*ACTIVOS, "QQQ") and acta.universo == universo
    assert acta.universo.origenes["QQQ"] is OrigenActivo.AGREGADO_EN_SESION
    assert acta.universo.diagnostico("QQQ").meses_disponibles == 61
    assert any("tasas_2022 no aplica" in a for a in acta.universo.diagnostico("IBIT").advertencias)
    assert "Analizando VOOG, BNS, IBIT, VB, QQQ" in " ".join(corrida.textos("market_analyst"))
    # Restricciones de sesión con su origen
    sesion = acta.restricciones_sesion
    assert sesion.universe_version == universo.version
    assert (sesion.peso_min.valor, sesion.peso_max.valor) == (0.02, 0.70)
    assert sesion.peso_max.origen is OrigenRestriccion.DEFAULT_CONFIG
    # Todo sellado con el universo de la corrida
    assert acta.quant_estimates is not None
    sellos = [acta.quant_estimates, *acta.candidatos, *acta.validaciones]
    assert {s.universe_version for s in sellos} == {universo.version}
    # Snapshot del prior y tabla π con procedencias
    prior = acta.prior
    assert prior is not None and prior.metodo is MetodoPrior.CAPITALIZACION
    assert prior.tickers == acta.activos
    assert set(prior.procedencias.values()) == {PriorProvenance.USUARIO}
    qqq = next(a for a in prior.activos if a.activo == "QQQ")
    assert qqq.cap == 22.0 and qqq.fuente_detalle == "capitalización del Nasdaq-100 (subyacente)"
    assert qqq.peso_mercado == pytest.approx(22.0 / (28.0 + 0.116 + 1.9 + 2.5 + 22.0))
    assert all(a.pi_total == pytest.approx(a.pi_exceso + 0.04) for a in prior.activos)
    # La cartera es de 5 activos, suma 1 y respeta los límites de la sesión
    ronda = acta.candidatos[-1]
    assert {c.nombre for c in ronda.candidatos} == {"black_litterman", "hrp", "min_varianza"}
    pesos = ronda.portafolio_recomendado.pesos
    assert set(pesos) == set(acta.activos) and sum(pesos.values()) == pytest.approx(1.0)
    assert all(0.02 - 1e-6 <= p <= 0.70 + 1e-6 for p in pesos.values())
    # El informe muestra SIEMPRE la tabla π con la procedencia de cada peso
    assert "## Prior de equilibrio (Black-Litterman)" in informe
    assert "| QQQ | usuario | 22 | capitalización del Nasdaq-100 (subyacente) |" in informe
    assert "| VOOG | usuario | 28 |" in informe and "π (total)" in informe
    assert "## Universo y restricciones" in informe and "agregado_en_sesion" in informe
    assert ADVERTENCIA_PRIOR_NEUTRAL not in informe
    assert llm.pendientes() == {}
    assert acta.etapa is EtapaCorrida.COMPLETADA and acta.aprobado


# ----------------------------------------------------------------------- historia corta
def test_las_advertencias_de_historia_corta_llegan_al_informe(
    config: Config, gestor: GestorDatos, views_golden: MarketViews
) -> None:
    universo = gestor.incorporar("NUEVO", prior_cap=0.5, prior_metodologia="cap bursátil")
    diagnostico = universo.diagnostico("NUEVO")
    assert diagnostico.meses_disponibles == 20
    assert any("stress tasas_2022 no aplica" in a for a in diagnostico.advertencias)

    acta, _ = _hasta_validar(config, gestor, universo, views_golden)
    advertencias = acta.validaciones[-1].advertencias
    assert any(a.startswith("NUEVO: el backtest solo lo mide desde 2025-02") for a in advertencias)
    assert "NUEVO: el stress tasas_2022 no lo mide (sin datos en la ventana)" in advertencias
    assert any(a.startswith("IBIT: el stress tasas_2022 no lo mide") for a in advertencias)
    assert not any(a.startswith("VOOG") for a in advertencias)

    informe = renderizar(acta, "Narrativa.", "modelo")
    assert "Advertencias de datos:" in informe and "**NUEVO**: historia corta: 20 meses" in informe
    assert "Alcance de esta validación (historia corta):" in informe
    assert "NUEVO: el stress tasas_2022 no lo mide" in informe


# --------------------------------------------------------------------- prior pendiente
def test_sin_cap_y_sin_aceptar_neutral_bl_no_disponible_y_el_comite_sigue(
    config: Config, gestor: GestorDatos, views_golden: MarketViews
) -> None:
    universo = gestor.incorporar("QQQ")
    assert universo.estado_prior is EstadoPrior.PENDIENTE
    acta, construir = _hasta_validar(config, gestor, universo, views_golden)

    motivo = construir["no_disponibles"]["black_litterman"]
    assert "falta la capitalización de QQQ" in motivo and "aceptar_neutral=True" in motivo
    assert construir["recomendado"] == "hrp" and "no está disponible" in construir["avisos"][0]
    assert set(construir["candidatos"]) == {"hrp", "min_varianza"}  # el comité no queda cojo
    ronda = acta.candidatos[-1]
    assert TecnicaOptimizacion.BLACK_LITTERMAN in ronda.no_disponibles
    assert acta.prior is None and len(acta.validaciones) == 1

    informe = renderizar(acta, "Narrativa.", "modelo")
    assert "Black-Litterman no disponible: falta la capitalización de QQQ" in informe
    assert "**black_litterman no disponible**" in informe


# ---------------------------------------------------------------- degradación aceptada
def test_degradacion_aceptada_todo_el_vector_neutral_y_advertencia_en_el_informe(
    config: Config, gestor: GestorDatos, views_golden: MarketViews
) -> None:
    universo = gestor.incorporar("QQQ", aceptar_neutral=True)
    acta, construir = _hasta_validar(config, gestor, universo, views_golden)

    assert acta.prior is not None and acta.prior.metodo is MetodoPrior.NEUTRAL
    assert set(acta.prior.procedencias.values()) == {PriorProvenance.NEUTRAL}
    assert acta.prior.pesos_mercado == pytest.approx(dict.fromkeys(acta.activos, 0.2))
    assert construir["no_disponibles"] == {} and ADVERTENCIA_PRIOR_NEUTRAL in construir["avisos"]
    assert "black_litterman" in construir["candidatos"]

    informe = renderizar(acta, "Narrativa.", "modelo")
    assert f"> **Advertencia — {ADVERTENCIA_PRIOR_NEUTRAL}.**" in informe
    assert "| VOOG | neutral | — |" in informe and "| QQQ | neutral | — |" in informe
    assert "sin capitalización: QQQ" in informe


# ------------------------------------------------------------------------ obsolescencia
def test_un_resultado_con_universe_version_viejo_se_rechaza(
    config: Config, gestor: GestorDatos, views_golden: MarketViews
) -> None:
    viejo = gestor.universo()
    tools = NucleoTools(config, gestor.provider())
    ctx = _contexto(viejo, views_golden)
    assert tools.estimar_mercado(ctx)["status"] == "success"
    assert tools.construir_candidatos(ctx)["status"] == "success"

    # Cambia una cap congelada: MISMO conjunto de activos, otro universo.
    nuevo = gestor.refrescar_cap("BNS", prior_cap=0.13, prior_metodologia="cap bursátil 2026-10")
    ctx.state[CLAVE_UNIVERSO] = nuevo.model_dump(mode="json")
    ctx.state["restricciones_sesion"] = None

    validar = tools.validar_candidato(ctx)
    assert validar["status"] == "error" and validar["tipo"] == "ResultadoObsoletoError"
    assert "candidatos a validar: obsoleto" in validar["mensaje"]
    ctx.state[CLAVE_CANDIDATOS] = []
    construir = tools.construir_candidatos(ctx)
    assert (
        construir["status"] == "error"
        and "estimaciones del Quant: obsoleto" in construir["mensaje"]
    )
    # Recalcular sobre el universo vigente lo arregla; el prior refleja la cap nueva.
    ctx.state[CLAVE_FECHA_DECISION] = None
    assert tools.estimar_mercado(ctx)["status"] == "success"
    assert tools.construir_candidatos(ctx)["status"] == "success"
    assert ctx.state[CLAVE_PRIOR]["activos"][1]["cap"] == 0.13


def test_restricciones_infactibles_son_un_error_claro_de_la_herramienta(
    config: Config, gestor: GestorDatos, views_golden: MarketViews
) -> None:
    tools = NucleoTools(config, gestor.provider())
    ctx = _contexto(gestor.universo(), views_golden)
    tools.estimar_mercado(ctx)
    for override, fragmento in (
        ({"VOOG": 0.9}, "solo puede ENDURECER"),
        ({"TSLA": 0.3}, "fuera del universo"),
        ({"IBIT": 0.01}, "por debajo de su piso"),
        (dict.fromkeys(ACTIVOS, 0.2), "techos suman 80.00% < 100 %"),
    ):
        salida = tools.construir_candidatos(ctx, peso_max_por_activo=override)
        assert salida["status"] == "error" and fragmento in salida["mensaje"], salida
        assert salida["tipo"] == "RestriccionesInfactiblesError"
    assert not ctx.state.get(CLAVE_CANDIDATOS)
