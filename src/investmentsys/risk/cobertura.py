"""Qué ventanas de la historia cubren los datos de cada activo. Código puro.

Lo usan el Gestor de Datos (advertencias del diagnóstico) y el Escéptico (degradación explícita
de backtest y stress cuando la historia es corta): una sola regla, dos consumidores.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from enum import StrEnum

from investmentsys.config import EscenarioStressConfig


class Cobertura(StrEnum):
    COMPLETA = "completa"
    PARCIAL = "parcial"
    NINGUNA = "ninguna"


def cobertura_escenario(inicio_datos: date, escenario: EscenarioStressConfig) -> Cobertura:
    """El primer retorno del escenario necesita un precio ANTERIOR a ``escenario.desde``."""
    if inicio_datos < escenario.desde:
        return Cobertura.COMPLETA
    return Cobertura.PARCIAL if inicio_datos < escenario.hasta else Cobertura.NINGUNA


def advertencias_de_cobertura(
    inicio_datos: date,
    meses_disponibles: int,
    escenarios: Sequence[EscenarioStressConfig],
    ventana_covarianza_meses: int,
) -> tuple[str, ...]:
    avisos: list[str] = []
    if meses_disponibles < ventana_covarianza_meses:
        avisos.append(
            f"historia corta: {meses_disponibles} meses (desde {inicio_datos:%Y-%m}) frente a la "
            f"ventana de {ventana_covarianza_meses}; covarianza y backtest solo lo ven desde esa "
            "fecha"
        )
    for e in escenarios:
        cobertura = cobertura_escenario(inicio_datos, e)
        if cobertura is Cobertura.NINGUNA:
            avisos.append(
                f"ventana corta: stress {e.nombre} no aplica (datos desde {inicio_datos:%Y-%m})"
            )
        elif cobertura is Cobertura.PARCIAL:
            avisos.append(
                f"ventana corta: stress {e.nombre} aplica solo en parte (datos desde "
                f"{inicio_datos:%Y-%m})"
            )
    return tuple(avisos)
