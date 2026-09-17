"""Estrategias listas para el backtest walk-forward. Código puro (ADR-004).

Una estrategia es ``(precios, fecha) -> pesos`` y solo puede usar filas ≤ ``fecha``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date

import numpy as np
import pandas as pd

from investmentsys.contracts import CandidatePortfolio, MetodoCovarianza, QuantEstimates
from investmentsys.quant import estimar
from investmentsys.risk.backtest import Estrategia

Constructor = Callable[[QuantEstimates], CandidatePortfolio]
"""Optimizador de ``portfolio/`` con sus restricciones y config ya ligadas."""


def pesos_fijos(pesos: Mapping[str, float]) -> Estrategia:
    """Cartera estratégica constante: en cada rebalanceo se vuelve a ``pesos``."""
    objetivo = dict(pesos)

    def estrategia(precios: pd.DataFrame, fecha: date) -> Mapping[str, float]:
        return objetivo

    return estrategia


def reestimada(
    constructor: Constructor,
    *,
    ventana_meses: int,
    metodos: Sequence[MetodoCovarianza],
    nivel_confianza: float,
    periodos_por_anio: int,
) -> Estrategia:
    """Re-estima ``QuantEstimates`` con los datos hasta ``fecha`` y reoptimiza con ``constructor``.

    Es el walk-forward genuino de una técnica: en cada decisión se recalculan covarianzas y
    retornos con la muestra disponible en ese momento. ``estimar`` lanza ``LookAheadError``
    si recibiera una fila posterior a ``fecha``; por eso se trunca antes.
    """

    def estrategia(precios: pd.DataFrame, fecha: date) -> Mapping[str, float]:
        historia = precios.loc[pd.DatetimeIndex(precios.index) <= pd.Timestamp(fecha)]
        estimates = estimar(
            retornos_log(historia),
            fecha_decision=fecha,
            periodos_por_anio=periodos_por_anio,
            ventana_meses=ventana_meses,
            metodos=metodos,
            nivel_confianza=nivel_confianza,
        )
        return constructor(estimates).pesos

    return estrategia


def retornos_log(precios: pd.DataFrame) -> pd.DataFrame:
    """``ln(P_t / P_{t-1})``; se descarta el primer período (misma convención que ``data/``)."""
    log_precios = pd.DataFrame(
        np.log(precios.to_numpy(dtype=float)), index=precios.index, columns=precios.columns
    )
    return log_precios.diff().iloc[1:]
