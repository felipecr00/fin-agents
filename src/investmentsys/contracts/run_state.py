"""``RunState``: estado serializable de una corrida completa.

Es lo que se persiste en ``runs/<timestamp>/`` y lo que consume el reporter. Es inmutable:
cada etapa produce un nuevo estado con ``avanzar(...)``, que revalida todo el contrato.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator, model_validator

from investmentsys.contracts.common import (
    DISCLAIMER,
    ContractBase,
    Ticker,
    validar_activos_unicos,
)
from investmentsys.contracts.constraints import PortfolioConstraints
from investmentsys.contracts.estimates import QuantEstimates
from investmentsys.contracts.portfolios import CandidatePortfolio, CandidatePortfolios
from investmentsys.contracts.validation import ValidationReport, Veredicto
from investmentsys.contracts.views import MarketViews


class EtapaCorrida(StrEnum):
    INICIADA = "iniciada"
    ANALISIS_Y_ESTIMACION = "analisis_y_estimacion"
    CONSTRUCCION = "construccion"
    VALIDACION = "validacion"
    REPORTE = "reporte"
    COMPLETADA = "completada"
    FALLIDA = "fallida"


class RunState(ContractBase):
    run_id: str = Field(min_length=1)
    creado_en: datetime
    fecha_decision: date
    semilla: int = Field(description="Semilla de config.yaml; misma entrada = misma salida.")
    config_hash: str = Field(
        pattern=r"^[0-9a-f]{64}$", description="SHA-256 del config.yaml usado en la corrida."
    )
    activos: tuple[Ticker, ...] = Field(min_length=1)
    etapa: EtapaCorrida = EtapaCorrida.INICIADA
    restricciones: PortfolioConstraints | None = None
    market_views: MarketViews | None = None
    quant_estimates: QuantEstimates | None = None
    candidatos: tuple[CandidatePortfolios, ...] = Field(
        default=(), description="Una entrada por iteración del bucle Constructor ↔ Validador."
    )
    validaciones: tuple[ValidationReport, ...] = Field(
        default=(), description="Una entrada por iteración; nunca más que candidatos."
    )
    reporte_markdown: str | None = None
    errores: tuple[str, ...] = ()
    disclaimer: str = DISCLAIMER

    @field_validator("activos")
    @classmethod
    def _activos_unicos(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        return validar_activos_unicos(v)

    @field_validator("disclaimer")
    @classmethod
    def _disclaimer_intacto(cls, v: str) -> str:
        if v != DISCLAIMER:
            raise ValueError("el disclaimer no se modifica")
        return v

    @model_validator(mode="after")
    def _coherencia(self) -> RunState:
        for nombre, sub in (
            ("restricciones", self.restricciones),
            ("market_views", self.market_views),
            ("quant_estimates", self.quant_estimates),
            *((f"candidatos[{i}]", c) for i, c in enumerate(self.candidatos)),
        ):
            if sub is not None and sub.activos != self.activos:
                raise ValueError(f"{nombre}: universo distinto al de la corrida")
        for nombre, fecha in (
            *(("market_views", v.fecha_decision) for v in [self.market_views] if v),
            *(("quant_estimates", q.fecha_decision) for q in [self.quant_estimates] if q),
            *((f"candidatos[{i}]", c.fecha_decision) for i, c in enumerate(self.candidatos)),
            *((f"validaciones[{i}]", r.fecha_decision) for i, r in enumerate(self.validaciones)),
        ):
            if fecha != self.fecha_decision:
                raise ValueError(f"{nombre}: fecha de decisión distinta a la de la corrida")
        if len(self.validaciones) > len(self.candidatos):
            raise ValueError("hay más validaciones que rondas de candidatos")
        for i, (c, r) in enumerate(zip(self.candidatos, self.validaciones, strict=False)):
            if c.iteracion != i + 1 or r.iteracion != i + 1:
                raise ValueError(f"iteración {i + 1}: numeración inconsistente")
            if r.candidato_evaluado != c.recomendado:
                raise ValueError(
                    f"iteración {i + 1}: se validó un candidato distinto al recomendado"
                )
        if self.etapa is EtapaCorrida.COMPLETADA:
            if not self.aprobado:
                raise ValueError("COMPLETADA exige una cartera APROBADA por el validador")
            if not self.reporte_markdown or DISCLAIMER not in self.reporte_markdown:
                raise ValueError("COMPLETADA exige un reporte que incluya el disclaimer")
        if self.etapa is EtapaCorrida.FALLIDA and not self.errores:
            raise ValueError("FALLIDA exige al menos un error registrado")
        return self

    @property
    def ultima_validacion(self) -> ValidationReport | None:
        return self.validaciones[-1] if self.validaciones else None

    @property
    def aprobado(self) -> bool:
        ultima = self.ultima_validacion
        return ultima is not None and ultima.veredicto is Veredicto.APROBADA

    @property
    def portafolio_final(self) -> CandidatePortfolio | None:
        """El candidato aprobado en la última iteración, o ``None`` si no lo hay."""
        if not self.aprobado:
            return None
        return self.candidatos[len(self.validaciones) - 1].portafolio_recomendado

    def avanzar(self, **cambios: Any) -> RunState:
        """Nuevo estado con ``cambios`` aplicados y el contrato completo revalidado."""
        return RunState.model_validate({**self.model_dump(), **cambios})
