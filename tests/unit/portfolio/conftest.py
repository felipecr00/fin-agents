"""Fixtures de ``portfolio/``: estimaciones reales del repo, config y restricciones."""

from __future__ import annotations

from pathlib import Path

import pytest

from investmentsys.config import Config, cargar_config
from investmentsys.contracts import MetodoCovarianza, PortfolioConstraints, QuantEstimates
from investmentsys.data import CSVPriceProvider
from investmentsys.quant import estimar
from tests.conftest import ACTIVOS, FECHA

RAIZ = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config()


@pytest.fixture(scope="module")
def estimates_reales(config: Config) -> QuantEstimates:
    provider = CSVPriceProvider(RAIZ / config.datos.ruta_csv)
    return estimar(
        provider.retornos_log(ACTIVOS, hasta=FECHA),
        fecha_decision=FECHA,
        periodos_por_anio=provider.periodos_por_anio,
        ventana_meses=config.datos.ventana_covarianza_meses,
        metodos=(MetodoCovarianza.HISTORICA, MetodoCovarianza.LEDOIT_WOLF),
        nivel_confianza=config.estimacion.nivel_confianza,
    )


@pytest.fixture(scope="module")
def restricciones(config: Config) -> PortfolioConstraints:
    return PortfolioConstraints(
        activos=ACTIVOS,
        peso_min=config.optimizacion.peso_min,
        peso_max=config.optimizacion.peso_max,
        permitir_cortos=config.optimizacion.permitir_cortos,
    )


@pytest.fixture(scope="module")
def sin_limites() -> PortfolioConstraints:
    return PortfolioConstraints(activos=ACTIVOS, peso_min=0.0, peso_max=1.0)
