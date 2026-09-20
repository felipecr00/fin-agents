"""Claves del estado de sesión de ADK y (de)serialización de contratos.

El estado de sesión solo guarda JSON: cada contrato entra con ``model_dump(mode="json")`` y
sale revalidado con ``model_validate``. Así los contratos grandes (covarianzas, candidatos)
viajan por el estado y nunca por los argumentos que escribe un LLM.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

CLAVE_FECHA_DECISION = "fecha_decision"
CLAVE_MARKET_VIEWS = "market_views"
CLAVE_QUANT_ESTIMATES = "quant_estimates"
CLAVE_RESTRICCIONES = "restricciones"
CLAVE_CANDIDATOS = "candidatos"
CLAVE_VALIDACIONES = "validaciones"
CLAVE_UNIVERSO = "universo"
CLAVE_RESTRICCIONES_SESION = "restricciones_sesion"
CLAVE_PRIOR = "prior"
CLAVE_RUN_STATE = "run_state_json"  # ADR-009: el RunState final viaja también en la sesión
# Exploratorio (S8): fuera de todo lo que lee RunState; nunca es una validación del comité.
CLAVE_DIAGNOSTICOS_CARTERA = "diagnosticos_cartera"
CLAVE_SOLICITUD_NEUTRAL = "solicitud_prior_neutral"  # custodia por turnos (ADR-015 §A)
CLAVE_SOLICITUD_COMITE = "solicitud_comite"  # gate del comité (ADR-014): resumen + token
# S10 (ADR-019): pesos que el usuario le dio al Director para el Escéptico; los pone un callback
# del Director y los lee la tool de la persona, sin pasar por el LLM de la persona.
CLAVE_PESOS_EN_CONSULTA = "pesos_en_consulta"

M = TypeVar("M", bound=BaseModel)


class EstadoLegible(Protocol):
    """Lectura: ``dict``, ``State`` de ADK o el ``MappingProxyType`` de un contexto de lectura."""

    def get(self, key: str, default: Any = None, /) -> Any: ...


class Estado(EstadoLegible, Protocol):
    """Lo mínimo que comparten ``dict`` y ``google.adk.sessions.State``."""

    def __setitem__(self, key: str, value: Any) -> None: ...


class ResultadoObsoletoError(ValueError):
    """Un resultado se calculó sobre otra versión del universo (o sin universo): no vale."""


def exigir_sello(sello: str | None, version: str, que: str) -> None:
    """Regla de obsolescencia como invariante mecánico (ADR-012)."""
    if sello is None:
        raise ResultadoObsoletoError(f"{que}: sin sellar; recalcúlalo sobre el universo vigente")
    if sello != version:
        raise ResultadoObsoletoError(
            f"{que}: obsoleto. Se calculó sobre el universo {sello[:12]}… y el vigente es "
            f"{version[:12]}… (cambió el universo, una cap o los datos): recalcúlalo"
        )


class FaltaEnEstadoError(LookupError):
    """Un tool necesita una clave que ninguna etapa anterior escribió."""


def leer(estado: EstadoLegible, clave: str, modelo: type[M]) -> M:
    crudo = estado.get(clave)
    if crudo is None:
        raise FaltaEnEstadoError(f"falta '{clave}' en el estado: ejecuta antes la etapa previa")
    return modelo.model_validate(crudo)


def leer_lista(estado: EstadoLegible, clave: str, modelo: type[M]) -> tuple[M, ...]:
    return tuple(modelo.model_validate(c) for c in estado.get(clave) or ())


def leer_fecha(estado: EstadoLegible) -> date | None:
    crudo = estado.get(CLAVE_FECHA_DECISION)
    return date.fromisoformat(crudo) if crudo else None


def volcar(modelo: BaseModel) -> dict[str, Any]:
    return modelo.model_dump(mode="json")


def agregar(estado: Estado, clave: str, modelo: BaseModel) -> None:
    """Añade ``modelo`` a la lista de ``clave`` reasignándola (el delta de ADK es por clave)."""
    estado[clave] = [*(estado.get(clave) or ()), volcar(modelo)]
