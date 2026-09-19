"""Construcción de portafolios (Black-Litterman, HRP, mínima varianza). Sin ADK ni LLM."""

from investmentsys.portfolio._comun import OptimizacionFallidaError
from investmentsys.portfolio.black_litterman import optimizar_black_litterman
from investmentsys.portfolio.cartera_usuario import (
    CarteraInvalidaError,
    cartera_del_usuario,
    validar_pesos_usuario,
)
from investmentsys.portfolio.factibilidad import (
    RestriccionesInfactiblesError,
    restricciones_de_iteracion,
    sesion_ajustada,
    sesion_por_defecto,
)
from investmentsys.portfolio.hrp import optimizar_hrp, pesos_hrp
from investmentsys.portfolio.min_varianza import optimizar_min_varianza
from investmentsys.portfolio.prior import (
    PriorNoDisponibleError,
    mensaje_estado_prior,
    resolver_prior,
)

__all__ = [
    "CarteraInvalidaError",
    "OptimizacionFallidaError",
    "PriorNoDisponibleError",
    "RestriccionesInfactiblesError",
    "cartera_del_usuario",
    "mensaje_estado_prior",
    "optimizar_black_litterman",
    "optimizar_hrp",
    "optimizar_min_varianza",
    "pesos_hrp",
    "resolver_prior",
    "restricciones_de_iteracion",
    "sesion_ajustada",
    "sesion_por_defecto",
    "validar_pesos_usuario",
]
