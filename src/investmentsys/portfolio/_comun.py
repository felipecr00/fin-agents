"""Utilidades compartidas por los optimizadores de ``portfolio/``. Código puro (ADR-003).

Todo optimizador termina en un ``CandidatePortfolio``; aquí viven el QP con límites
(SLSQP con punto inicial determinista), la proyección al conjunto factible y las
métricas ex ante. Ningún parámetro financiero se fija aquí: llegan por argumentos.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import numpy.typing as npt
from scipy.optimize import LinearConstraint, minimize

from investmentsys.contracts import (
    MetodoCovarianza,
    MetricasExAnte,
    PortfolioConstraints,
    QuantEstimates,
)

Vector = npt.NDArray[np.float64]
Matriz = npt.NDArray[np.float64]

# Tolerancias numéricas del solver: precisión de punto flotante, no parámetros financieros.
_TOL_SOLVER = 1e-12
_MAX_ITER_SOLVER = 1000


class OptimizacionFallidaError(RuntimeError):
    """El solver no convergió o devolvió una solución infactible."""


def verificar_universo(estimates: QuantEstimates, restricciones: PortfolioConstraints) -> None:
    if restricciones.activos != estimates.activos:
        raise ValueError(
            f"restricciones sobre {restricciones.activos} pero estimaciones sobre "
            f"{estimates.activos}: el orden canónico debe coincidir"
        )


def matriz(estimates: QuantEstimates, metodo: MetodoCovarianza) -> Matriz:
    return np.array(estimates.covarianza(MetodoCovarianza(metodo)).valores, dtype=float)


def retornos_historicos(estimates: QuantEstimates) -> Vector:
    return np.array([r.media_anual for r in estimates.retornos_historicos], dtype=float)


def punto_inicial(limites: list[tuple[float, float]], suma: float) -> Vector:
    """Punto factible determinista: mínimos más el excedente repartido según la holgura."""
    lo = np.array([a for a, _ in limites], dtype=float)
    hi = np.array([b for _, b in limites], dtype=float)
    holgura = hi - lo
    excedente = suma - lo.sum()
    if holgura.sum() <= 0.0:
        return lo
    return np.asarray(lo + holgura * (excedente / holgura.sum()), dtype=float)


def resolver_qp(
    objetivo: Callable[[Vector], float],
    gradiente: Callable[[Vector], Vector],
    restricciones: PortfolioConstraints,
) -> Vector:
    """min ``objetivo(w)`` sujeto a Σw = ``suma_pesos`` y límites por activo (SLSQP)."""
    limites = restricciones.limites_ordenados()
    suma = restricciones.suma_pesos
    suma_unitaria = LinearConstraint(np.ones((1, len(limites))), suma, suma)
    resultado = minimize(
        objetivo,
        punto_inicial(limites, suma),
        jac=gradiente,
        method="SLSQP",
        bounds=limites,
        constraints=suma_unitaria,
        options={"ftol": _TOL_SOLVER, "maxiter": _MAX_ITER_SOLVER},
    )
    if not resultado.success:
        raise OptimizacionFallidaError(f"SLSQP: {resultado.message}")
    return ajustar_a_limites(np.asarray(resultado.x, dtype=float), limites)


def ajustar_a_limites(w: Vector, limites: list[tuple[float, float]]) -> Vector:
    """Elimina violaciones de redondeo del solver (orden 1e-16) sin alterar la suma."""
    lo = np.array([a for a, _ in limites], dtype=float)
    hi = np.array([b for _, b in limites], dtype=float)
    return np.asarray(np.clip(w, lo, hi), dtype=float)


def proyectar(w_objetivo: Vector, restricciones: PortfolioConstraints) -> Vector:
    """Punto factible más cercano en norma euclídea a ``w_objetivo``."""
    return resolver_qp(
        lambda w: float(np.sum((w - w_objetivo) ** 2)),
        lambda w: np.asarray(2.0 * (w - w_objetivo), dtype=float),
        restricciones,
    )


def metricas_ex_ante(
    w: Vector, mu: Vector, sigma: Matriz, tasa_libre_riesgo: float
) -> MetricasExAnte:
    retorno = float(w @ mu)
    volatilidad = math.sqrt(max(float(w @ sigma @ w), 0.0))
    sharpe = (retorno - tasa_libre_riesgo) / volatilidad if volatilidad > 0.0 else 0.0
    return MetricasExAnte(
        retorno_esperado_anual=retorno,
        volatilidad_anual=volatilidad,
        sharpe=sharpe,
        concentracion_hhi=float(np.sum(w**2)),
    )


def pesos_a_dict(activos: tuple[str, ...], w: Vector) -> dict[str, float]:
    return {a: float(p) for a, p in zip(activos, w, strict=True)}
