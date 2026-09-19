"""DoD de S3: corrida completa con LLM falso → RunState y reporte en runs/<run_id>/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from investmentsys.config import Config
from investmentsys.contracts import DISCLAIMER, EtapaCorrida, RunState, Veredicto
from investmentsys.data import CSVPriceProvider
from investmentsys.orchestrator import (
    ARCHIVO_REPORTE,
    ARCHIVO_RUN_STATE,
    CLAVE_DIRECTORIO,
    crear_pipeline,
)
from tests.almacen import universo_referencia
from tests.integration.conftest import Corrida, Llamada, LlmPorAgente, ejecutar
from tests.integration.test_market_analyst import BORRADOR_GOLDEN, FUERA_DEL_UNIVERSO, _view

PESOS_GOLDEN = {"VOOG": 0.70, "BNS": 0.07, "IBIT": 0.02, "VB": 0.21}
NARRATIVA = "El analista favoreció large caps. El validador aprobó la cartera propuesta."
CRIPTO_EUFORICO = {
    "resumen": "Euforia cripto.",
    "views": [_view("absoluta", {"IBIT": 1.0}, 1.5)],  # BL topa IBIT en peso_max → HHI excesivo
}


def _correr(config: Config, provider: CSVPriceProvider, llm: LlmPorAgente, runs: Path) -> Corrida:
    pipeline = crear_pipeline(
        config, provider, llm, directorio_runs=runs, universo=universo_referencia()
    )
    corrida = ejecutar(pipeline)
    assert llm.pendientes() == {}, "quedaron respuestas del guion sin consumir"
    return corrida


def _leer(corrida: Corrida) -> tuple[RunState, str]:
    carpeta = Path(corrida.estado[CLAVE_DIRECTORIO])
    estado = RunState.model_validate_json((carpeta / ARCHIVO_RUN_STATE).read_text("utf-8"))
    return estado, (carpeta / ARCHIVO_REPORTE).read_text("utf-8")


def test_corrida_completa_aprobada_a_la_primera(
    config: Config, provider: CSVPriceProvider, tmp_path: Path
) -> None:
    llm = LlmPorAgente(
        analista=[BORRADOR_GOLDEN],
        constructor=[Llamada("construir_candidatos"), "Pedí Black-Litterman con los límites."],
        reporter=[NARRATIVA],
    )
    corrida = _correr(config, provider, llm, tmp_path)
    estado, reporte = _leer(corrida)

    assert estado.etapa is EtapaCorrida.COMPLETADA
    assert estado.aprobado and len(estado.validaciones) == 1
    assert estado.market_views is not None and len(estado.market_views.views) == 3
    assert estado.quant_estimates is not None
    final = estado.portafolio_final
    assert final is not None and final.nombre == "black_litterman"
    for activo, esperado in PESOS_GOLDEN.items():
        assert final.pesos[activo] == pytest.approx(esperado, abs=0.02)

    assert Path(corrida.estado[CLAVE_DIRECTORIO]).parent == tmp_path
    assert estado.reporte_markdown == reporte
    assert reporte.count(DISCLAIMER) >= 2
    assert "cartera aprobada" in reporte and NARRATIVA in reporte
    assert "| VOOG | 70.0 % |" in reporte
    assert "Aviso" not in reporte


def test_rechazo_y_segunda_iteracion_aprobada(
    config: Config, provider: CSVPriceProvider, tmp_path: Path
) -> None:
    llm = LlmPorAgente(
        analista=[FUERA_DEL_UNIVERSO, CRIPTO_EUFORICO],  # además ejerce el reintento
        constructor=[
            Llamada("construir_candidatos", recomendado="black_litterman"),
            "Primera propuesta.",
            Llamada("construir_candidatos", peso_max_por_activo={"IBIT": 0.05}),
            "Endurecí el máximo de IBIT.",
        ],
        reporter=["Se rechazó la primera propuesta por concentración en IBIT y luego se aprobó."],
    )
    corrida = _correr(config, provider, llm, tmp_path)
    estado, reporte = _leer(corrida)

    assert [v.veredicto for v in estado.validaciones] == [Veredicto.RECHAZADA, Veredicto.APROBADA]
    assert estado.validaciones[0].pesos_evaluados["IBIT"] > 0.5
    final = estado.portafolio_final
    assert final is not None and final.pesos["IBIT"] <= 0.05 + 1e-6
    assert estado.etapa is EtapaCorrida.COMPLETADA
    assert "## Iteración 2" in reporte and "Razón de rechazo" in reporte

    primera, segunda = llm.instrucciones("constructor")[0], llm.instrucciones("constructor")[2]
    assert "primera propuesta" in primera
    assert "RECHAZÓ" in segunda and "IBIT" in segunda
    assert "NO validó" in llm.instrucciones("analista")[1]


def test_agotadas_las_iteraciones_hay_reporte_sin_cartera(
    config: Config, provider: CSVPriceProvider, tmp_path: Path
) -> None:
    maximo = config.validacion.max_iteraciones_constructor
    llm = LlmPorAgente(
        analista=[CRIPTO_EUFORICO],
        constructor=[Llamada("construir_candidatos"), "Insisto."] * maximo,
        reporter=["No hay cartera aprobada: el validador rechazó todas las propuestas."],
    )
    estado, reporte = _leer(_correr(config, provider, llm, tmp_path))
    assert estado.etapa is EtapaCorrida.FALLIDA
    assert len(estado.validaciones) == maximo and not estado.aprobado
    assert estado.portafolio_final is None
    assert "SIN cartera aprobada" in reporte and DISCLAIMER in reporte
    assert "## Cartera aprobada" not in reporte


def test_si_el_constructor_no_llama_al_tool_se_usa_la_propuesta_por_defecto(
    config: Config, provider: CSVPriceProvider, tmp_path: Path
) -> None:
    llm = LlmPorAgente(
        analista=[BORRADOR_GOLDEN], constructor=["Creo que 60/40 estaría bien."], reporter=["Ok."]
    )
    estado, reporte = _leer(_correr(config, provider, llm, tmp_path))
    assert estado.aprobado
    assert "el constructor no dejó candidatos" in reporte


def test_el_reporte_delata_cifras_que_no_salen_de_las_herramientas(
    config: Config, provider: CSVPriceProvider, tmp_path: Path
) -> None:
    llm = LlmPorAgente(
        analista=[BORRADOR_GOLDEN],
        constructor=[Llamada("construir_candidatos"), "Listo."],
        reporter=["VOOG pesa 70.0 % y esperamos un retorno del 23,5 % con Sharpe alto."],
    )
    _, reporte = _leer(_correr(config, provider, llm, tmp_path))
    aviso = next(linea for linea in reporte.splitlines() if "Aviso" in linea)
    assert "23,5 %" in aviso and "70.0 %" not in aviso


def test_el_reporter_recibe_solo_la_hoja_de_hechos(
    config: Config, provider: CSVPriceProvider, tmp_path: Path
) -> None:
    llm = LlmPorAgente(
        analista=[BORRADOR_GOLDEN],
        constructor=[Llamada("construir_candidatos"), "Listo."],
        reporter=[NARRATIVA],
    )
    _correr(config, provider, llm, tmp_path)
    (instruccion,) = llm.instrucciones("reporter")
    hoja: dict[str, Any] = json.loads(instruccion[instruccion.index("{") :].rsplit("}", 1)[0] + "}")
    assert hoja["aprobado"] is True
    assert hoja["rondas"][0]["pesos"]["VOOG"] == "70.0 %"
