"""Hitos del comité formal (S11): lo que el pipeline cuenta de sí mismo MIENTRAS delibera.

Un ``HitoComite`` es una línea de la bitácora: quién (``fase``), en qué ronda (``iteracion``),
qué pasó (``evento``) y con qué detalle. Los emite el CÓDIGO del pipeline desde los contratos
ya validados del estado (candidatos, veredicto, razones del veto): ningún LLM redacta un hito,
así que las cifras de ``detalle`` son las de las herramientas.

Los hitos NO entran en ``RunState``: llevan la hora del reloj y el acta debe seguir siendo
reproducible por replay (ADR-009). Viven en ``pipeline_milestones`` (estado de sesión) y en
``runs/<run_id>/bitacora.jsonl``, junto al acta. ``CronologiaComite`` es la secuencia completa:
rechaza hitos desordenados en el tiempo o rondas que retroceden.
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum

from pydantic import AwareDatetime, Field, model_validator

from investmentsys.contracts.common import ContractBase


class FaseComite(StrEnum):
    """Quién habla en el hito. ``COMITE`` es la sesión misma (apertura y cierre)."""

    COMITE = "Comité"
    ANALISTA = "Analista"
    ESTADISTICO = "Estadístico"
    CONSTRUCTOR = "Constructor"
    VALIDADOR = "Escéptico (Validador)"
    REPORTER = "Reporter"


class EventoComite(StrEnum):
    SESION_ABIERTA = "sesion_abierta"
    VIEWS_EMITIDAS = "views_emitidas"
    MERCADO_ESTIMADO = "mercado_estimado"
    PROPUESTA = "propuesta"
    PROPUESTA_POR_DEFECTO = "propuesta_por_defecto"
    VETO = "veto"
    APROBADA = "aprobada"
    ITERACIONES_AGOTADAS = "iteraciones_agotadas"
    ACTA_CONSOLIDADA = "acta_consolidada"


class HitoComite(ContractBase):
    timestamp: AwareDatetime
    fase: FaseComite
    iteracion: int = Field(
        ge=0, description="Ronda Constructor ⇄ Validador; 0 = fuera del bucle (apertura, cierre)."
    )
    evento: EventoComite
    detalle: str = Field(min_length=1)

    @model_validator(mode="after")
    def _veto_con_motivo(self) -> HitoComite:
        # Un veto sin motivo es justo la caja negra que el sprint viene a abrir.
        if self.evento is EventoComite.VETO and "Motivo" not in self.detalle:
            raise ValueError("un hito de veto lleva su motivo en el detalle ('Motivo: …')")
        return self

    def linea(self) -> str:
        """``«Escéptico (Validador) · ronda 1: VETO. Motivo: …»``, como lo lee el usuario."""
        ronda = f" · ronda {self.iteracion}" if self.iteracion else ""
        return f"{self.fase.value}{ronda}: {self.detalle}"


class CronologiaComite(ContractBase):
    """La deliberación completa, en orden. Lo que se narra al cierre sale de aquí."""

    hitos: tuple[HitoComite, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _en_orden(self) -> CronologiaComite:
        for anterior, actual in zip(self.hitos, self.hitos[1:], strict=False):
            if actual.timestamp < anterior.timestamp:
                raise ValueError(f"hitos fuera de orden: '{actual.linea()}' es anterior al previo")
        rondas = [h.iteracion for h in self.hitos if h.iteracion]
        if rondas != sorted(rondas):
            raise ValueError("las rondas del comité no retroceden")
        return self

    @property
    def duracion(self) -> timedelta:
        return self.hitos[-1].timestamp - self.hitos[0].timestamp

    @property
    def iteraciones(self) -> int:
        return max((h.iteracion for h in self.hitos), default=0)

    @property
    def vetos(self) -> tuple[HitoComite, ...]:
        return tuple(h for h in self.hitos if h.evento is EventoComite.VETO)

    def transcurrido(self, hito: HitoComite) -> timedelta:
        return hito.timestamp - self.hitos[0].timestamp
