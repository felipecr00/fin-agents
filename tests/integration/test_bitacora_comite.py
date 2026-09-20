"""S11: el pipeline emite hitos a ``pipeline_milestones`` y a ``runs/<id>/bitacora.jsonl``
MIENTRAS corre (LLM falso, Runner real)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from google.adk.models.llm_request import LlmRequest

from investmentsys.config import Config
from investmentsys.contracts import CronologiaComite, EventoComite, FaseComite, RunState
from investmentsys.data import CSVPriceProvider
from investmentsys.orchestrator import ARCHIVO_RUN_STATE, CLAVE_DIRECTORIO, crear_pipeline
from investmentsys.orchestrator.bitacora import (
    ARCHIVO_BITACORA,
    CLAVE_HITOS,
    leer_bitacora,
    leer_hitos,
)
from tests.almacen import universo_referencia
from tests.integration.conftest import Corrida, Llamada, LlmPorAgente, ejecutar
from tests.integration.test_market_analyst import BORRADOR_GOLDEN
from tests.integration.test_pipeline import CRIPTO_EUFORICO

T0 = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
E = EventoComite


def _correr(config: Config, provider: CSVPriceProvider, llm: LlmPorAgente, runs: Path) -> Corrida:
    marcas = iter(T0 + timedelta(seconds=7 * i) for i in range(100))
    pipeline = crear_pipeline(
        config,
        provider,
        llm,
        directorio_runs=runs,
        universo=universo_referencia(),
        reloj=lambda: next(marcas),
    )
    return ejecutar(pipeline)


def _aprobada() -> dict[str, list[Any]]:
    return {
        "analista": [BORRADOR_GOLDEN],
        "constructor": [Llamada("construir_candidatos"), "Pedí Black-Litterman."],
        "reporter": ["El comité aprobó la cartera propuesta."],
    }


def test_corrida_aprobada_deja_la_secuencia_de_hitos_en_estado_y_bitacora(
    config: Config, provider: CSVPriceProvider, tmp_path: Path
) -> None:
    corrida = _correr(config, provider, LlmPorAgente(**_aprobada()), tmp_path)
    hitos = leer_hitos(corrida.estado)

    assert [(h.fase, h.iteracion, h.evento) for h in hitos] == [
        (FaseComite.COMITE, 0, E.SESION_ABIERTA),
        (FaseComite.ANALISTA, 0, E.VIEWS_EMITIDAS),
        (FaseComite.ESTADISTICO, 0, E.MERCADO_ESTIMADO),
        (FaseComite.CONSTRUCTOR, 1, E.PROPUESTA),
        (FaseComite.VALIDADOR, 1, E.APROBADA),
        (FaseComite.REPORTER, 0, E.ACTA_CONSOLIDADA),
    ]
    CronologiaComite(hitos=hitos)  # en orden, por contrato
    carpeta = Path(corrida.estado[CLAVE_DIRECTORIO])
    assert leer_bitacora(carpeta / ARCHIVO_BITACORA) == hitos  # junto al acta, mismo contenido
    assert (carpeta / ARCHIVO_RUN_STATE).exists()

    assert "3 views formalizadas" in hitos[1].detalle
    # Las cifras del hito son las de la herramienta: los pesos del candidato del acta.
    acta = RunState.model_validate(corrida.estado["run_state_json"])
    assert acta.portafolio_final is not None
    for activo, peso in acta.portafolio_final.pesos.items():
        assert f"{activo} {peso * 100:.1f} %" in hitos[3].detalle


def test_los_hitos_no_entran_al_acta(
    config: Config, provider: CSVPriceProvider, tmp_path: Path
) -> None:
    """Llevan la hora del reloj: dentro de ``RunState`` romperían el replay (ADR-009)."""
    corrida = _correr(config, provider, LlmPorAgente(**_aprobada()), tmp_path)
    acta = (Path(corrida.estado[CLAVE_DIRECTORIO]) / ARCHIVO_RUN_STATE).read_text("utf-8")
    assert CLAVE_HITOS not in acta and "sesion_abierta" not in acta


def test_un_veto_lleva_su_motivo_y_abre_la_ronda_siguiente(
    config: Config, provider: CSVPriceProvider, tmp_path: Path
) -> None:
    llm = LlmPorAgente(
        analista=[CRIPTO_EUFORICO],
        constructor=[
            Llamada("construir_candidatos", recomendado="black_litterman"),
            "Primera propuesta.",
            Llamada("construir_candidatos", peso_max_por_activo={"IBIT": 0.05}),
            "Endurecí el máximo de IBIT.",
        ],
        reporter=["Se rechazó la primera propuesta y luego se aprobó."],
    )
    corrida = _correr(config, provider, llm, tmp_path)
    hitos = leer_hitos(corrida.estado)
    assert [(h.iteracion, h.evento) for h in hitos if h.iteracion] == [
        (1, E.PROPUESTA),
        (1, E.VETO),
        (2, E.PROPUESTA),
        (2, E.APROBADA),
    ]
    (veto,) = CronologiaComite(hitos=hitos).vetos
    acta = RunState.model_validate(corrida.estado["run_state_json"])
    for razon in acta.validaciones[0].razones_rechazo:  # el motivo es el del ValidationReport
        assert razon in veto.detalle


def test_iteraciones_agotadas_y_propuesta_por_defecto_quedan_dichas(
    config: Config, provider: CSVPriceProvider, tmp_path: Path
) -> None:
    maximo = config.validacion.max_iteraciones_constructor
    llm = LlmPorAgente(
        analista=[CRIPTO_EUFORICO],
        constructor=["No llamo a nada."] * maximo,
        reporter=["No hay cartera aprobada."],
    )
    eventos = [h.evento for h in leer_hitos(_correr(config, provider, llm, tmp_path).estado)]
    assert eventos.count(E.PROPUESTA_POR_DEFECTO) == maximo and E.PROPUESTA not in eventos
    assert eventos.count(E.VETO) == maximo
    assert eventos[-2:] == [E.ITERACIONES_AGOTADAS, E.ACTA_CONSOLIDADA]


def test_la_bitacora_es_legible_mientras_el_comite_sigue_corriendo(
    config: Config, provider: CSVPriceProvider, tmp_path: Path
) -> None:
    """Lo que vería ``make bitacora`` desde otra terminal en mitad de la corrida: cuando el
    Reporter recibe su turno, el archivo ya cuenta todo lo deliberado y aún no hay acta."""
    visto: list[list[EventoComite]] = []

    def reporter(_: LlmRequest) -> str:
        (bitacora,) = tmp_path.glob(f"*/{ARCHIVO_BITACORA}")
        assert not (bitacora.parent / ARCHIVO_RUN_STATE).exists()
        visto.append([h.evento for h in leer_bitacora(bitacora)])
        return "El comité aprobó la cartera propuesta."

    _correr(config, provider, LlmPorAgente(**{**_aprobada(), "reporter": [reporter]}), tmp_path)
    assert visto == [
        [E.SESION_ABIERTA, E.VIEWS_EMITIDAS, E.MERCADO_ESTIMADO, E.PROPUESTA, E.APROBADA]
    ]
