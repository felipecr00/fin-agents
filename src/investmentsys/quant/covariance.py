"""Estimadores de covarianza. Código puro: sin ADK, sin LLM. Implementación en S1."""

from __future__ import annotations

import pandas as pd

from investmentsys.contracts import MatrizCovarianza, MetodoCovarianza


def estimar_covarianza(
    retornos: pd.DataFrame,
    metodo: MetodoCovarianza,
    ventana_meses: int,
    periodos_por_anio: int,
) -> MatrizCovarianza:
    """Covarianza anualizada a partir de retornos logarítmicos por período.

    Contrato esperado por el golden test (ver ``docs/referencia_black_litterman.py``):
    - ``historica``: desviaciones y correlaciones muestrales (ddof=1) sobre las últimas
      ``ventana_meses`` observaciones; para un activo de inicio tardío, su volatilidad y
      sus correlaciones se estiman sobre la ventana común con cada par (sin descartar la
      muestra larga de los demás). Anualización: varianza × ``periodos_por_anio``.
    - ``ledoit_wolf``: contracción de Ledoit-Wolf sobre la misma ventana.
    """
    raise NotImplementedError("S1: estimar_covarianza pendiente de implementación")
