"""Construcción de ``QuantEstimates``. Código puro: sin ADK, sin LLM (ADR-003)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date

import numpy as np
import pandas as pd
from scipy import stats

from investmentsys.config import RegimenConfig
from investmentsys.contracts import (
    MetodoCovarianza,
    QuantEstimates,
    RegimenMercado,
    RetornoEsperado,
)
from investmentsys.quant.covariance import MuestraInsuficienteError, estimar_covarianza
from investmentsys.quant.errores import LookAheadError
from investmentsys.quant.regimen import clasificar_regimen


def estimar(
    retornos: pd.DataFrame,
    fecha_decision: date,
    periodos_por_anio: int,
    ventana_meses: int,
    metodos: Sequence[MetodoCovarianza],
    *,
    nivel_confianza: float,
    regimen: RegimenConfig | None = None,
    universe_version: str | None = None,
) -> QuantEstimates:
    """Covarianzas por método, retornos históricos con intervalo y régimen.

    - Se usan las últimas ``ventana_meses`` filas de ``retornos`` (índice temporal).
    - Ninguna fila puede ser posterior a ``fecha_decision`` (guarda de look-ahead: se
      lanza ``LookAheadError`` antes de calcular nada).
    - Retorno histórico anualizado = media por período × ``periodos_por_anio``, con
      intervalo t de Student al ``nivel_confianza`` sobre la media (cada activo con su
      propia muestra, como la covarianza híbrida).
    - Régimen: ``quant.regimen.clasificar_regimen`` sobre TODA la muestra recibida (no solo la
      ventana de covarianza) si se pasa ``regimen``; sin él, ``INDETERMINADO``.
    - ``universe_version`` sella el resultado con el ``Universe`` sobre el que se calculó
      (ADR-012). ``None`` = sin sellar: solo para el núcleo llamado directamente.
    """
    if not metodos:
        raise ValueError("se necesita al menos un método de covarianza")
    if retornos.empty:
        raise ValueError("retornos vacío")
    indice = pd.DatetimeIndex(retornos.index)
    limite = pd.Timestamp(fecha_decision)
    if (indice > limite).any():
        raise LookAheadError(
            f"look-ahead: hay retornos hasta {indice.max().date()}, posteriores a "
            f"la fecha de decisión {fecha_decision}"
        )

    ventana = retornos.iloc[-ventana_meses:]
    activos = tuple(str(c) for c in ventana.columns)
    covarianzas = {
        metodo: estimar_covarianza(ventana, metodo, ventana_meses, periodos_por_anio)
        for metodo in dict.fromkeys(metodos)
    }
    retornos_historicos = tuple(
        _retorno_historico(activo, ventana[activo], periodos_por_anio, nivel_confianza)
        for activo in activos
    )
    indice_ventana = pd.DatetimeIndex(ventana.index)
    return QuantEstimates(
        fecha_decision=fecha_decision,
        fecha_inicio_muestra=indice_ventana[0].date(),
        fecha_fin_muestra=indice_ventana[-1].date(),
        activos=activos,
        periodos_por_anio=periodos_por_anio,
        covarianzas=covarianzas,
        retornos_historicos=retornos_historicos,
        regimen=(
            clasificar_regimen(retornos, fecha_decision, regimen).regimen
            if regimen is not None
            else RegimenMercado.INDETERMINADO
        ),
        universe_version=universe_version,
    )


def _retorno_historico(
    activo: str, serie: pd.Series, periodos_por_anio: int, nivel_confianza: float
) -> RetornoEsperado:
    x = serie.to_numpy(dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 2:
        raise MuestraInsuficienteError(f"{activo}: {n} retornos, se necesitan ≥ 2")
    media = float(np.mean(x)) * periodos_por_anio
    error_estandar = float(np.std(x, ddof=1)) / math.sqrt(n) * periodos_por_anio
    t_critico = float(stats.t.ppf((1.0 + nivel_confianza) / 2.0, df=n - 1))
    semiancho = t_critico * error_estandar
    return RetornoEsperado(
        activo=activo,
        media_anual=media,
        intervalo_inferior=media - semiancho,
        intervalo_superior=media + semiancho,
        nivel_confianza=nivel_confianza,
    )
