"""Mínima varianza global con límites por activo. Código puro (ADR-003).

min wᵀΣw sujeto a Σw = ``suma_pesos`` y límites de ``restricciones`` (SLSQP, punto
inicial determinista). El retorno ex ante se calcula con los retornos históricos de
``estimates`` (el optimizador no los usa).
"""

from __future__ import annotations

import numpy as np

from investmentsys.config import OptimizacionConfig
from investmentsys.contracts import (
    CandidatePortfolio,
    PortfolioConstraints,
    QuantEstimates,
    TecnicaOptimizacion,
)
from investmentsys.portfolio._comun import (
    matriz,
    metricas_ex_ante,
    pesos_a_dict,
    resolver_qp,
    retornos_historicos,
    verificar_universo,
)

NOMBRE_CANDIDATO = "min_varianza"


def optimizar_min_varianza(
    estimates: QuantEstimates,
    restricciones: PortfolioConstraints,
    optimizacion: OptimizacionConfig,
) -> CandidatePortfolio:
    verificar_universo(estimates, restricciones)
    activos = estimates.activos
    sigma = matriz(estimates, optimizacion.metodo_covarianza)
    w = resolver_qp(
        lambda w: float(w @ sigma @ w),
        lambda w: np.asarray(2.0 * sigma @ w, dtype=float),
        restricciones,
    )
    mu = retornos_historicos(estimates)
    return CandidatePortfolio(
        nombre=NOMBRE_CANDIDATO,
        tecnica=TecnicaOptimizacion.MIN_VARIANZA,
        pesos=pesos_a_dict(activos, w),
        metricas=metricas_ex_ante(w, mu, sigma, optimizacion.tasa_libre_riesgo),
        retornos_esperados=pesos_a_dict(activos, mu),
        parametros={"metodo_covarianza": str(optimizacion.metodo_covarianza)},
    )
