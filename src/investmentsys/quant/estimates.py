"""Construcción de ``QuantEstimates``. Código puro. Implementación en S1."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import pandas as pd

from investmentsys.contracts import MetodoCovarianza, QuantEstimates


def estimar(
    retornos: pd.DataFrame,
    fecha_decision: date,
    periodos_por_anio: int,
    ventana_meses: int,
    metodos: Sequence[MetodoCovarianza],
) -> QuantEstimates:
    """Covarianzas por método, retornos históricos con intervalo y régimen.

    ``retornos`` no puede contener fechas posteriores a ``fecha_decision``; el contrato
    de salida lo verifica (``fecha_fin_muestra <= fecha_decision``).
    """
    raise NotImplementedError("S1: estimar pendiente de implementación")
