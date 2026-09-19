"""``DiagnosticoCartera``: evaluación EXPLORATORIA de una cartera que trae el usuario (S8).

Es lo que mide el Escéptico fuera del comité. Deliberadamente NO tiene veredicto y NO es un
``ValidationReport``: un ``RunState`` no lo admite, así que un acta nunca puede confundir una
evaluación exploratoria con un veto (ADR-014). ``validado`` es ``False`` en el dato, no solo
en el texto que redacte un agente.
"""

from __future__ import annotations

from datetime import date
from typing import Final, Literal

from pydantic import Field, model_validator

from investmentsys.contracts.common import ContractBase, Ticker, validar_suma
from investmentsys.contracts.portfolios import MetricasExAnte
from investmentsys.contracts.universe import UniverseVersion
from investmentsys.contracts.validation import (
    Criterio,
    MetricasOOS,
    ResultadoStress,
    ValidationReport,
)

ETIQUETA_DIAGNOSTICO: Final = "diagnostico"


class DiagnosticoCartera(ContractBase):
    etiqueta: Literal["diagnostico"] = ETIQUETA_DIAGNOSTICO
    validado: Literal[False] = Field(
        default=False, description="Exploratorio: no pasó por el comité. Nunca es True."
    )
    universe_version: UniverseVersion = Field(
        description="Sello del Universe sobre el que se midió (ADR-012); obligatorio."
    )
    fecha_decision: date
    pesos_evaluados: dict[Ticker, float] = Field(min_length=1)
    metricas_ex_ante: MetricasExAnte
    metricas_oos: MetricasOOS
    stress: tuple[ResultadoStress, ...] = ()
    criterios_de_referencia: tuple[Criterio, ...] = Field(
        min_length=1,
        description=(
            "Los umbrales del comité medidos sobre esta cartera, como referencia: cumplirlos "
            "o no aquí no aprueba ni rechaza nada."
        ),
    )
    look_ahead_verificado: bool
    advertencias: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _coherencia(self) -> DiagnosticoCartera:
        validar_suma(self.pesos_evaluados, 1.0, "pesos_evaluados")
        if self.metricas_oos.fecha_fin > self.fecha_decision:
            raise ValueError("look-ahead: el backtest termina después de la fecha de decisión")
        return self

    @classmethod
    def desde_reporte(
        cls, reporte: ValidationReport, metricas_ex_ante: MetricasExAnte
    ) -> DiagnosticoCartera:
        """Las mediciones del validador SIN su veredicto ni sus sugerencias al Constructor."""
        if reporte.universe_version is None:
            raise ValueError("diagnóstico sin sellar: mídelo sobre el universo vigente")
        return cls(
            universe_version=reporte.universe_version,
            fecha_decision=reporte.fecha_decision,
            pesos_evaluados=dict(reporte.pesos_evaluados),
            metricas_ex_ante=metricas_ex_ante,
            metricas_oos=reporte.metricas_oos,
            stress=reporte.stress,
            criterios_de_referencia=reporte.criterios,
            look_ahead_verificado=reporte.look_ahead_verificado,
            advertencias=reporte.advertencias,
        )
