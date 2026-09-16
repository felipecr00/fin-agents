"""``PortfolioConstraints``: restricciones que todo candidato debe respetar."""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from investmentsys.contracts.common import (
    TOLERANCIA_NUMERICA,
    ContractBase,
    Ticker,
    validar_activos_unicos,
)


class PortfolioConstraints(ContractBase):
    activos: tuple[Ticker, ...] = Field(min_length=1)
    peso_min: float = Field(description="Límite inferior por activo (fracción).")
    peso_max: float = Field(le=1.0, description="Límite superior por activo (fracción).")
    permitir_cortos: bool = False
    limites_por_activo: dict[Ticker, tuple[float, float]] = Field(
        default_factory=dict, description="Excepciones (min, max) por activo."
    )
    suma_pesos: float = Field(default=1.0, description="1.0 = totalmente invertido.")
    turnover_maximo: float | None = Field(
        default=None, ge=0.0, description="Rotación máxima admisible frente al portafolio actual."
    )

    @field_validator("activos")
    @classmethod
    def _activos_unicos(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        return validar_activos_unicos(v)

    @model_validator(mode="after")
    def _factibilidad(self) -> PortfolioConstraints:
        if self.peso_min > self.peso_max:
            raise ValueError("peso_min mayor que peso_max")
        if not self.permitir_cortos and self.peso_min < 0.0:
            raise ValueError("peso_min negativo requiere permitir_cortos=True")
        fuera = sorted(set(self.limites_por_activo) - set(self.activos))
        if fuera:
            raise ValueError(f"limites_por_activo: activos fuera del universo: {fuera}")
        for activo, (lo, hi) in self.limites_por_activo.items():
            if lo > hi:
                raise ValueError(f"{activo}: límite inferior mayor que el superior")
            if not self.permitir_cortos and lo < 0.0:
                raise ValueError(f"{activo}: límite negativo requiere permitir_cortos=True")
        suma_min = sum(self.limites(a)[0] for a in self.activos)
        suma_max = sum(self.limites(a)[1] for a in self.activos)
        if not suma_min - TOLERANCIA_NUMERICA <= self.suma_pesos <= suma_max + TOLERANCIA_NUMERICA:
            raise ValueError(
                f"infactible: los límites permiten sumas en [{suma_min:.4f}, {suma_max:.4f}] "
                f"pero se exige {self.suma_pesos}"
            )
        return self

    def limites(self, activo: str) -> tuple[float, float]:
        """(mínimo, máximo) efectivos para ``activo``."""
        return self.limites_por_activo.get(activo, (self.peso_min, self.peso_max))

    def limites_ordenados(self) -> list[tuple[float, float]]:
        """Límites en el orden canónico, listos para un optimizador."""
        return [self.limites(a) for a in self.activos]
