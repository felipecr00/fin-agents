"""Tests de métricas OOS contra cálculos a mano."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from investmentsys.risk import (
    backtest_walk_forward,
    concentracion_hhi,
    drawdown_por_activo,
    max_drawdown,
    metricas_oos,
    pesos_fijos,
)
from tests.unit.risk.conftest import PESOS_REFERENCIA

RF = 0.04


def test_max_drawdown_a_mano() -> None:
    valor = pd.Series([1.0, 1.2, 0.9, 1.1, 0.8, 1.3])
    assert max_drawdown(valor) == pytest.approx(1 - 0.8 / 1.2)
    assert max_drawdown(pd.Series([1.0, 1.1, 1.2])) == 0.0


def test_metricas_oos_coinciden_con_el_calculo_directo(precios_reales: pd.DataFrame) -> None:
    res = backtest_walk_forward(
        precios_reales,
        pesos_fijos(PESOS_REFERENCIA),
        costo_transaccion_bps=10,
        rebalanceo="mensual",
    )
    m = metricas_oos(res, periodos_por_anio=12, tasa_libre_riesgo=RF)
    r = res.retornos.to_numpy()
    anios = len(r) / 12
    assert m.n_periodos == 60
    assert m.retorno_anualizado == pytest.approx(res.valor.iloc[-1] ** (1 / anios) - 1)
    vol = np.std(r, ddof=1) * math.sqrt(12)
    assert m.volatilidad_anualizada == pytest.approx(vol)
    assert m.sharpe_oos == pytest.approx((np.mean(r) * 12 - RF) / vol)
    assert m.max_drawdown == pytest.approx(max_drawdown(res.valor))
    assert m.turnover_anual == pytest.approx(res.turnover.sum() / anios)
    assert m.costo_transaccion_total == pytest.approx(res.costos.sum())
    assert m.fecha_inicio == res.fechas_decision[0].date()
    assert m.fecha_fin == res.retornos.index[-1].date()


def test_concentracion_hhi_devuelve_el_maximo_y_su_fecha() -> None:
    pesos = pd.DataFrame(
        {"A": [0.5, 0.9, 0.6], "B": [0.5, 0.1, 0.4]},
        index=pd.DatetimeIndex(["2024-01-31", "2024-02-29", "2024-03-31"]),
    )
    hhi, fecha = concentracion_hhi(pesos)
    assert hhi == pytest.approx(0.82)
    assert fecha == pd.Timestamp("2024-02-29")


def test_drawdown_por_activo_ignora_nan_iniciales(precios_reales: pd.DataFrame) -> None:
    caidas = drawdown_por_activo(precios_reales)
    assert set(caidas) == set(precios_reales.columns)
    assert caidas["IBIT"] == pytest.approx(1 - 33.29 / 66.32)
    assert caidas["VOOG"] == pytest.approx(1 - 33.79 / 48.60)
