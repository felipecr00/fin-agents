"""Black-Litterman. Código puro: sin ADK, sin LLM. Implementación en S1."""

from __future__ import annotations

from investmentsys.config import OptimizacionConfig, PriorEquilibrioConfig
from investmentsys.contracts import (
    CandidatePortfolio,
    MarketViews,
    PortfolioConstraints,
    QuantEstimates,
)


def optimizar_black_litterman(
    estimates: QuantEstimates,
    views: MarketViews,
    restricciones: PortfolioConstraints,
    optimizacion: OptimizacionConfig,
    prior: PriorEquilibrioConfig,
) -> CandidatePortfolio:
    """Cartera óptima según Black-Litterman con límites por activo.

    Contrato esperado por el golden test (``docs/referencia_black_litterman.py``):
    1. Σ = ``estimates.covarianzas[optimizacion.metodo_covarianza]``.
    2. Prior de equilibrio π = δ·Σ·w_mkt, con w_mkt proporcional a ``prior``.
    3. Q: en views absolutas se resta la tasa libre de riesgo (``q_anual`` es retorno
       total); en relativas se usa tal cual. Ω según ``optimizacion.metodo_omega``.
    4. Posterior μ_BL y Σ_BL = Σ + M (He-Litterman).
    5. max  wᵀμ_BL − ½·δ·wᵀΣ_BL·w  sujeto a Σw = 1 y límites de ``restricciones``.

    Devuelve ``retornos_esperados`` como retornos TOTALES (μ_BL + rf) y métricas ex ante
    con volatilidad calculada sobre Σ (no Σ_BL).
    """
    raise NotImplementedError("S1: optimizar_black_litterman pendiente de implementación")
