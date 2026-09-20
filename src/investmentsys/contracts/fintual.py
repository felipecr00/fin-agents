"""``PlanInercia``: bandas de inercia (No-Trade Zones) sobre una cartera objetivo (S10, ADR-020).

Lo produce ``fintual/no_trade_zones.py`` (Nivel 3, puro). Dentro de la banda la orden de un
activo es ``HOLD`` y el contrato lo exige: un plan que llame ``FUERA_DE_BANDA`` a una desviación
que cabe en la banda (o al revés) no valida. S10 solo SEÑALA lo que está fuera de banda; cuánto
comprar con aportes es de S11, que consumirá este contrato.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import Field, model_validator

from investmentsys.contracts.common import (
    TOLERANCIA_NUMERICA,
    ContractBase,
    Fraccion,
    Ticker,
    validar_activos_unicos,
)
from investmentsys.contracts.universe import UniverseVersion

DISCLAIMER_OPERATIVO: Final = (
    "Esta es una estimación algorítmica, no asesoría tributaria o financiera. Valida el "
    "tratamiento de dividendos extranjeros con tu contador."
)


class OrdenInercia(StrEnum):
    HOLD = "HOLD"
    FUERA_DE_BANDA = "FUERA_DE_BANDA"


class DecisionInercia(ContractBase):
    activo: Ticker
    peso_objetivo: Fraccion
    peso_actual: Fraccion
    desviacion: float = Field(
        description="peso_actual − peso_objetivo, en fracción (0.05 = 5 p.p.)."
    )
    banda: float = Field(gt=0.0, le=1.0, description="Semiancho absoluto de la banda de inercia.")
    orden: OrdenInercia
    monto_objetivo_usd: float = Field(ge=0.0, description="Peso objetivo en US$, 2 decimales.")
    monto_actual_usd: float = Field(ge=0.0, description="Peso actual en US$, 2 decimales.")

    @model_validator(mode="after")
    def _coherencia(self) -> DecisionInercia:
        if abs(self.desviacion - (self.peso_actual - self.peso_objetivo)) > TOLERANCIA_NUMERICA:
            raise ValueError(f"{self.activo}: desviacion no es peso_actual − peso_objetivo")
        dentro = abs(self.desviacion) <= self.banda + TOLERANCIA_NUMERICA
        if dentro != (self.orden is OrdenInercia.HOLD):
            raise ValueError(
                f"{self.activo}: orden {self.orden.value} incoherente con una desviación de "
                f"{self.desviacion:+.4f} y una banda de ±{self.banda:.4f}"
            )
        return self


class PlanInercia(ContractBase):
    universe_version: UniverseVersion = Field(
        description="Sello del Universe de la cartera objetivo (ADR-012); obligatorio."
    )
    validado: bool = Field(description="El de la cartera objetivo: solo el comité da True.")
    origen_objetivo: str = Field(min_length=1, description="De dónde sale la cartera objetivo.")
    valor_cartera_usd: float = Field(gt=0.0)
    decisiones: tuple[DecisionInercia, ...] = Field(min_length=1)
    orden_global: OrdenInercia
    disclaimer: str = DISCLAIMER_OPERATIVO

    @model_validator(mode="after")
    def _coherencia(self) -> PlanInercia:
        validar_activos_unicos(d.activo for d in self.decisiones)
        todo_hold = all(d.orden is OrdenInercia.HOLD for d in self.decisiones)
        if todo_hold != (self.orden_global is OrdenInercia.HOLD):
            raise ValueError("orden_global: es HOLD si y solo si todos los activos están en banda")
        for nombre in ("monto_objetivo_usd", "monto_actual_usd"):
            total = sum(getattr(d, nombre) for d in self.decisiones)
            if abs(total - self.valor_cartera_usd) > TOLERANCIA_NUMERICA:
                raise ValueError(f"{nombre}: suman {total:.2f}, no {self.valor_cartera_usd:.2f}")
        return self
