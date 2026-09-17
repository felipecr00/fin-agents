"""Del estado de sesión de ADK a ``RunState``, y de ``RunState`` a ``runs/<run_id>/``."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from investmentsys.config import Config, hash_config
from investmentsys.contracts import EtapaCorrida, RunState
from investmentsys.tools.estado import (
    CLAVE_CANDIDATOS,
    CLAVE_FECHA_DECISION,
    CLAVE_MARKET_VIEWS,
    CLAVE_QUANT_ESTIMATES,
    CLAVE_RESTRICCIONES,
    CLAVE_VALIDACIONES,
    EstadoLegible,
)

CLAVE_RUN_ID = "run_id"
CLAVE_CREADO_EN = "creado_en"
CLAVE_NOTAS = "notas_corrida"
CLAVE_NARRATIVA = "reporte_narrativa"
CLAVE_REPORTE = "reporte_markdown"
CLAVE_DIRECTORIO = "directorio_corrida"

ARCHIVO_RUN_STATE = "run_state.json"
ARCHIVO_REPORTE = "reporte.md"


def nuevo_run_id(ahora: datetime | None = None) -> tuple[str, datetime]:
    """``runs/<timestamp>/``: UTC con microsegundos, ordenable y sin colisiones prácticas."""
    ahora = ahora or datetime.now(UTC)
    return ahora.strftime("%Y%m%dT%H%M%S_%fZ"), ahora


def armar_run_state(
    estado: EstadoLegible | Mapping[str, Any], config: Config, etapa: EtapaCorrida, **extra: Any
) -> RunState:
    """Revalida TODOS los contratos del estado y su coherencia cruzada (``RunState``)."""
    return RunState.model_validate(
        {
            "run_id": estado.get(CLAVE_RUN_ID),
            "creado_en": estado.get(CLAVE_CREADO_EN),
            "fecha_decision": estado.get(CLAVE_FECHA_DECISION),
            "semilla": config.reproducibilidad.semilla,
            "config_hash": hash_config(),
            "activos": config.portafolio.activos,
            "etapa": etapa,
            "restricciones": estado.get(CLAVE_RESTRICCIONES),
            "market_views": estado.get(CLAVE_MARKET_VIEWS),
            "quant_estimates": estado.get(CLAVE_QUANT_ESTIMATES),
            "candidatos": estado.get(CLAVE_CANDIDATOS) or (),
            "validaciones": estado.get(CLAVE_VALIDACIONES) or (),
            **extra,
        }
    )


def persistir(corrida: RunState, directorio_runs: Path) -> Path:
    destino = directorio_runs / corrida.run_id
    destino.mkdir(parents=True, exist_ok=False)
    (destino / ARCHIVO_RUN_STATE).write_text(corrida.model_dump_json(indent=2), encoding="utf-8")
    if corrida.reporte_markdown:
        (destino / ARCHIVO_REPORTE).write_text(corrida.reporte_markdown, encoding="utf-8")
    return destino
