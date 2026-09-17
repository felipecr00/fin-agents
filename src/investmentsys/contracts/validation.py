"""``ValidationReport``: veredicto del agente de Riesgo sobre un candidato.

El veredicto lo decide código contra los umbrales de ``config.yaml``; el LLM solo lo
redacta. El validador del contrato impide que ``APROBADA`` conviva con un criterio
incumplido o con look-ahead sin verificar.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field, model_validator

from investmentsys.contracts.common import ContractBase, Fraccion, Ticker, validar_suma


class Veredicto(StrEnum):
    APROBADA = "APROBADA"
    RECHAZADA = "RECHAZADA"


class MetricasOOS(ContractBase):
    """Métricas fuera de muestra del backtest walk-forward, anualizadas."""

    fecha_inicio: date
    fecha_fin: date
    n_periodos: int = Field(ge=1)
    retorno_anualizado: float
    volatilidad_anualizada: float = Field(ge=0.0)
    sharpe_oos: float
    max_drawdown: Fraccion = Field(
        description="Caída máxima como fracción positiva (0.35 = −35 %)."
    )
    turnover_anual: float = Field(ge=0.0)
    costo_transaccion_total: float = Field(
        ge=0.0, description="Costos acumulados como fracción del valor del portafolio."
    )

    @model_validator(mode="after")
    def _fechas(self) -> MetricasOOS:
        if self.fecha_inicio > self.fecha_fin:
            raise ValueError("fecha_inicio posterior a fecha_fin")
        return self


class ResultadoStress(ContractBase):
    escenario: str = Field(min_length=1, description="P. ej. 'covid_2020', 'tasas_2022'.")
    fecha_inicio: date
    fecha_fin: date
    retorno_periodo: float
    max_drawdown: Fraccion
    superado: bool = Field(description="True si el escenario no viola el umbral de drawdown.")

    @model_validator(mode="after")
    def _fechas(self) -> ResultadoStress:
        if self.fecha_inicio > self.fecha_fin:
            raise ValueError(f"{self.escenario}: fecha_inicio posterior a fecha_fin")
        return self


class Criterio(ContractBase):
    """Un umbral de ``config.yaml`` evaluado contra el candidato."""

    nombre: str = Field(
        min_length=1, description="Clave en config.yaml, p. ej. 'sharpe_oos_minimo'."
    )
    valor: float
    umbral: float
    cumple: bool
    detalle: str = ""


class ValidationReport(ContractBase):
    fecha_decision: date
    iteracion: int = Field(ge=1)
    candidato_evaluado: str = Field(min_length=1)
    pesos_evaluados: dict[Ticker, float] = Field(min_length=1)
    metricas_oos: MetricasOOS
    stress: tuple[ResultadoStress, ...] = ()
    criterios: tuple[Criterio, ...] = Field(min_length=1)
    look_ahead_verificado: bool = Field(
        description="True solo si risk/ comprobó que ninguna estimación usó datos futuros."
    )
    veredicto: Veredicto
    sugerencias: tuple[str, ...] = Field(
        default=(), description="Indicaciones al Constructor para la siguiente iteración."
    )

    @model_validator(mode="after")
    def _veredicto_coherente(self) -> ValidationReport:
        validar_suma(self.pesos_evaluados, 1.0, "pesos_evaluados")
        if self.metricas_oos.fecha_fin > self.fecha_decision:
            raise ValueError("look-ahead: el backtest termina después de la fecha de decisión")
        todo_cumple = all(c.cumple for c in self.criterios) and all(s.superado for s in self.stress)
        aprobable = todo_cumple and self.look_ahead_verificado
        if self.veredicto is Veredicto.APROBADA and not aprobable:
            raise ValueError(
                "APROBADA es incompatible con criterios incumplidos, stress no superado o "
                "look-ahead sin verificar"
            )
        if self.veredicto is Veredicto.RECHAZADA and aprobable:
            raise ValueError("RECHAZADA sin ningún criterio incumplido: falta la razón del veto")
        return self

    @property
    def razones_rechazo(self) -> tuple[str, ...]:
        razones = [
            f"{c.nombre}: {c.valor:.4f} vs umbral {c.umbral}"
            for c in self.criterios
            if not c.cumple
        ]
        razones += [
            f"stress {s.escenario}: drawdown {s.max_drawdown:.2%}"
            for s in self.stress
            if not s.superado
        ]
        if not self.look_ahead_verificado:
            razones.append("look-ahead no verificado")
        return tuple(razones)
