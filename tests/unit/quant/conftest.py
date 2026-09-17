"""Fixtures de ``quant/``: retornos reales del repo y paneles sintéticos deterministas."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from investmentsys.data import CSVPriceProvider
from tests.conftest import ACTIVOS, FECHA

RAIZ = Path(__file__).resolve().parents[3]
CSV_REAL = RAIZ / "data" / "precios.csv"
VENTANA = 60
PERIODOS = 12


@pytest.fixture(scope="module")
def retornos_reales() -> pd.DataFrame:
    return CSVPriceProvider(CSV_REAL).retornos_log(ACTIVOS, hasta=FECHA)


@pytest.fixture(scope="module")
def panel_comun(retornos_reales: pd.DataFrame) -> pd.DataFrame:
    """Ventana común de los cuatro activos (32 retornos, sin NaN)."""
    return retornos_reales.dropna()


def panel_sintetico(n_obs: int, semilla: int = 42) -> pd.DataFrame:
    """Panel completo con correlación conocida (semilla fija: misma entrada, misma salida)."""
    rng = np.random.default_rng(semilla)
    n = len(ACTIVOS)
    # Un factor con cargas y volatilidades idiosincráticas heterogéneas: la correlación
    # verdadera NO es constante, así que la contracción debe desvanecerse con más datos.
    cargas = np.array([0.3, 0.9, 1.6, 0.6])
    idiosincratica = np.array([0.02, 0.03, 0.10, 0.02])
    factor = rng.standard_normal((n_obs, 1))
    base = rng.standard_normal((n_obs, n))
    x = 0.03 * factor * cargas + base * idiosincratica
    indice = pd.date_range(end=pd.Timestamp(date(2026, 9, 30)), periods=n_obs, freq="ME")
    return pd.DataFrame(x, index=indice, columns=list(ACTIVOS))
