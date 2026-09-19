"""Clasificador simple de régimen de mercado. Código puro: sin ADK ni LLM.

Tres indicadores sobre un índice de referencia (promedio simple de los retornos log de
``regimen.activos_referencia``), todos con datos hasta la fecha de decisión:

- **tendencia**: retorno acumulado de los últimos ``ventana_tendencia_meses``;
- **ratio de volatilidad**: volatilidad de los últimos ``ventana_volatilidad_meses`` sobre la de
  toda la muestra disponible;
- **drawdown**: caída del índice desde su máximo de la muestra.

Reglas, en orden:

1. menos de ``observaciones_minimas`` → ``INDETERMINADO``;
2. drawdown ≥ ``drawdown_estres`` y ratio ≥ ``ratio_volatilidad_estres`` → ``ESTRES``;
3. tendencia ≥ +``umbral_tendencia`` → ``ALCISTA``; ≤ −``umbral_tendencia`` → ``BAJISTA``;
4. en otro caso → ``LATERAL``.

Es una etiqueta descriptiva para los informes: ninguna etapa cambia pesos por ella.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from investmentsys.config import RegimenConfig
from investmentsys.contracts import RegimenMercado
from investmentsys.quant.errores import LookAheadError


@dataclass(frozen=True)
class DiagnosticoRegimen:
    regimen: RegimenMercado
    observaciones: int
    tendencia: float | None
    ratio_volatilidad: float | None
    drawdown: float | None
    motivo: str


def clasificar_regimen(
    retornos: pd.DataFrame, fecha_decision: date, regimen: RegimenConfig
) -> DiagnosticoRegimen:
    """``retornos``: retornos log por período, índice temporal, una columna por activo."""
    indice = pd.DatetimeIndex(retornos.index)
    if len(indice) and (indice > pd.Timestamp(fecha_decision)).any():
        raise LookAheadError(
            f"look-ahead: hay retornos hasta {indice.max().date()}, posteriores a "
            f"la fecha de decisión {fecha_decision}"
        )
    faltan = [a for a in regimen.activos_referencia if a not in retornos.columns]
    if faltan:
        raise ValueError(f"activos de referencia sin retornos: {faltan}")

    serie = retornos[list(regimen.activos_referencia)].mean(axis=1, skipna=True).dropna()
    n = len(serie)
    if n < regimen.observaciones_minimas:
        return DiagnosticoRegimen(
            RegimenMercado.INDETERMINADO,
            n,
            None,
            None,
            None,
            f"{n} observaciones; se necesitan {regimen.observaciones_minimas}",
        )

    valores = serie.to_numpy(dtype=float)
    tendencia = math.expm1(float(valores[-regimen.ventana_tendencia_meses :].sum()))
    vol_reciente = float(np.std(valores[-regimen.ventana_volatilidad_meses :], ddof=1))
    vol_larga = float(np.std(valores, ddof=1))
    ratio = vol_reciente / vol_larga if vol_larga > 0.0 else 1.0
    nivel = np.exp(np.concatenate([[0.0], np.cumsum(valores)]))
    drawdown = float(1.0 - nivel[-1] / nivel.max())

    if drawdown >= regimen.drawdown_estres and ratio >= regimen.ratio_volatilidad_estres:
        etiqueta = RegimenMercado.ESTRES
        motivo = (
            f"drawdown {drawdown:.1%} ≥ {regimen.drawdown_estres:.0%} y volatilidad reciente "
            f"{ratio:.2f}× la de la muestra (≥ {regimen.ratio_volatilidad_estres:.2f}×)"
        )
    elif abs(tendencia) >= regimen.umbral_tendencia:
        etiqueta = RegimenMercado.ALCISTA if tendencia > 0 else RegimenMercado.BAJISTA
        motivo = (
            f"tendencia de {regimen.ventana_tendencia_meses} meses {tendencia:+.1%} "
            f"(umbral ±{regimen.umbral_tendencia:.0%})"
        )
    else:
        etiqueta = RegimenMercado.LATERAL
        motivo = (
            f"tendencia de {regimen.ventana_tendencia_meses} meses {tendencia:+.1%}, dentro de "
            f"±{regimen.umbral_tendencia:.0%}"
        )
    return DiagnosticoRegimen(etiqueta, n, tendencia, ratio, drawdown, motivo)
