"""ADR-009: el RunState viaja en la sesión y el replay local reproduce sus números."""

from __future__ import annotations

from pathlib import Path

import pytest

from investmentsys.config import Config
from investmentsys.contracts import RunState
from investmentsys.data import CSVPriceProvider
from investmentsys.orchestrator import (
    CLAVE_DIRECTORIO,
    CLAVE_RUN_STATE,
    crear_pipeline,
    repetir,
)
from investmentsys.orchestrator.corrida import CLAVE_NOTAS
from investmentsys.orchestrator.replay import ReplayImposibleError
from tests.almacen import universo_referencia
from tests.integration.conftest import Corrida, Llamada, LlmPorAgente, ejecutar
from tests.integration.test_market_analyst import BORRADOR_GOLDEN
from tests.integration.test_pipeline import CRIPTO_EUFORICO, NARRATIVA, _leer


def _una_ronda() -> LlmPorAgente:
    return LlmPorAgente(
        analista=[BORRADOR_GOLDEN],
        constructor=[Llamada("construir_candidatos"), "Black-Litterman con los límites."],
        reporter=[NARRATIVA],
    )


def _dos_rondas() -> LlmPorAgente:
    return LlmPorAgente(
        analista=[CRIPTO_EUFORICO],
        constructor=[
            Llamada("construir_candidatos"),
            "Primera propuesta.",
            Llamada("construir_candidatos", recomendado="hrp", peso_max_por_activo={"IBIT": 0.05}),
            "Endurecí el máximo de IBIT y recomendé HRP.",
        ],
        reporter=["Se rechazó la primera propuesta y se aprobó la segunda."],
    )


def _correr(config: Config, provider: CSVPriceProvider, llm: LlmPorAgente, runs: Path) -> Corrida:
    return ejecutar(
        crear_pipeline(config, provider, llm, directorio_runs=runs, universo=universo_referencia())
    )


def test_el_run_state_de_la_sesion_es_el_del_disco(
    config: Config, provider: CSVPriceProvider, tmp_path: Path
) -> None:
    corrida = _correr(config, provider, _una_ronda(), tmp_path)
    en_disco, _ = _leer(corrida)
    assert RunState.model_validate(corrida.estado[CLAVE_RUN_STATE]) == en_disco


def test_disco_no_escribible_no_tumba_la_corrida(
    config: Config, provider: CSVPriceProvider, tmp_path: Path
) -> None:
    ocupado = tmp_path / "runs"
    ocupado.write_text("un archivo donde debería ir el directorio", encoding="utf-8")
    corrida = _correr(config, provider, _una_ronda(), ocupado)

    assert CLAVE_DIRECTORIO not in corrida.estado
    assert RunState.model_validate(corrida.estado[CLAVE_RUN_STATE]).aprobado
    assert any("solo en la sesión" in nota for nota in corrida.estado[CLAVE_NOTAS])


@pytest.mark.parametrize(("guion", "no_repetibles"), [(_una_ronda, 0), (_dos_rondas, 1)])
def test_replay_reproduce_la_corrida(
    config: Config,
    provider: CSVPriceProvider,
    tmp_path: Path,
    guion: type[LlmPorAgente],
    no_repetibles: int,
) -> None:
    corrida = _correr(config, provider, guion(), tmp_path)
    remota = RunState.model_validate(corrida.estado[CLAVE_RUN_STATE])
    resultado = repetir(remota, config, provider)

    assert resultado.reproduce and resultado.desviacion_maxima == 0.0
    assert resultado.comparados > 100  # covarianzas, pesos, métricas, backtest, stress
    assert len(resultado.no_repetible) == no_repetibles


def test_replay_delata_un_numero_alterado(
    config: Config, provider: CSVPriceProvider, tmp_path: Path
) -> None:
    corrida = _correr(config, provider, _una_ronda(), tmp_path)
    crudo = corrida.estado[CLAVE_RUN_STATE]
    delta = 10 * config.reproducibilidad.tolerancia_replay
    crudo["validaciones"][0]["metricas_oos"]["sharpe_oos"] += delta
    resultado = repetir(RunState.model_validate(crudo), config, provider)

    assert [d.ruta for d in resultado.diferencias] == ["validaciones[0].metricas_oos.sharpe_oos"]
    assert resultado.desviacion_maxima == pytest.approx(delta)


def test_replay_exige_la_misma_configuracion(
    config: Config, provider: CSVPriceProvider, tmp_path: Path
) -> None:
    corrida = _correr(config, provider, _una_ronda(), tmp_path)
    remota = RunState.model_validate(corrida.estado[CLAVE_RUN_STATE])
    with pytest.raises(ReplayImposibleError, match=r"config\.yaml"):
        repetir(remota.avanzar(config_hash="0" * 64), config, provider)
    with pytest.raises(ReplayImposibleError, match="semilla"):
        repetir(remota.avanzar(semilla=remota.semilla + 1), config, provider)
