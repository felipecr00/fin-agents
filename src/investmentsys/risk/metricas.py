"""Métricas fuera de muestra de un ``ResultadoBacktest``. Código puro."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from investmentsys.contracts import MetricasOOS
from investmentsys.risk.backtest import ResultadoBacktest

# Mínimo de retornos para una desviación estándar muestral (ddof=1).
_MIN_OBS_VOLATILIDAD = 2


def metricas_oos(
    resultado: ResultadoBacktest, *, periodos_por_anio: int, tasa_libre_riesgo: float
) -> MetricasOOS:
    """Anualiza el backtest.

    - Retorno anualizado: geométrico, ``valor_final ** (ppa / n) − 1``.
    - Volatilidad: desviación muestral (ddof=1) × √ppa.
    - Sharpe OOS: (media aritmética × ppa − rf) / volatilidad; 0 si la volatilidad es nula.
    - Turnover anual: Σ turnover / años simulados.
    """
    n = resultado.n_periodos
    anios = n / periodos_por_anio
    retornos = resultado.retornos.to_numpy(dtype=float)
    valor_final = float(resultado.valor.iloc[-1])
    retorno_anualizado = valor_final ** (1.0 / anios) - 1.0
    volatilidad = (
        float(np.std(retornos, ddof=1)) * math.sqrt(periodos_por_anio)
        if n >= _MIN_OBS_VOLATILIDAD
        else 0.0
    )
    exceso = float(np.mean(retornos)) * periodos_por_anio - tasa_libre_riesgo
    return MetricasOOS(
        fecha_inicio=resultado.fechas_decision[0].date(),
        fecha_fin=pd.Timestamp(resultado.retornos.index[-1]).date(),
        n_periodos=n,
        retorno_anualizado=retorno_anualizado,
        volatilidad_anualizada=volatilidad,
        sharpe_oos=exceso / volatilidad if volatilidad > 0.0 else 0.0,
        max_drawdown=max_drawdown(resultado.valor),
        turnover_anual=float(resultado.turnover.sum()) / anios,
        costo_transaccion_total=float(resultado.costos.sum()),
    )


def max_drawdown(valor: pd.Series) -> float:
    """Mayor caída desde un máximo previo, como fracción positiva (0.35 = −35 %)."""
    v = valor.to_numpy(dtype=float)
    caidas = 1.0 - v / np.maximum.accumulate(v)
    return float(np.max(caidas))


def drawdown_por_activo(precios: pd.DataFrame) -> dict[str, float]:
    """Max drawdown de cada columna sobre sus precios válidos (0 si tiene < 2 precios)."""
    resultado: dict[str, float] = {}
    for activo in precios.columns:
        serie = precios[activo].dropna()
        resultado[str(activo)] = max_drawdown(serie) if len(serie) >= 2 else 0.0
    return resultado


def concentracion_hhi(pesos: pd.DataFrame) -> tuple[float, pd.Timestamp]:
    """Máximo índice Herfindahl (Σw²) de los pesos aplicados y la fecha en que ocurre."""
    hhi = (pesos**2).sum(axis=1).to_numpy(dtype=float)
    posicion = int(np.argmax(hhi))
    return float(hhi[posicion]), pd.DatetimeIndex(pesos.index)[posicion]
