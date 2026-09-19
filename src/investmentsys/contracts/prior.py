"""``PriorSnapshot``: el prior de equilibrio de Black-Litterman tal como se usó (ADR-013).

Es la fotografía auditable que ``RunState`` guarda y el reporte muestra SIEMPRE: el vector
w_mkt, la procedencia de cada peso y la tabla de retornos implícitos π = δ·Σ·w_mkt. El
contrato impone la coherencia todo-o-nada: o todas las procedencias pertenecen a
{fuente, usuario}, o todas son neutral — nunca mezcla.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field, model_validator

from investmentsys.contracts.common import (
    TOLERANCIA_NUMERICA,
    ContractBase,
    Ticker,
    validar_activos_unicos,
)
from investmentsys.contracts.estimates import MetodoCovarianza
from investmentsys.contracts.universe import PriorProvenance, UniverseVersion

ADVERTENCIA_PRIOR_NEUTRAL = (
    "prior neutral: la asignación BL refleja tus views contra un punto de partida "
    "equiponderado, no contra el consenso de mercado"
)
ADVERTENCIA_PRIOR_SOLO_VIEWS = (
    "prior solo-views (π = 0): la asignación BL refleja únicamente tus views, sin punto de "
    "partida de mercado"
)


class MetodoPrior(StrEnum):
    CAPITALIZACION = "capitalizacion"
    NEUTRAL = "neutral"  # equal-weight sobre el universo completo
    SOLO_VIEWS = "solo_views"  # π = 0; disponible por config, no es la política activa


class PriorActivo(ContractBase):
    """Una fila de la tabla π: el peso de mercado de un activo, su origen y su retorno implícito."""

    activo: Ticker
    procedencia: PriorProvenance
    cap: float | None = Field(default=None, gt=0.0, description="US$ billones (10^12).")
    fuente_detalle: str | None = None
    as_of: date | None = None
    peso_mercado: float | None = Field(default=None, ge=0.0, le=1.0)
    pi_exceso: float = Field(description="Retorno implícito en exceso de la tasa libre de riesgo.")
    pi_total: float = Field(description="pi_exceso + tasa libre de riesgo.")


class PriorSnapshot(ContractBase):
    universe_version: UniverseVersion
    metodo: MetodoPrior
    delta: float = Field(gt=0.0)
    tasa_libre_riesgo: float
    metodo_covarianza: MetodoCovarianza
    activos: tuple[PriorActivo, ...] = Field(min_length=1, description="En el orden canónico.")
    advertencia: str | None = Field(
        default=None, description="Texto estándar obligatorio cuando el prior no es de mercado."
    )

    @model_validator(mode="after")
    def _coherencia(self) -> PriorSnapshot:
        validar_activos_unicos(a.activo for a in self.activos)
        self._todo_o_nada()
        for a in self.activos:
            if abs(a.pi_total - (a.pi_exceso + self.tasa_libre_riesgo)) > TOLERANCIA_NUMERICA:
                raise ValueError(f"{a.activo}: pi_total distinto de pi_exceso + rf")
        if self.metodo is MetodoPrior.CAPITALIZACION:
            self._pesos_proporcionales_a_caps()
        else:
            self._sin_caps()
        return self

    def _todo_o_nada(self) -> None:
        procedencias = {a.procedencia for a in self.activos}
        de_mercado = procedencias <= {PriorProvenance.FUENTE, PriorProvenance.USUARIO}
        todo_neutral = procedencias == {PriorProvenance.NEUTRAL}
        if not (de_mercado or todo_neutral):
            raise ValueError(
                "prior incoherente: mezcla de procedencias de mercado y neutral "
                f"({ {a.activo: a.procedencia.value for a in self.activos} }); o todas "
                "pertenecen a {fuente, usuario} o todas son neutral"
            )
        if de_mercado is not (self.metodo is MetodoPrior.CAPITALIZACION):
            raise ValueError(f"metodo={self.metodo.value} incompatible con las procedencias")

    def _pesos_proporcionales_a_caps(self) -> None:
        incompletos = [
            a.activo
            for a in self.activos
            if a.cap is None or a.fuente_detalle is None or a.as_of is None
        ]
        if incompletos:
            raise ValueError(f"caps sin valor, detalle o fecha as-of: {incompletos}")
        if self.advertencia is not None:
            raise ValueError("un prior por capitalización no lleva advertencia de degradación")
        total = sum(a.cap or 0.0 for a in self.activos)
        for a in self.activos:
            esperado = (a.cap or 0.0) / total
            if a.peso_mercado is None or abs(a.peso_mercado - esperado) > TOLERANCIA_NUMERICA:
                raise ValueError(f"{a.activo}: peso_mercado no es cap/Σcap ({esperado:.6f})")

    def _sin_caps(self) -> None:
        con_cap = [a.activo for a in self.activos if a.cap is not None]
        if con_cap:
            raise ValueError(
                f"prior {self.metodo.value}: las caps no participan y no se registran: {con_cap} "
                "(siguen congeladas en el Universe)"
            )
        if self.metodo is MetodoPrior.NEUTRAL:
            esperado, advertencia = 1.0 / len(self.activos), ADVERTENCIA_PRIOR_NEUTRAL
            malos = [
                a.activo
                for a in self.activos
                if a.peso_mercado is None or abs(a.peso_mercado - esperado) > TOLERANCIA_NUMERICA
            ]
            if malos:
                raise ValueError(f"prior neutral: peso_mercado debe ser 1/N para todos: {malos}")
        else:
            advertencia = ADVERTENCIA_PRIOR_SOLO_VIEWS
            malos = [
                a.activo
                for a in self.activos
                if a.peso_mercado is not None or abs(a.pi_exceso) > TOLERANCIA_NUMERICA
            ]
            if malos:
                raise ValueError(f"prior solo-views: sin w_mkt y con π = 0 para todos: {malos}")
        if self.advertencia != advertencia:
            raise ValueError(f"prior {self.metodo.value}: falta la advertencia estándar")

    @property
    def tickers(self) -> tuple[str, ...]:
        return tuple(a.activo for a in self.activos)

    @property
    def procedencias(self) -> dict[str, PriorProvenance]:
        return {a.activo: a.procedencia for a in self.activos}

    @property
    def pesos_mercado(self) -> dict[str, float] | None:
        """w_mkt por activo; ``None`` con prior solo-views (no hay cartera de mercado)."""
        if self.metodo is MetodoPrior.SOLO_VIEWS:
            return None
        return {a.activo: a.peso_mercado or 0.0 for a in self.activos}
