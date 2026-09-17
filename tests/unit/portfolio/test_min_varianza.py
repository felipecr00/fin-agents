"""Tests de mínima varianza contra el oráculo externo de ADR-003 y por propiedades."""

from __future__ import annotations

import numpy as np
import pytest

from investmentsys.config import Config
from investmentsys.contracts import (
    MetodoCovarianza,
    PortfolioConstraints,
    QuantEstimates,
    TecnicaOptimizacion,
)
from investmentsys.portfolio import OptimizacionFallidaError, optimizar_min_varianza
from investmentsys.portfolio._comun import proyectar, punto_inicial, resolver_qp
from tests.conftest import ACTIVOS

# Oráculo: PyPortfolioOpt 1.6.0 ``EfficientFrontier(None, Σ, weight_bounds).min_volatility()``
# con Σ la covarianza histórica híbrida de data/precios.csv.
MINVAR_ORACULO_2_70 = {"VOOG": 0.44289447, "BNS": 0.02, "IBIT": 0.02, "VB": 0.51710553}
MINVAR_ORACULO_0_1 = {"VOOG": 0.46215367, "BNS": 0.0, "IBIT": 0.0, "VB": 0.53784633}
TOLERANCIA_ORACULO = 1e-6


def test_reproduce_el_oraculo_con_limites(
    config: Config, estimates_reales: QuantEstimates, restricciones: PortfolioConstraints
) -> None:
    cartera = optimizar_min_varianza(estimates_reales, restricciones, config.optimizacion)
    assert cartera.tecnica is TecnicaOptimizacion.MIN_VARIANZA
    assert cartera.violaciones(restricciones) == []
    for a in ACTIVOS:
        assert cartera.pesos[a] == pytest.approx(MINVAR_ORACULO_2_70[a], abs=TOLERANCIA_ORACULO), a


def test_reproduce_el_oraculo_sin_limites(
    config: Config, estimates_reales: QuantEstimates, sin_limites: PortfolioConstraints
) -> None:
    cartera = optimizar_min_varianza(estimates_reales, sin_limites, config.optimizacion)
    for a in ACTIVOS:
        assert cartera.pesos[a] == pytest.approx(MINVAR_ORACULO_0_1[a], abs=TOLERANCIA_ORACULO), a


def test_la_varianza_es_minima_frente_a_perturbaciones(
    config: Config, estimates_reales: QuantEstimates, restricciones: PortfolioConstraints
) -> None:
    cartera = optimizar_min_varianza(estimates_reales, restricciones, config.optimizacion)
    sigma = np.array(estimates_reales.covarianza(MetodoCovarianza.HISTORICA).valores)
    w = np.array(cartera.pesos_ordenados(ACTIVOS))
    optimo = w @ sigma @ w
    assert cartera.metricas.volatilidad_anual == pytest.approx(np.sqrt(optimo))
    rng = np.random.default_rng(config.reproducibilidad.semilla)
    for _ in range(50):
        alt = proyectar(w + 0.02 * rng.standard_normal(4), restricciones)
        assert alt @ sigma @ alt >= optimo - 1e-12


def test_usa_la_covarianza_del_config(
    config: Config, estimates_reales: QuantEstimates, restricciones: PortfolioConstraints
) -> None:
    lw = config.optimizacion.model_copy(update={"metodo_covarianza": MetodoCovarianza.LEDOIT_WOLF})
    con_lw = optimizar_min_varianza(estimates_reales, restricciones, lw)
    con_hist = optimizar_min_varianza(estimates_reales, restricciones, config.optimizacion)
    assert con_lw.parametros["metodo_covarianza"] == "ledoit_wolf"
    assert con_lw.pesos != con_hist.pesos


def test_punto_inicial_es_factible() -> None:
    limites = [(0.02, 0.70), (0.02, 0.70), (0.02, 0.10), (0.30, 0.50)]
    w = punto_inicial(limites, 1.0)
    assert w.sum() == pytest.approx(1.0)
    for peso, (lo, hi) in zip(w, limites, strict=True):
        assert lo <= peso <= hi


def test_proyectar_devuelve_el_punto_factible_mas_cercano() -> None:
    restricciones = PortfolioConstraints(activos=ACTIVOS, peso_min=0.10, peso_max=0.40)
    """Proyección euclídea sobre {Σw = 1, límites}: w_i = clip(v_i + λ, lo, hi) con λ tal
    que la suma sea 1. Para v = (0.70, 0.20, 0.05, 0.05) y límites [0.10, 0.40], λ = 0.10."""
    objetivo = np.array([0.70, 0.20, 0.05, 0.05])
    w = proyectar(objetivo, restricciones)
    assert w.sum() == pytest.approx(1.0)
    np.testing.assert_allclose(w, [0.40, 0.30, 0.15, 0.15], atol=1e-6)
    # Un objetivo ya factible no se mueve.
    factible = np.array([0.40, 0.30, 0.15, 0.15])
    np.testing.assert_allclose(proyectar(factible, restricciones), factible, atol=1e-8)


def test_resolver_qp_informa_fallo_del_solver() -> None:
    restricciones = PortfolioConstraints(activos=ACTIVOS, peso_min=0.0, peso_max=1.0)
    with pytest.raises(OptimizacionFallidaError):
        resolver_qp(lambda w: float("nan"), lambda w: np.full(4, float("nan")), restricciones)
