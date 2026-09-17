"""``CandidatePortfolios``: carteras propuestas por el Constructor al Validador."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from investmentsys.contracts.common import (
    TOLERANCIA_NUMERICA,
    ContractBase,
    Fraccion,
    Ticker,
    validar_activos_unicos,
    validar_mismo_universo,
    validar_suma,
)
from investmentsys.contracts.constraints import PortfolioConstraints


class TecnicaOptimizacion(StrEnum):
    BLACK_LITTERMAN = "black_litterman"
    HRP = "hrp"
    MIN_VARIANZA = "min_varianza"
    EQUIPONDERADO = "equiponderado"
    ACTUAL = "actual"


class MetricasExAnte(ContractBase):
    """Métricas esperadas (ex ante) del candidato, anualizadas."""

    retorno_esperado_anual: float
    volatilidad_anual: float = Field(ge=0.0)
    sharpe: float
    concentracion_hhi: Fraccion = Field(
        description="Índice Herfindahl de los pesos: 1/n equiponderado, 1 un solo activo."
    )


class Sensibilidad(ContractBase):
    """Cómo cambian los pesos al perturbar un parámetro o input."""

    parametro: str = Field(min_length=1, description="P. ej. 'tau', 'delta', 'view[1].q_anual'.")
    perturbacion: float = Field(description="Magnitud aplicada (misma unidad que el parámetro).")
    pesos_perturbados: dict[Ticker, float]
    cambio_max_pp: float = Field(
        ge=0.0, description="Mayor cambio absoluto de un peso, en puntos porcentuales."
    )


class CandidatePortfolio(ContractBase):
    nombre: str = Field(min_length=1)
    tecnica: TecnicaOptimizacion
    pesos: dict[Ticker, float] = Field(min_length=1, description="Fracciones; suman 1.")
    metricas: MetricasExAnte
    sensibilidad: tuple[Sensibilidad, ...] = ()
    retornos_esperados: dict[Ticker, float] | None = Field(
        default=None, description="Retornos usados por el optimizador (p. ej. μ posterior BL)."
    )
    parametros: dict[str, float | int | str | bool] = Field(
        default_factory=dict, description="Parámetros efectivos (delta, tau, método Ω…)."
    )

    @model_validator(mode="after")
    def _coherencia(self) -> CandidatePortfolio:
        validar_suma(self.pesos, 1.0, f"{self.nombre}: pesos")
        if self.retornos_esperados is not None:
            validar_mismo_universo(self.retornos_esperados, self.pesos, "retornos_esperados")
        for s in self.sensibilidad:
            validar_mismo_universo(s.pesos_perturbados, self.pesos, f"sensibilidad {s.parametro}")
        return self

    def pesos_ordenados(self, activos: tuple[str, ...]) -> list[float]:
        return [self.pesos[a] for a in activos]

    def violaciones(self, restricciones: PortfolioConstraints) -> list[str]:
        """Lista de límites incumplidos (vacía si el candidato es admisible)."""
        problemas: list[str] = []
        for activo, peso in self.pesos.items():
            lo, hi = restricciones.limites(activo)
            if peso < lo - TOLERANCIA_NUMERICA or peso > hi + TOLERANCIA_NUMERICA:
                problemas.append(f"{activo}={peso:.4f} fuera de [{lo}, {hi}]")
        if abs(sum(self.pesos.values()) - restricciones.suma_pesos) > TOLERANCIA_NUMERICA:
            problemas.append(f"suma de pesos distinta de {restricciones.suma_pesos}")
        return problemas


class CandidatePortfolios(ContractBase):
    """Salida del Constructor en una iteración; entrada del Validador."""

    fecha_decision: date
    activos: tuple[Ticker, ...] = Field(min_length=1)
    iteracion: int = Field(ge=1, description="Ronda del bucle Constructor ↔ Validador.")
    candidatos: tuple[CandidatePortfolio, ...] = Field(min_length=1)
    recomendado: str = Field(description="Nombre del candidato que se somete a validación.")

    @field_validator("activos")
    @classmethod
    def _activos_unicos(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        return validar_activos_unicos(v)

    @model_validator(mode="after")
    def _coherencia(self) -> CandidatePortfolios:
        nombres = [c.nombre for c in self.candidatos]
        if len(set(nombres)) != len(nombres):
            raise ValueError("nombres de candidatos repetidos")
        if self.recomendado not in nombres:
            raise ValueError(f"recomendado '{self.recomendado}' no está entre {nombres}")
        for c in self.candidatos:
            validar_mismo_universo(c.pesos, self.activos, f"candidato {c.nombre}")
        return self

    def candidato(self, nombre: str) -> CandidatePortfolio:
        for c in self.candidatos:
            if c.nombre == nombre:
                return c
        raise KeyError(nombre)

    @property
    def portafolio_recomendado(self) -> CandidatePortfolio:
        return self.candidato(self.recomendado)
