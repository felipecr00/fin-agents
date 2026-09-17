"""Orquestación de la corrida completa y persistencia de ``RunState``."""

from investmentsys.orchestrator.corrida import (
    ARCHIVO_REPORTE,
    ARCHIVO_RUN_STATE,
    CLAVE_DIRECTORIO,
    CLAVE_REPORTE,
    CLAVE_RUN_STATE,
    armar_run_state,
    persistir,
)
from investmentsys.orchestrator.pipeline import EtapaFallidaError, crear_pipeline
from investmentsys.orchestrator.replay import Diferencia, ResultadoReplay, repetir

__all__ = [
    "ARCHIVO_REPORTE",
    "ARCHIVO_RUN_STATE",
    "CLAVE_DIRECTORIO",
    "CLAVE_REPORTE",
    "CLAVE_RUN_STATE",
    "Diferencia",
    "EtapaFallidaError",
    "ResultadoReplay",
    "armar_run_state",
    "crear_pipeline",
    "persistir",
    "repetir",
]
