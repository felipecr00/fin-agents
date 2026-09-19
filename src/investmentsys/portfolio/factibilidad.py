"""Restricciones de una iteración a partir de las de la sesión. Código puro (S7 §3).

Cinco chequeos, cada uno con un mensaje que dice qué corregir:

1. piso × N ≤ 100 % y 2. los techos alcanzan el 100 % — también tras aplicar los overrides;
3. un override solo ENDURECE respecto a ``SessionConstraints`` (nunca sube un máximo);
4. los tickers del override pertenecen al universo;
5. un override nunca baja del piso del activo.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import ValidationError

from investmentsys.config import OptimizacionConfig
from investmentsys.contracts import (
    LimiteActivo,
    LimiteGlobal,
    OrigenRestriccion,
    PortfolioConstraints,
    SessionConstraints,
    Universe,
)
from investmentsys.contracts.common import TOLERANCIA_NUMERICA


class RestriccionesInfactiblesError(ValueError):
    """Las restricciones pedidas no admiten ninguna cartera, o relajan las de la sesión."""


def sesion_por_defecto(universo: Universe, optimizacion: OptimizacionConfig) -> SessionConstraints:
    """Restricciones de ``config.yaml`` sobre ``universo``; infactibles = error de validación."""
    if optimizacion.permitir_cortos:
        raise RestriccionesInfactiblesError("SessionConstraints no modela cortos (ADR-012)")
    origen = OrigenRestriccion.DEFAULT_CONFIG
    return SessionConstraints(
        universe_version=universo.version,
        activos=universo.activos,
        peso_min=LimiteGlobal(valor=optimizacion.peso_min, origen=origen),
        peso_max=LimiteGlobal(valor=optimizacion.peso_max, origen=origen),
    )


def sesion_ajustada(
    vigente: SessionConstraints,
    peso_min: float | None = None,
    peso_max: float | None = None,
    limites_por_activo: Mapping[str, tuple[float, float]] | None = None,
) -> SessionConstraints:
    """``vigente`` con los ajustes del usuario (origen ``ajuste_usuario``); lo demás no cambia.

    La factibilidad la decide el contrato ``SessionConstraints`` (piso×N ≤ 100 %, los techos
    alcanzan el 100 %, tickers del universo): aquí solo se le da un mensaje sin ruido de pydantic.
    """
    usuario = OrigenRestriccion.AJUSTE_USUARIO
    propios = dict(vigente.limites_por_activo)
    for activo, (minimo, maximo) in (limites_por_activo or {}).items():
        propios[activo] = LimiteActivo.model_construct(minimo=minimo, maximo=maximo, origen=usuario)
    try:
        return SessionConstraints.model_validate(
            {
                "universe_version": vigente.universe_version,
                "activos": vigente.activos,
                "peso_min": vigente.peso_min
                if peso_min is None
                else {"valor": peso_min, "origen": usuario},
                "peso_max": vigente.peso_max
                if peso_max is None
                else {"valor": peso_max, "origen": usuario},
                "limites_por_activo": {a: dict(limite) for a, limite in propios.items()},
            }
        )
    except ValidationError as exc:
        motivos = "; ".join(str(e["msg"]).removeprefix("Value error, ") for e in exc.errors())
        raise RestriccionesInfactiblesError(
            f"restricciones rechazadas: {motivos}. Las vigentes no cambian"
        ) from exc


def restricciones_de_iteracion(
    sesion: SessionConstraints, peso_max_por_activo: Mapping[str, float]
) -> PortfolioConstraints:
    """``sesion`` con los máximos de ``peso_max_por_activo`` endurecidos, lista para optimizar."""
    fuera = sorted(set(peso_max_por_activo) - set(sesion.activos))
    if fuera:
        raise RestriccionesInfactiblesError(
            f"peso_max_por_activo: tickers fuera del universo {list(sesion.activos)}: {fuera}"
        )
    limites = {a: sesion.limites(a) for a in sesion.limites_por_activo}
    for activo, maximo in peso_max_por_activo.items():
        piso, techo = sesion.limites(activo)
        if maximo > techo + TOLERANCIA_NUMERICA:
            raise RestriccionesInfactiblesError(
                f"{activo}: un override solo puede ENDURECER; pides máximo {maximo:.2%} y el "
                f"vigente en la sesión es {techo:.2%}"
            )
        if maximo < piso - TOLERANCIA_NUMERICA:
            raise RestriccionesInfactiblesError(
                f"{activo}: máximo {maximo:.2%} por debajo de su piso {piso:.2%}; el mínimo "
                "admisible para este override es el piso"
            )
        limites[activo] = (piso, maximo)

    efectivos = {a: limites.get(a, sesion.limites(a)) for a in sesion.activos}
    suma_pisos = sum(lo for lo, _ in efectivos.values())
    suma_techos = sum(hi for _, hi in efectivos.values())
    n = len(sesion.activos)
    if suma_pisos > 1.0 + TOLERANCIA_NUMERICA:
        raise RestriccionesInfactiblesError(
            f"infactible: los pisos suman {suma_pisos:.2%} > 100 % con {n} activos"
        )
    if suma_techos < 1.0 - TOLERANCIA_NUMERICA:
        raise RestriccionesInfactiblesError(
            f"infactible: con esos máximos los techos suman {suma_techos:.2%} < 100 % "
            f"({n} activos): no existe cartera totalmente invertida; endurece menos"
        )
    return PortfolioConstraints(
        activos=sesion.activos,
        peso_min=sesion.peso_min.valor,
        peso_max=sesion.peso_max.valor,
        limites_por_activo=limites,
    )
