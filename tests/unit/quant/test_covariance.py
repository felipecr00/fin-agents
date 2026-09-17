"""Tests del estimador de covarianza (histórica híbrida y Ledoit-Wolf)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from investmentsys.contracts import MetodoCovarianza
from investmentsys.quant import MuestraInsuficienteError, estimar_covarianza, ledoit_wolf
from tests.conftest import ACTIVOS
from tests.unit.quant.conftest import PERIODOS, VENTANA, panel_sintetico

# Oráculo externo (ADR-003): intensidad de Ledoit-Wolf (2003, correlación constante) sobre la
# ventana común de data/precios.csv (32 retornos mensuales), calculada con la fórmula
# canónica (covarianza muestral con 1/T, como en covCor.m de los autores). PyPortfolioOpt
# 1.6.0 reproduce exactamente este valor cuando se le pasa esa covarianza muestral; con su
# valor por defecto (pandas .cov(), ddof=1, mezclado con momentos 1/T) da 0.6798.
DELTA_LW_ORACULO = 0.724423267
TOLERANCIA_ORACULO = 1e-8


# --- histórica híbrida ------------------------------------------------------------------


def test_historica_usa_toda_la_muestra_de_cada_activo(retornos_reales: pd.DataFrame) -> None:
    cov = estimar_covarianza(retornos_reales, MetodoCovarianza.HISTORICA, VENTANA, PERIODOS)
    assert cov.metodo is MetodoCovarianza.HISTORICA
    assert cov.activos == ACTIVOS
    assert cov.observaciones_por_activo == {"VOOG": 60, "BNS": 60, "IBIT": 32, "VB": 60}
    for activo in ("VOOG", "BNS", "VB"):
        esperada = retornos_reales[activo].std(ddof=1) * math.sqrt(PERIODOS)
        assert cov.volatilidad(activo) == pytest.approx(esperada)
    ibit = retornos_reales["IBIT"].dropna()
    assert cov.volatilidad("IBIT") == pytest.approx(ibit.std(ddof=1) * math.sqrt(PERIODOS))


def test_historica_correlaciones_por_par_en_ventana_comun(
    retornos_reales: pd.DataFrame,
) -> None:
    cov = estimar_covarianza(retornos_reales, MetodoCovarianza.HISTORICA, VENTANA, PERIODOS)
    i, j = ACTIVOS.index("VOOG"), ACTIVOS.index("IBIT")
    rho = cov.valores[i][j] / (cov.volatilidad("VOOG") * cov.volatilidad("IBIT"))
    comun = retornos_reales[["VOOG", "IBIT"]].dropna()
    assert rho == pytest.approx(comun["VOOG"].corr(comun["IBIT"]))
    # El par sin serie corta usa la muestra completa, no la ventana de IBIT.
    i, j = ACTIVOS.index("VOOG"), ACTIVOS.index("VB")
    rho = cov.valores[i][j] / (cov.volatilidad("VOOG") * cov.volatilidad("VB"))
    assert rho == pytest.approx(retornos_reales["VOOG"].corr(retornos_reales["VB"]))


def test_historica_con_panel_completo_es_la_covarianza_muestral() -> None:
    panel = panel_sintetico(48)
    cov = estimar_covarianza(panel, MetodoCovarianza.HISTORICA, 48, PERIODOS)
    esperada = np.cov(panel.to_numpy(), rowvar=False, ddof=1) * PERIODOS
    np.testing.assert_allclose(np.array(cov.valores), esperada, rtol=1e-12)


def test_la_ventana_recorta_las_observaciones_mas_antiguas() -> None:
    panel = panel_sintetico(48)
    cov = estimar_covarianza(panel, MetodoCovarianza.HISTORICA, 24, PERIODOS)
    esperada = np.cov(panel.iloc[-24:].to_numpy(), rowvar=False, ddof=1) * PERIODOS
    assert cov.ventana_meses == 24
    assert set(cov.observaciones_por_activo.values()) == {24}
    np.testing.assert_allclose(np.array(cov.valores), esperada, rtol=1e-12)


def test_es_determinista(retornos_reales: pd.DataFrame) -> None:
    a = estimar_covarianza(retornos_reales, MetodoCovarianza.HISTORICA, VENTANA, PERIODOS)
    b = estimar_covarianza(retornos_reales, MetodoCovarianza.HISTORICA, VENTANA, PERIODOS)
    assert a == b


def test_rechaza_activo_con_una_sola_observacion() -> None:
    panel = panel_sintetico(12)
    panel.iloc[:-1, panel.columns.get_loc("IBIT")] = np.nan
    with pytest.raises(MuestraInsuficienteError, match="IBIT"):
        estimar_covarianza(panel, MetodoCovarianza.HISTORICA, 12, PERIODOS)


def test_rechaza_par_sin_ventana_comun() -> None:
    panel = panel_sintetico(12)
    panel.iloc[:6, panel.columns.get_loc("IBIT")] = np.nan
    panel.iloc[6:, panel.columns.get_loc("VB")] = np.nan
    with pytest.raises(MuestraInsuficienteError, match="IBIT, VB"):
        estimar_covarianza(panel, MetodoCovarianza.HISTORICA, 12, PERIODOS)


def test_rechaza_parametros_no_positivos(retornos_reales: pd.DataFrame) -> None:
    with pytest.raises(ValueError):
        estimar_covarianza(retornos_reales, MetodoCovarianza.HISTORICA, 0, PERIODOS)


# --- Ledoit-Wolf --------------------------------------------------------------------------


def test_ledoit_wolf_reproduce_la_intensidad_del_oraculo(panel_comun: pd.DataFrame) -> None:
    x = panel_comun.to_numpy()
    sigma = np.cov(x, rowvar=False, ddof=1) * PERIODOS
    contraida, delta = ledoit_wolf(sigma, x)
    assert delta == pytest.approx(DELTA_LW_ORACULO, abs=TOLERANCIA_ORACULO)
    # Σ_LW = δ·F + (1−δ)·Σ con F de correlación constante y las varianzas de Σ.
    desviaciones = np.sqrt(np.diag(sigma))
    escala = np.outer(desviaciones, desviaciones)
    n = len(ACTIVOS)
    r_bar = (np.sum(sigma / escala) - n) / (n * (n - 1))
    objetivo = r_bar * escala
    np.fill_diagonal(objetivo, np.diag(sigma))
    np.testing.assert_allclose(contraida, delta * objetivo + (1 - delta) * sigma, rtol=1e-12)


def test_ledoit_wolf_preserva_varianzas_y_es_psd(retornos_reales: pd.DataFrame) -> None:
    hist = estimar_covarianza(retornos_reales, MetodoCovarianza.HISTORICA, VENTANA, PERIODOS)
    lw = estimar_covarianza(retornos_reales, MetodoCovarianza.LEDOIT_WOLF, VENTANA, PERIODOS)
    assert lw.metodo is MetodoCovarianza.LEDOIT_WOLF
    assert lw.observaciones_por_activo == hist.observaciones_por_activo
    for activo in ACTIVOS:
        assert lw.varianza(activo) == pytest.approx(hist.varianza(activo))
    autovalores = np.linalg.eigvalsh(np.array(lw.valores))
    assert autovalores.min() > 0.0


def test_ledoit_wolf_acerca_las_correlaciones_a_su_media(retornos_reales: pd.DataFrame) -> None:
    hist = estimar_covarianza(retornos_reales, MetodoCovarianza.HISTORICA, VENTANA, PERIODOS)
    lw = estimar_covarianza(retornos_reales, MetodoCovarianza.LEDOIT_WOLF, VENTANA, PERIODOS)

    def correlaciones(valores: tuple[tuple[float, ...], ...]) -> np.ndarray:
        m = np.array(valores)
        d = np.sqrt(np.diag(m))
        return m / np.outer(d, d)

    rho_h, rho_lw = correlaciones(hist.valores), correlaciones(lw.valores)
    fuera = ~np.eye(len(ACTIVOS), dtype=bool)
    assert np.std(rho_lw[fuera]) < np.std(rho_h[fuera])


def test_ledoit_wolf_intensidad_cae_con_mas_datos() -> None:
    deltas = []
    for n_obs in (24, 240, 2400):
        x = panel_sintetico(n_obs).to_numpy()
        _, delta = ledoit_wolf(np.cov(x, rowvar=False, ddof=1), x)
        assert 0.0 <= delta <= 1.0
        deltas.append(delta)
    assert deltas[0] > deltas[1] > deltas[2]


def test_ledoit_wolf_rechaza_panel_incompatible() -> None:
    x = panel_sintetico(24).to_numpy()
    with pytest.raises(ValueError):
        ledoit_wolf(np.eye(3), x)
    with pytest.raises(MuestraInsuficienteError):
        ledoit_wolf(np.eye(4), x[:1])
