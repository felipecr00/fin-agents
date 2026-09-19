"""La cartera que trae el usuario, como ``CandidatePortfolio`` evaluable. Código puro.

No optimiza nada: valida los pesos ANTES de cualquier cálculo (con mensajes que dicen qué
corregir) y les calcula las mismas métricas ex ante que a un candidato del Constructor, con
los retornos históricos y la covarianza configurada.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np

from investmentsys.config import OptimizacionConfig
from investmentsys.contracts import (
    CandidatePortfolio,
    QuantEstimates,
    TecnicaOptimizacion,
)
from investmentsys.contracts.common import TOLERANCIA_NUMERICA
from investmentsys.portfolio._comun import (
    matriz,
    metricas_ex_ante,
    pesos_a_dict,
    retornos_historicos,
)

NOMBRE_CANDIDATO = "cartera_usuario"


class CarteraInvalidaError(ValueError):
    """Los pesos del usuario no describen una cartera evaluable sobre el universo vigente."""


def validar_pesos_usuario(
    pesos: Mapping[str, float], activos: tuple[str, ...]
) -> dict[str, float]:
    """Pesos completos sobre ``activos`` (los omitidos valen 0), o ``CarteraInvalidaError``."""
    if not pesos:
        raise CarteraInvalidaError("cartera vacía: indica el peso de al menos un activo")
    normalizados = {str(a).strip().upper(): p for a, p in pesos.items()}
    fuera = sorted(set(normalizados) - set(activos))
    if fuera:
        raise CarteraInvalidaError(
            f"activos fuera del universo vigente: {fuera}. El universo es {list(activos)}: "
            "incorpóralos con el Gestor de Datos antes de evaluarlos, o quítalos de la cartera"
        )
    no_finitos = sorted(a for a, p in normalizados.items() if not math.isfinite(p))
    if no_finitos:
        raise CarteraInvalidaError(f"pesos no numéricos: {no_finitos}")
    cortos = {a: p for a, p in normalizados.items() if p < 0.0}
    if cortos:
        raise CarteraInvalidaError(
            f"pesos negativos (posiciones cortas, no soportadas): {cortos}"
        )
    suma = sum(normalizados.values())
    if abs(suma - 1.0) > TOLERANCIA_NUMERICA:
        raise CarteraInvalidaError(
            f"los pesos suman {suma:.6f} y deben sumar 1 (son fracciones: 0.25 = 25 %). "
            "No se renormalizan: corrige los pesos o di qué hacer con la diferencia"
        )
    return {a: float(normalizados.get(a, 0.0)) for a in activos}


def cartera_del_usuario(
    pesos: Mapping[str, float], estimates: QuantEstimates, optimizacion: OptimizacionConfig
) -> CandidatePortfolio:
    completos = validar_pesos_usuario(pesos, estimates.activos)
    w = np.array([completos[a] for a in estimates.activos], dtype=float)
    mu = retornos_historicos(estimates)
    return CandidatePortfolio(
        nombre=NOMBRE_CANDIDATO,
        tecnica=TecnicaOptimizacion.ACTUAL,
        pesos=completos,
        metricas=metricas_ex_ante(
            w, mu, matriz(estimates, optimizacion.metodo_covarianza), optimizacion.tasa_libre_riesgo
        ),
        retornos_esperados=pesos_a_dict(estimates.activos, mu),
        parametros={"metodo_covarianza": str(optimizacion.metodo_covarianza)},
    )
