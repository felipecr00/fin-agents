"""Tests de ``estimar``: construcción de ``QuantEstimates`` y guarda de look-ahead."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from investmentsys.contracts import MetodoCovarianza, RegimenMercado
from investmentsys.quant import LookAheadError, estimar
from tests.conftest import ACTIVOS, FECHA
from tests.unit.quant.conftest import PERIODOS, VENTANA, panel_sintetico

NIVEL = 0.95
METODOS = (MetodoCovarianza.HISTORICA, MetodoCovarianza.LEDOIT_WOLF)


def _estimar(retornos: pd.DataFrame, fecha: date = FECHA, ventana: int = VENTANA):
    return estimar(
        retornos,
        fecha_decision=fecha,
        periodos_por_anio=PERIODOS,
        ventana_meses=ventana,
        metodos=METODOS,
        nivel_confianza=NIVEL,
    )


def test_construye_el_contrato_completo(retornos_reales: pd.DataFrame) -> None:
    est = _estimar(retornos_reales)
    assert est.activos == ACTIVOS
    assert est.fecha_decision == FECHA
    assert est.fecha_inicio_muestra == date(2021, 10, 31)
    assert est.fecha_fin_muestra == FECHA
    assert est.periodos_por_anio == PERIODOS
    assert set(est.covarianzas) == set(METODOS)
    assert est.regimen is RegimenMercado.INDETERMINADO
    assert tuple(r.activo for r in est.retornos_historicos) == ACTIVOS


def test_retornos_historicos_anualizados_con_intervalo_t(retornos_reales: pd.DataFrame) -> None:
    est = _estimar(retornos_reales)
    for r in est.retornos_historicos:
        x = retornos_reales[r.activo].dropna()
        n = len(x)
        media = x.mean() * PERIODOS
        semiancho = stats.t.ppf((1 + NIVEL) / 2, df=n - 1) * x.std(ddof=1) / math.sqrt(n) * PERIODOS
        assert r.media_anual == pytest.approx(media)
        assert r.intervalo_inferior == pytest.approx(media - semiancho)
        assert r.intervalo_superior == pytest.approx(media + semiancho)
        assert r.nivel_confianza == NIVEL
    ibit = next(r for r in est.retornos_historicos if r.activo == "IBIT")
    voog = next(r for r in est.retornos_historicos if r.activo == "VOOG")
    assert ibit.intervalo_superior - ibit.intervalo_inferior > (
        voog.intervalo_superior - voog.intervalo_inferior
    )


def test_rechaza_retornos_posteriores_a_la_fecha_de_decision(
    retornos_reales: pd.DataFrame,
) -> None:
    with pytest.raises(LookAheadError, match="look-ahead"):
        _estimar(retornos_reales, fecha=date(2026, 8, 31))


def test_acepta_fecha_de_decision_posterior_a_la_muestra(retornos_reales: pd.DataFrame) -> None:
    est = _estimar(retornos_reales, fecha=date(2026, 10, 15))
    assert est.fecha_fin_muestra == FECHA


def test_la_ventana_fija_el_inicio_de_la_muestra() -> None:
    panel = panel_sintetico(48)
    est = _estimar(panel, ventana=24)
    assert est.fecha_inicio_muestra == panel.index[-24].date()
    assert est.covarianza(MetodoCovarianza.HISTORICA).ventana_meses == 24


def test_metodos_repetidos_se_calculan_una_vez(retornos_reales: pd.DataFrame) -> None:
    est = estimar(
        retornos_reales,
        fecha_decision=FECHA,
        periodos_por_anio=PERIODOS,
        ventana_meses=VENTANA,
        metodos=(MetodoCovarianza.HISTORICA, MetodoCovarianza.HISTORICA),
        nivel_confianza=NIVEL,
    )
    assert list(est.covarianzas) == [MetodoCovarianza.HISTORICA]


def test_es_determinista(retornos_reales: pd.DataFrame) -> None:
    assert _estimar(retornos_reales) == _estimar(retornos_reales)


def test_rechaza_entradas_vacias(retornos_reales: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="método"):
        estimar(retornos_reales, FECHA, PERIODOS, VENTANA, (), nivel_confianza=NIVEL)
    vacio = retornos_reales.iloc[0:0]
    with pytest.raises(ValueError, match="vacío"):
        estimar(vacio, FECHA, PERIODOS, VENTANA, METODOS, nivel_confianza=NIVEL)


def test_no_hay_nan_en_la_salida(retornos_reales: pd.DataFrame) -> None:
    est = _estimar(retornos_reales)
    for matriz in est.covarianzas.values():
        assert not np.isnan(np.array(matriz.valores)).any()
