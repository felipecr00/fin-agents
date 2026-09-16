"""Tipos y utilidades compartidas por todos los contratos.

Los contratos son la columna vertebral del sistema: toda comunicación entre
agentes pasa por estos esquemas. Cambiar un contrato exige ADR + actualizar
todos los consumidores + tests (ver CLAUDE.md).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

DISCLAIMER = (
    "Herramienta de análisis. Ninguna salida constituye asesoría financiera; "
    "los resultados dependen de supuestos y datos históricos que pueden no repetirse."
)

# Tolerancia técnica de punto flotante para comprobaciones de suma (pesos, filas de P).
# No es un parámetro financiero: no vive en config.yaml a propósito.
TOLERANCIA_NUMERICA = 1e-6

Ticker = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[A-Z][A-Z0-9.\-]{0,9}$"),
]
"""Símbolo de un activo, p. ej. ``VOOG``, ``BRK.B``."""

Fraccion = Annotated[float, Field(ge=0.0, le=1.0)]
"""Proporción en [0, 1]. Los pesos y drawdowns se expresan así, nunca en porcentaje."""


class ContractBase(BaseModel):
    """Base de todos los contratos.

    - ``extra="forbid"``: un campo desconocido es un error, no se ignora en silencio.
    - ``frozen=True``: los contratos son inmutables una vez validados (reproducibilidad).
    - ``allow_inf_nan=False``: ningún NaN/inf atraviesa una frontera entre agentes.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        validate_default=True,
        str_strip_whitespace=True,
    )


def validar_activos_unicos(activos: Iterable[str]) -> tuple[str, ...]:
    """Devuelve la tupla si no hay duplicados; si los hay, lanza ``ValueError``."""
    activos = tuple(activos)
    duplicados = sorted({a for a in activos if activos.count(a) > 1})
    if duplicados:
        raise ValueError(f"activos duplicados: {duplicados}")
    return activos


def validar_mismo_universo(observados: Iterable[str], esperados: Iterable[str], que: str) -> None:
    """Verifica que ``observados`` sea exactamente el mismo conjunto que ``esperados``."""
    obs, esp = set(observados), set(esperados)
    if obs != esp:
        faltan, sobran = sorted(esp - obs), sorted(obs - esp)
        raise ValueError(f"{que}: no coincide con el universo (faltan={faltan}, sobran={sobran})")


def validar_suma(valores: Mapping[str, float], esperado: float, que: str) -> None:
    """Verifica que la suma de ``valores`` sea ``esperado`` dentro de la tolerancia técnica."""
    suma = sum(valores.values())
    if abs(suma - esperado) > TOLERANCIA_NUMERICA:
        raise ValueError(f"{que}: suman {suma:.8f}, se esperaba {esperado}")
