"""Hierarchical Risk Parity (López de Prado, 2016). Código puro (ADR-003).

1. Distancia d_ij = √(½·(1 − ρ_ij)) a partir de la correlación implícita en Σ.
2. Agrupamiento jerárquico con enlace simple (``scipy.cluster.hierarchy``).
3. Cuasi-diagonalización: orden de las hojas del dendrograma.
4. Bisección recursiva: en cada corte se reparte el peso entre las dos mitades en
   proporción inversa a la varianza de cada mitad, con pesos de varianza inversa dentro.

HRP no admite límites por construcción. Si el resultado viola ``restricciones`` se
proyecta al punto factible más cercano (norma euclídea) y se registra
``parametros["proyectado"] = True``.
"""

from __future__ import annotations

from typing import Final

import numpy as np
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform

from investmentsys.config import OptimizacionConfig
from investmentsys.contracts import (
    CandidatePortfolio,
    PortfolioConstraints,
    QuantEstimates,
    TecnicaOptimizacion,
)
from investmentsys.contracts.common import TOLERANCIA_NUMERICA
from investmentsys.portfolio._comun import (
    Matriz,
    Vector,
    matriz,
    metricas_ex_ante,
    pesos_a_dict,
    proyectar,
    retornos_historicos,
    verificar_universo,
)

NOMBRE_CANDIDATO = "hrp"
METODO_ENLACE: Final = "single"


def optimizar_hrp(
    estimates: QuantEstimates,
    restricciones: PortfolioConstraints,
    optimizacion: OptimizacionConfig,
) -> CandidatePortfolio:
    verificar_universo(estimates, restricciones)
    activos = estimates.activos
    sigma = matriz(estimates, optimizacion.metodo_covarianza)
    w = pesos_hrp(sigma)
    proyectado = False
    if _viola(w, restricciones):
        w = proyectar(w, restricciones)
        proyectado = True
    return CandidatePortfolio(
        nombre=NOMBRE_CANDIDATO,
        tecnica=TecnicaOptimizacion.HRP,
        pesos=pesos_a_dict(activos, w),
        metricas=metricas_ex_ante(
            w, retornos_historicos(estimates), sigma, optimizacion.tasa_libre_riesgo
        ),
        retornos_esperados=pesos_a_dict(activos, retornos_historicos(estimates)),
        parametros={
            "metodo_covarianza": str(optimizacion.metodo_covarianza),
            "enlace": METODO_ENLACE,
            "proyectado": proyectado,
        },
    )


def pesos_hrp(sigma: Matriz) -> Vector:
    """Pesos HRP crudos (suman 1, sin límites) para una covarianza Σ."""
    n = sigma.shape[0]
    if n == 1:
        return np.ones(1)
    desviaciones = np.sqrt(np.diag(sigma))
    correlacion = sigma / np.outer(desviaciones, desviaciones)
    distancia = np.sqrt(np.clip(0.5 * (1.0 - correlacion), 0.0, None))
    np.fill_diagonal(distancia, 0.0)
    enlaces = linkage(squareform(distancia, checks=False), method=METODO_ENLACE)
    orden = [int(i) for i in leaves_list(enlaces)]
    w = np.ones(n)
    grupos = [orden]
    while grupos:
        grupos = [
            mitad
            for grupo in grupos
            if len(grupo) > 1
            for mitad in (grupo[: len(grupo) // 2], grupo[len(grupo) // 2 :])
        ]
        for izq, der in zip(grupos[0::2], grupos[1::2], strict=True):
            var_izq, var_der = _varianza_grupo(sigma, izq), _varianza_grupo(sigma, der)
            alpha = 1.0 - var_izq / (var_izq + var_der)
            w[izq] *= alpha
            w[der] *= 1.0 - alpha
    return np.asarray(w / w.sum(), dtype=float)


def _varianza_grupo(sigma: Matriz, indices: list[int]) -> float:
    sub = sigma[np.ix_(indices, indices)]
    w_iv = 1.0 / np.diag(sub)
    w_iv /= w_iv.sum()
    return float(w_iv @ sub @ w_iv)


def _viola(w: Vector, restricciones: PortfolioConstraints) -> bool:
    for peso, (lo, hi) in zip(w, restricciones.limites_ordenados(), strict=True):
        if peso < lo - TOLERANCIA_NUMERICA or peso > hi + TOLERANCIA_NUMERICA:
            return True
    return abs(float(w.sum()) - restricciones.suma_pesos) > TOLERANCIA_NUMERICA
