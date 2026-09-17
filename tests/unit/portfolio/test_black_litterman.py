"""Tests unitarios de Black-Litterman (el golden test cubre el ejercicio completo)."""

from __future__ import annotations

import numpy as np
import pytest

from investmentsys.config import Config, MetodoOmega
from investmentsys.contracts import (
    MarketViews,
    MetodoCovarianza,
    PortfolioConstraints,
    QuantEstimates,
    TecnicaOptimizacion,
    TipoView,
    View,
)
from investmentsys.portfolio import optimizar_black_litterman
from investmentsys.portfolio.black_litterman import (
    matriz_omega,
    pesos_mercado,
    posterior,
    prior_equilibrio,
    vector_q_en_exceso,
)
from tests.conftest import ACTIVOS, FECHA


def _sin_views() -> MarketViews:
    return MarketViews(
        fecha_decision=FECHA, activos=ACTIVOS, horizonte_meses=12, resumen="Sin opiniones."
    )


def test_prior_de_equilibrio_es_delta_sigma_w(
    config: Config, estimates_reales: QuantEstimates
) -> None:
    sigma = np.array(estimates_reales.covarianza(MetodoCovarianza.HISTORICA).valores)
    w_mkt = pesos_mercado(config.prior_equilibrio, ACTIVOS)
    assert w_mkt.sum() == pytest.approx(1.0)
    assert w_mkt[0] == pytest.approx(28.0 / (28.0 + 0.116 + 1.9 + 2.5))
    pi = prior_equilibrio(sigma, w_mkt, config.optimizacion.aversion_riesgo_delta)
    np.testing.assert_allclose(pi, 2.5 * sigma @ w_mkt)


def test_q_descuenta_rf_solo_en_views_absolutas(views_golden: MarketViews) -> None:
    np.testing.assert_allclose(vector_q_en_exceso(views_golden, 0.04), [-0.01, 0.03, 0.06])


def test_omega_he_litterman_es_la_diagonal_de_p_tau_sigma_pt(views_golden: MarketViews) -> None:
    sigma = np.diag([0.04, 0.05, 0.25, 0.03])
    p = np.array(views_golden.matriz_p(), dtype=float)
    omega = matriz_omega(p, sigma, 0.05, MetodoOmega.HE_LITTERMAN)
    np.testing.assert_allclose(omega, np.diag(np.diag(p @ (0.05 * sigma) @ p.T)))
    assert np.count_nonzero(omega - np.diag(np.diag(omega))) == 0


def test_omega_idzorek_no_esta_implementado(views_golden: MarketViews) -> None:
    p = np.array(views_golden.matriz_p(), dtype=float)
    with pytest.raises(NotImplementedError, match="idzorek"):
        matriz_omega(p, np.eye(4), 0.05, MetodoOmega.IDZOREK)


def test_sin_views_el_posterior_es_el_equilibrio() -> None:
    sigma = np.array([[0.04, 0.01], [0.01, 0.09]])
    pi = np.array([0.05, 0.08])
    mu, m = posterior(pi, sigma, 0.05, np.empty((0, 2)), np.empty(0), np.empty((0, 0)))
    np.testing.assert_allclose(mu, pi)
    np.testing.assert_allclose(m, 0.05 * sigma)


def test_view_absoluta_con_omega_casi_nula_impone_su_retorno() -> None:
    sigma = np.array([[0.04, 0.01], [0.01, 0.09]])
    pi = np.array([0.05, 0.08])
    p, q = np.array([[1.0, 0.0]]), np.array([0.20])
    mu, _ = posterior(pi, sigma, 0.05, p, q, np.array([[1e-12]]))
    assert mu[0] == pytest.approx(0.20, abs=1e-6)


def test_view_con_omega_enorme_no_mueve_el_prior() -> None:
    sigma = np.array([[0.04, 0.01], [0.01, 0.09]])
    pi = np.array([0.05, 0.08])
    p, q = np.array([[1.0, 0.0]]), np.array([0.20])
    mu, _ = posterior(pi, sigma, 0.05, p, q, np.array([[1e12]]))
    np.testing.assert_allclose(mu, pi, atol=1e-8)


def test_candidato_sin_views_respeta_limites_y_devuelve_totales(
    config: Config, estimates_reales: QuantEstimates, restricciones: PortfolioConstraints
) -> None:
    cartera = optimizar_black_litterman(
        estimates_reales, _sin_views(), restricciones, config.optimizacion, config.prior_equilibrio
    )
    assert cartera.tecnica is TecnicaOptimizacion.BLACK_LITTERMAN
    assert cartera.violaciones(restricciones) == []
    assert cartera.retornos_esperados is not None
    sigma = np.array(estimates_reales.covarianza(MetodoCovarianza.HISTORICA).valores)
    pi = prior_equilibrio(
        sigma,
        pesos_mercado(config.prior_equilibrio, ACTIVOS),
        config.optimizacion.aversion_riesgo_delta,
    )
    for i, a in enumerate(ACTIVOS):
        assert cartera.retornos_esperados[a] == pytest.approx(
            pi[i] + config.optimizacion.tasa_libre_riesgo
        )
    assert cartera.parametros["n_views"] == 0
    assert cartera.parametros["metodo_omega"] == "he_litterman"


def test_sin_views_ni_limites_activos_coincide_con_la_solucion_analitica(
    config: Config, estimates_reales: QuantEstimates
) -> None:
    """Sin views, μ = δΣw_mkt y Σ_BL = (1+τ)Σ. Con Σw = 1 y límites no activos, el óptimo
    de la utilidad cuadrática es w = w_mkt/(1+τ) + c·Σ⁻¹1 con c = (1 − 1/(1+τ)) / (1ᵀΣ⁻¹1)."""
    amplias = PortfolioConstraints(
        activos=ACTIVOS, peso_min=-1.0, peso_max=1.0, permitir_cortos=True
    )
    cartera = optimizar_black_litterman(
        estimates_reales, _sin_views(), amplias, config.optimizacion, config.prior_equilibrio
    )
    sigma = np.array(estimates_reales.covarianza(MetodoCovarianza.HISTORICA).valores)
    tau = config.optimizacion.tau
    w_mkt = pesos_mercado(config.prior_equilibrio, ACTIVOS)
    unos = np.ones(len(ACTIVOS))
    sigma_inv_unos = np.linalg.solve(sigma, unos)
    c = (1.0 - 1.0 / (1.0 + tau)) / (unos @ sigma_inv_unos)
    esperado = w_mkt / (1.0 + tau) + c * sigma_inv_unos
    # SLSQP con ftol=1e-12 sobre la utilidad fija los pesos con ~1e-6 de precisión.
    np.testing.assert_allclose(cartera.pesos_ordenados(ACTIVOS), esperado, atol=1e-5)


def test_las_metricas_usan_sigma_y_retornos_totales(
    config: Config,
    estimates_reales: QuantEstimates,
    restricciones: PortfolioConstraints,
    views_golden: MarketViews,
) -> None:
    cartera = optimizar_black_litterman(
        estimates_reales, views_golden, restricciones, config.optimizacion, config.prior_equilibrio
    )
    assert cartera.retornos_esperados is not None
    w = np.array(cartera.pesos_ordenados(ACTIVOS))
    mu = np.array([cartera.retornos_esperados[a] for a in ACTIVOS])
    sigma = np.array(estimates_reales.covarianza(MetodoCovarianza.HISTORICA).valores)
    assert cartera.metricas.retorno_esperado_anual == pytest.approx(w @ mu)
    assert cartera.metricas.volatilidad_anual == pytest.approx(np.sqrt(w @ sigma @ w))
    rf = config.optimizacion.tasa_libre_riesgo
    assert cartera.metricas.sharpe == pytest.approx((w @ mu - rf) / np.sqrt(w @ sigma @ w))
    assert cartera.metricas.concentracion_hhi == pytest.approx(np.sum(w**2))


def test_es_determinista(
    config: Config,
    estimates_reales: QuantEstimates,
    restricciones: PortfolioConstraints,
    views_golden: MarketViews,
) -> None:
    a = optimizar_black_litterman(
        estimates_reales, views_golden, restricciones, config.optimizacion, config.prior_equilibrio
    )
    b = optimizar_black_litterman(
        estimates_reales, views_golden, restricciones, config.optimizacion, config.prior_equilibrio
    )
    assert a == b


def test_una_view_alcista_sube_el_peso_del_activo(
    config: Config, estimates_reales: QuantEstimates, sin_limites: PortfolioConstraints
) -> None:
    base = optimizar_black_litterman(
        estimates_reales, _sin_views(), sin_limites, config.optimizacion, config.prior_equilibrio
    )
    alcista = MarketViews(
        fecha_decision=FECHA,
        activos=ACTIVOS,
        horizonte_meses=12,
        resumen="BNS muy por encima del equilibrio.",
        views=(
            View(
                tipo=TipoView.ABSOLUTA,
                coeficientes={"BNS": 1.0},
                q_anual=0.30,
                confianza=0.9,
                justificacion="Prueba de sensibilidad direccional.",
                fuente="test",
            ),
        ),
    )
    con_view = optimizar_black_litterman(
        estimates_reales, alcista, sin_limites, config.optimizacion, config.prior_equilibrio
    )
    assert con_view.pesos["BNS"] > base.pesos["BNS"]


def test_rechaza_universos_o_fechas_incoherentes(
    config: Config, estimates_reales: QuantEstimates, restricciones: PortfolioConstraints
) -> None:
    otro_orden = PortfolioConstraints(activos=ACTIVOS[::-1], peso_min=0.02, peso_max=0.70)
    with pytest.raises(ValueError, match="orden canónico"):
        optimizar_black_litterman(
            estimates_reales, _sin_views(), otro_orden, config.optimizacion, config.prior_equilibrio
        )
    otra_fecha = _sin_views().model_copy(update={"fecha_decision": FECHA.replace(day=1)})
    with pytest.raises(ValueError, match="fecha de decisión"):
        optimizar_black_litterman(
            estimates_reales,
            otra_fecha,
            restricciones,
            config.optimizacion,
            config.prior_equilibrio,
        )
