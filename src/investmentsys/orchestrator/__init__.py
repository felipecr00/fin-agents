"""Orquestación de la corrida completa y persistencia de ``RunState``."""

from investmentsys.orchestrator.corrida import (
    ARCHIVO_REPORTE,
    ARCHIVO_RUN_STATE,
    CLAVE_DIRECTORIO,
    CLAVE_REPORTE,
    armar_run_state,
    persistir,
)
from investmentsys.orchestrator.pipeline import EtapaFallidaError, crear_pipeline

__all__ = [
    "ARCHIVO_REPORTE",
    "ARCHIVO_RUN_STATE",
    "CLAVE_DIRECTORIO",
    "CLAVE_REPORTE",
    "EtapaFallidaError",
    "armar_run_state",
    "crear_pipeline",
    "persistir",
]
