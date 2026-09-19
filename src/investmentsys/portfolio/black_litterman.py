"""Black-Litterman. Código puro: sin ADK, sin LLM (ADR-003).

Reproduce ``docs/referencia_black_litterman.py`` (golden test):

1. Σ = covarianza de ``estimates`` según ``optimizacion.metodo_covarianza``.
2. Prior de equilibrio π = δ·Σ·w_mkt, en exceso de la tasa libre de riesgo, con w_mkt
   proporcional a las capitalizaciones de ``prior``.
3. Q en exceso de rf para views absolutas (``q_anual`` es retorno total); tal cual para
   relativas. Ω = diag(P·τΣ·Pᵀ) (He-Litterman).
4. Posterior μ_BL = M·[(τΣ)⁻¹π + PᵀΩ⁻¹Q], M = [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹, Σ_BL = Σ + M.
5. max wᵀμ_BL − ½·δ·wᵀΣ_BL·w sujeto a Σw = 1 y límites (SLSQP).

Sin views, el posterior es el equilibrio (μ_BL = π, M = τΣ). ``retornos_esperados``
se devuelven como retornos totales (μ_BL + rf) y la volatilidad ex ante se calcula con Σ.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from investmentsys.config import MetodoOmega, OptimizacionConfig, PriorEquilibrioConfig
from investmentsys.contracts import (
    CandidatePortfolio,
    MarketViews,
    PortfolioConstraints,
    QuantEstimates,
    TecnicaOptimizacion,
    TipoView,
)
from investmentsys.portfolio._comun import (
    Matriz,
    Vector,
    matriz,
    metricas_ex_ante,
    pesos_a_dict,
    resolver_qp,
    verificar_universo,
)

NOMBRE_CANDIDATO = "black_litterman"


def optimizar_black_litterman(
    estimates: QuantEstimates,
    views: MarketViews,
    restricciones: PortfolioConstraints,
    optimizacion: OptimizacionConfig,
    prior: PriorEquilibrioConfig,
) -> CandidatePortfolio:
    """Cartera óptima según Black-Litterman con límites por activo (ver módulo)."""
    verificar_universo(estimates, restricciones)
    if views.activos != estimates.activos:
        raise ValueError("las views y las estimaciones deben compartir el orden canónico")
    if views.fecha_decision != estimates.fecha_decision:
        raise ValueError("views y estimaciones con fecha de decisión distinta")

    activos = estimates.activos
    delta, tau, rf = (
        optimizacion.aversion_riesgo_delta,
        optimizacion.tau,
        optimizacion.tasa_libre_riesgo,
    )
    post = posterior_black_litterman(estimates, views, optimizacion, prior)
    mu_bl, sigma = post.mu, post.sigma
    w = pesos_optimos(mu_bl, post.sigma_bl, delta, restricciones)
    retornos_totales = mu_bl + rf
    return CandidatePortfolio(
        nombre=NOMBRE_CANDIDATO,
        tecnica=TecnicaOptimizacion.BLACK_LITTERMAN,
        pesos=pesos_a_dict(activos, w),
        metricas=metricas_ex_ante(w, retornos_totales, sigma, rf),
        retornos_esperados=pesos_a_dict(activos, retornos_totales),
        parametros={
            "delta": delta,
            "tau": tau,
            "tasa_libre_riesgo": rf,
            "metodo_omega": str(optimizacion.metodo_omega),
            "metodo_covarianza": str(optimizacion.metodo_covarianza),
            "prior": prior.metodo,
            "n_views": len(views.views),
        },
    )


@dataclass(frozen=True)
class PosteriorBL:
    """Posterior de Black-Litterman: lo que entra al optimizador (pasos 1-4 del módulo)."""

    mu: Vector
    """μ_BL en exceso de la tasa libre de riesgo."""
    sigma: Matriz
    sigma_bl: Matriz


def posterior_black_litterman(
    estimates: QuantEstimates,
    views: MarketViews,
    optimizacion: OptimizacionConfig,
    prior: PriorEquilibrioConfig,
) -> PosteriorBL:
    delta, tau = optimizacion.aversion_riesgo_delta, optimizacion.tau
    activos = estimates.activos
    sigma = matriz(estimates, optimizacion.metodo_covarianza)
    pi = prior_equilibrio(sigma, pesos_mercado(prior, activos), delta)
    p = np.array(views.matriz_p(), dtype=float).reshape(len(views.views), len(activos))
    q = vector_q_en_exceso(views, optimizacion.tasa_libre_riesgo)
    omega = matriz_omega(p, sigma, tau, optimizacion.metodo_omega)
    mu_bl, m = posterior(pi, sigma, tau, p, q, omega)
    return PosteriorBL(mu=mu_bl, sigma=sigma, sigma_bl=sigma + m)


def pesos_optimos(
    mu: Vector, sigma_bl: Matriz, delta: float, restricciones: PortfolioConstraints
) -> Vector:
    """max wᵀμ − ½·δ·wᵀΣ_BL·w sujeto a Σw = 1 y límites (paso 5 del módulo)."""
    return resolver_qp(
        lambda w: float(-(w @ mu - 0.5 * delta * w @ sigma_bl @ w)),
        lambda w: np.asarray(-(mu - delta * sigma_bl @ w), dtype=float),
        restricciones,
    )


def pesos_mercado(prior: PriorEquilibrioConfig, activos: tuple[str, ...]) -> Vector:
    caps = np.array([prior.capitalizacion_usd_billones[a] for a in activos], dtype=float)
    return np.asarray(caps / caps.sum(), dtype=float)


def prior_equilibrio(sigma: Matriz, w_mkt: Vector, delta: float) -> Vector:
    """π = δ·Σ·w_mkt (retorno en exceso de la tasa libre de riesgo)."""
    return np.asarray(delta * sigma @ w_mkt, dtype=float)


def vector_q_en_exceso(views: MarketViews, tasa_libre_riesgo: float) -> Vector:
    return np.array(
        [
            v.q_anual - tasa_libre_riesgo if v.tipo is TipoView.ABSOLUTA else v.q_anual
            for v in views.views
        ],
        dtype=float,
    )


def matriz_omega(p: Matriz, sigma: Matriz, tau: float, metodo: MetodoOmega) -> Matriz:
    if metodo is MetodoOmega.HE_LITTERMAN:
        return np.asarray(np.diag(np.diag(p @ (tau * sigma) @ p.T)), dtype=float)
    raise NotImplementedError(
        f"metodo_omega={metodo}: solo he_litterman está implementado (ADR-003); "
        "idzorek se implementa cuando un sprint lo necesite"
    )


def posterior(
    pi: Vector, sigma: Matriz, tau: float, p: Matriz, q: Vector, omega: Matriz
) -> tuple[Vector, Matriz]:
    """(μ_BL, M) con M la covarianza del estimador del retorno medio (He-Litterman)."""
    inv_tau_sigma = np.linalg.inv(tau * sigma)
    if p.shape[0] == 0:
        return np.asarray(pi, dtype=float), np.asarray(tau * sigma, dtype=float)
    inv_omega = np.linalg.inv(omega)
    m = np.linalg.inv(inv_tau_sigma + p.T @ inv_omega @ p)
    mu = m @ (inv_tau_sigma @ pi + p.T @ inv_omega @ q)
    return np.asarray(mu, dtype=float), np.asarray((m + m.T) / 2.0, dtype=float)
