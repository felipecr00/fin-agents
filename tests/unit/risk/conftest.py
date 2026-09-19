"""Fixtures de ``risk/``: precios reales del repo, config y el candidato de referencia."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from investmentsys.config import Config, cargar_config
from investmentsys.contracts import CandidatePortfolio, MetricasExAnte, TecnicaOptimizacion
from investmentsys.data import CSVPriceProvider
from tests.conftest import ACTIVOS, CSV_REFERENCIA, FECHA

PESOS_REFERENCIA = {"VOOG": 0.70, "BNS": 0.07, "IBIT": 0.02, "VB": 0.21}


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config()


@pytest.fixture(scope="module")
def provider(config: Config) -> CSVPriceProvider:
    return CSVPriceProvider(CSV_REFERENCIA)


@pytest.fixture(scope="module")
def precios_reales(provider: CSVPriceProvider) -> pd.DataFrame:
    """Los 61 cierres mensuales del fixture congelado hasta la fecha de decisión."""
    return provider.precios(ACTIVOS, hasta=FECHA)


def candidato(nombre: str, pesos: dict[str, float]) -> CandidatePortfolio:
    """Candidato con métricas ex ante de relleno: al Validador solo le importan los pesos."""
    return CandidatePortfolio(
        nombre=nombre,
        tecnica=TecnicaOptimizacion.BLACK_LITTERMAN,
        pesos=pesos,
        metricas=MetricasExAnte(
            retorno_esperado_anual=0.0,
            volatilidad_anual=0.0,
            sharpe=0.0,
            concentracion_hhi=sum(p * p for p in pesos.values()),
        ),
    )


@pytest.fixture(scope="module")
def candidato_referencia() -> CandidatePortfolio:
    return candidato("bl_referencia", PESOS_REFERENCIA)


def panel_manual() -> pd.DataFrame:
    """Dos activos, tres cierres: A sube 10 % y luego cae 20 %; B es plano y luego sube 10 %."""
    fechas = pd.DatetimeIndex(
        [date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31)], name="fecha"
    )
    return pd.DataFrame({"A": [100.0, 110.0, 88.0], "B": [50.0, 50.0, 55.0]}, index=fechas)


def panel_con_inicio_tardio() -> pd.DataFrame:
    """C no cotiza en la primera fecha."""
    panel = panel_manual()
    panel["C"] = [np.nan, 10.0, 12.0]
    return panel
