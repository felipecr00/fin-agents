"""``SessionConstraints``: restricciones vigentes en la sesión, con el origen de cada una.

Es la referencia contra la que el Constructor endurece: un override de una iteración solo
puede ser MÁS estricto que esto (S7 §3). Los dos chequeos de factibilidad que dependen solo
de la sesión (piso×N ≤ 100 %, los techos alcanzan el 100 %) viven aquí, con mensajes que
dicen qué corregir; los que dependen del override viven en la herramienta.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from investmentsys.contracts.common import (
    TOLERANCIA_NUMERICA,
    ContractBase,
    Fraccion,
    Ticker,
    validar_activos_unicos,
)
from investmentsys.contracts.constraints import PortfolioConstraints
from investmentsys.contracts.universe import UniverseVersion


class OrigenRestriccion(StrEnum):
    DEFAULT_CONFIG = "default_config"
    AJUSTE_USUARIO = "ajuste_usuario"


class LimiteGlobal(ContractBase):
    valor: Fraccion
    origen: OrigenRestriccion


class LimiteActivo(ContractBase):
    """Excepción (mínimo, máximo) para un activo; siempre la pone el usuario o una sesión."""

    minimo: Fraccion
    maximo: Fraccion
    origen: OrigenRestriccion

    @model_validator(mode="after")
    def _ordenado(self) -> LimiteActivo:
        if self.minimo > self.maximo:
            raise ValueError("límite inferior mayor que el superior")
        return self


class SessionConstraints(ContractBase):
    universe_version: UniverseVersion
    activos: tuple[Ticker, ...] = Field(min_length=1)
    peso_min: LimiteGlobal
    peso_max: LimiteGlobal
    limites_por_activo: dict[Ticker, LimiteActivo] = Field(default_factory=dict)

    @field_validator("activos")
    @classmethod
    def _activos_unicos(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        return validar_activos_unicos(v)

    @model_validator(mode="after")
    def _factibilidad(self) -> SessionConstraints:
        n = len(self.activos)
        if self.peso_min.valor > self.peso_max.valor:
            raise ValueError("peso_min mayor que peso_max")
        fuera = sorted(set(self.limites_por_activo) - set(self.activos))
        if fuera:
            raise ValueError(f"limites_por_activo: tickers fuera del universo: {fuera}")
        suma_pisos = sum(self.limites(a)[0] for a in self.activos)
        suma_techos = sum(self.limites(a)[1] for a in self.activos)
        if suma_pisos > 1.0 + TOLERANCIA_NUMERICA:
            raise ValueError(
                f"infactible: los pisos suman {suma_pisos:.2%} > 100 % con {n} activos "
                f"(piso general {self.peso_min.valor:.2%}): baja el piso o quita activos"
            )
        if suma_techos < 1.0 - TOLERANCIA_NUMERICA:
            raise ValueError(
                f"infactible: los techos suman {suma_techos:.2%} < 100 % con {n} activos "
                f"(techo general {self.peso_max.valor:.2%}): sube el techo o añade activos"
            )
        return self

    def limites(self, activo: str) -> tuple[float, float]:
        """(mínimo, máximo) vigentes para ``activo``."""
        propio = self.limites_por_activo.get(activo)
        if propio is not None:
            return propio.minimo, propio.maximo
        return self.peso_min.valor, self.peso_max.valor

    def a_portfolio_constraints(self) -> PortfolioConstraints:
        """Las restricciones de sesión, sin overrides, en el formato del optimizador."""
        return PortfolioConstraints(
            activos=self.activos,
            peso_min=self.peso_min.valor,
            peso_max=self.peso_max.valor,
            limites_por_activo={a: self.limites(a) for a in self.limites_por_activo},
        )
