"""Cascada del prior de equilibrio de Black-Litterman (ADR-013). Código puro.

Por activo: cap de la ``fuente`` → cap del ``usuario`` → nada. Sobre el vector, todo o nada:
si todas las caps están, w_mkt ∝ caps; si falta alguna y el usuario aceptó degradar, TODO el
universo pasa al prior de ``prior_equilibrio.degradacion`` (neutral = equal-weight; solo_views
= π = 0); si falta alguna y no se aceptó, BL no está disponible (``PriorNoDisponibleError``).
Nunca se mezclan procedencias ni se inventa una cap.
"""

from __future__ import annotations

import numpy as np

from investmentsys.config import OptimizacionConfig, PriorEquilibrioConfig
from investmentsys.contracts import (
    ADVERTENCIA_PRIOR_NEUTRAL,
    ADVERTENCIA_PRIOR_SOLO_VIEWS,
    EstadoPrior,
    MetodoPrior,
    PriorActivo,
    PriorProvenance,
    PriorSnapshot,
    QuantEstimates,
    Universe,
)
from investmentsys.portfolio._comun import Vector, matriz


class PriorNoDisponibleError(ValueError):
    """Falta alguna cap y no se aceptó degradar: Black-Litterman no puede calcularse."""


def mensaje_estado_prior(universo: Universe) -> str:
    estado = universo.estado_prior
    if estado is EstadoPrior.CAPITALIZACION:
        return "prior de mercado: todas las capitalizaciones están congeladas con procedencia"
    faltan = ", ".join(universo.sin_cap)
    if estado is EstadoPrior.NEUTRAL:
        return (
            f"prior degradado con confirmación del usuario (sin cap: {faltan}): afecta a TODOS "
            "los activos, no solo a los que no tienen cap"
        )
    return (
        f"Black-Litterman no disponible: falta la capitalización de {faltan}. Apórtala con "
        "refrescar_cap(ticker, prior_cap, prior_metodologia) o acepta degradar TODO el universo a "
        "prior neutral (aceptar_neutral=True). HRP y mínima varianza siguen operativos"
    )


def resolver_prior(
    universo: Universe,
    estimates: QuantEstimates,
    optimizacion: OptimizacionConfig,
    prior: PriorEquilibrioConfig,
) -> PriorSnapshot:
    """El prior efectivo de ``universo`` con su tabla π = δ·Σ·w_mkt (en exceso de rf)."""
    if estimates.activos != universo.activos:
        raise ValueError("las estimaciones no corresponden al universo (activos u orden distintos)")
    if estimates.universe_version not in (None, universo.version):
        raise ValueError("las estimaciones están selladas con otra versión del universo")
    estado = universo.estado_prior
    if estado is EstadoPrior.PENDIENTE:
        raise PriorNoDisponibleError(mensaje_estado_prior(universo))

    n = len(universo.activos)
    delta, rf = optimizacion.aversion_riesgo_delta, optimizacion.tasa_libre_riesgo
    sigma = matriz(estimates, optimizacion.metodo_covarianza)
    w: Vector | None
    if estado is EstadoPrior.CAPITALIZACION:
        metodo, advertencia = MetodoPrior.CAPITALIZACION, None
        caps = np.array([d.prior_cap for d in universo.diagnosticos], dtype=float)
        w = np.asarray(caps / caps.sum(), dtype=float)
    elif prior.degradacion == "neutral":
        metodo, advertencia = MetodoPrior.NEUTRAL, ADVERTENCIA_PRIOR_NEUTRAL
        w = np.full(n, 1.0 / n)
    else:
        metodo, advertencia = MetodoPrior.SOLO_VIEWS, ADVERTENCIA_PRIOR_SOLO_VIEWS
        w = None
    pi = np.zeros(n) if w is None else np.asarray(delta * sigma @ w, dtype=float)

    de_mercado = metodo is MetodoPrior.CAPITALIZACION
    filas = tuple(
        PriorActivo(
            activo=d.ticker,
            procedencia=d.prior_provenance
            if de_mercado and d.prior_provenance
            else PriorProvenance.NEUTRAL,
            cap=d.prior_cap if de_mercado else None,
            fuente_detalle=d.prior_fuente_detalle if de_mercado else None,
            as_of=d.prior_as_of if de_mercado else None,
            peso_mercado=None if w is None else float(w[i]),
            pi_exceso=float(pi[i]),
            pi_total=float(pi[i]) + rf,
        )
        for i, d in enumerate(universo.diagnosticos)
    )
    return PriorSnapshot(
        universe_version=universo.version,
        metodo=metodo,
        delta=delta,
        tasa_libre_riesgo=rf,
        metodo_covarianza=optimizacion.metodo_covarianza,
        activos=filas,
        advertencia=advertencia,
    )
