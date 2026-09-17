"""Tests del backtest walk-forward: mecánica a mano, costos en cada rebalanceo, guardas."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from investmentsys.risk import ResultadoBacktest, backtest_walk_forward, pesos_fijos
from tests.unit.risk.conftest import panel_con_inicio_tardio, panel_manual

BPS = 10.0
TASA = BPS / 10_000


def _correr(
    panel: pd.DataFrame,
    pesos: dict[str, float],
    costo_transaccion_bps: float = BPS,
    **kw: object,
) -> ResultadoBacktest:
    return backtest_walk_forward(
        panel,
        pesos_fijos(pesos),
        costo_transaccion_bps=costo_transaccion_bps,
        rebalanceo="mensual",
        **kw,  # type: ignore[arg-type]
    )


def test_mecanica_calculada_a_mano() -> None:
    """60/40 sobre panel_manual. Período 1: r = 0.6·0.10 + 0.4·0 = 0.06, sin costo de entrada.
    Pesos derivados: A = 0.66/1.06, B = 0.40/1.06. Período 2: se rebalancea a 60/40,
    turnover = 2·|0.6 − 0.66/1.06|, costo = turnover·10 bps, r_bruto = 0.6·(−0.2) + 0.4·0.1.
    """
    res = backtest_walk_forward(
        panel_manual(),
        pesos_fijos({"A": 0.6, "B": 0.4}),
        costo_transaccion_bps=BPS,
        rebalanceo="mensual",
    )
    assert res.n_periodos == 2
    assert list(res.fechas_decision.date) == [date(2024, 1, 31), date(2024, 2, 29)]
    assert res.retornos.iloc[0] == pytest.approx(0.06)
    assert res.turnover.iloc[0] == 0.0 and res.costos.iloc[0] == 0.0
    derivado_a = 0.66 / 1.06
    turnover_2 = 2 * abs(0.6 - derivado_a)
    assert res.turnover.iloc[1] == pytest.approx(turnover_2)
    assert res.costos.iloc[1] == pytest.approx(turnover_2 * TASA)
    r_bruto_2 = 0.6 * (-0.2) + 0.4 * 0.1
    assert res.retornos.iloc[1] == pytest.approx((1 - turnover_2 * TASA) * (1 + r_bruto_2) - 1)
    assert res.valor.iloc[0] == 1.0
    assert res.valor.iloc[-1] == pytest.approx(
        (1 + res.retornos.iloc[0]) * (1 + res.retornos.iloc[1])
    )
    assert res.pesos.iloc[1].tolist() == pytest.approx([0.6, 0.4])


def test_los_costos_se_cobran_en_cada_rebalanceo(precios_reales: pd.DataFrame) -> None:
    pesos = {"VOOG": 0.70, "BNS": 0.07, "IBIT": 0.02, "VB": 0.21}
    con = _correr(precios_reales, pesos)
    sin = _correr(precios_reales, pesos, costo_transaccion_bps=0.0)
    assert (con.turnover.iloc[1:] > 0).all(), "con deriva mensual, cada rebalanceo mueve pesos"
    np.testing.assert_allclose(con.costos.to_numpy(), con.turnover.to_numpy() * TASA)
    # El capital final con costos es exactamente el sin costos descontado por cada rebalanceo.
    factor = np.prod(1.0 - con.costos.to_numpy())
    assert con.valor.iloc[-1] == pytest.approx(sin.valor.iloc[-1] * factor)
    assert con.costos.sum() > 0.0


def test_el_costo_de_entrada_se_cobra_solo_con_pesos_iniciales() -> None:
    pesos = {"A": 0.6, "B": 0.4}
    sin_entrada = _correr(panel_manual(), pesos)
    con_entrada = _correr(panel_manual(), pesos, pesos_iniciales={"A": 1.0, "B": 0.0})
    assert sin_entrada.turnover.iloc[0] == 0.0
    assert con_entrada.turnover.iloc[0] == pytest.approx(0.8)
    assert con_entrada.retornos.iloc[0] == pytest.approx((1 - 0.8 * TASA) * 1.06 - 1)


def test_activo_sin_precio_reparte_su_peso_entre_los_disponibles() -> None:
    res = _correr(panel_con_inicio_tardio(), {"A": 0.5, "B": 0.25, "C": 0.25})
    assert res.pesos.iloc[0].tolist() == pytest.approx([2 / 3, 1 / 3, 0.0])
    assert res.pesos.iloc[1].tolist() == pytest.approx([0.5, 0.25, 0.25])
    assert res.retornos.iloc[0] == pytest.approx(2 / 3 * 0.10)


def test_es_walk_forward_la_estrategia_decide_en_cada_fecha_sin_la_siguiente() -> None:
    panel = panel_manual()
    fechas_vistas: list[date] = []

    def estrategia(precios: pd.DataFrame, fecha: date) -> dict[str, float]:
        fechas_vistas.append(fecha)
        assert precios is panel or precios.equals(panel)
        return {"A": 1.0, "B": 0.0}

    res = backtest_walk_forward(panel, estrategia, costo_transaccion_bps=0.0, rebalanceo="mensual")
    assert fechas_vistas == [date(2024, 1, 31), date(2024, 2, 29)]
    assert res.retornos.tolist() == pytest.approx([0.10, -0.20])


def test_rango_de_fechas(precios_reales: pd.DataFrame) -> None:
    res = _correr(
        precios_reales,
        {"VOOG": 1.0},
        fecha_inicio=date(2024, 1, 31),
        fecha_fin=date(2024, 6, 30),
    )
    assert res.n_periodos == 5
    assert res.fechas_decision[0].date() == date(2024, 1, 31)
    assert res.valor.index[-1].date() == date(2024, 6, 30)


def test_es_determinista(precios_reales: pd.DataFrame) -> None:
    pesos = {"VOOG": 0.70, "BNS": 0.07, "IBIT": 0.02, "VB": 0.21}
    a, b = _correr(precios_reales, pesos), _correr(precios_reales, pesos)
    pd.testing.assert_series_equal(a.valor, b.valor)
    pd.testing.assert_frame_equal(a.pesos, b.pesos)


@pytest.mark.parametrize(
    ("pesos", "mensaje"),
    [
        ({"A": 0.5, "B": 0.4}, "suman"),
        ({"A": 0.5, "B": 0.5, "Z": 0.0}, "fuera del panel"),
        ({"A": float("nan"), "B": 1.0}, "no finitos"),
    ],
)
def test_rechaza_pesos_invalidos(pesos: dict[str, float], mensaje: str) -> None:
    with pytest.raises(ValueError, match=mensaje):
        _correr(panel_manual(), pesos)


def test_rechaza_parametros_invalidos() -> None:
    with pytest.raises(ValueError, match="rebalanceo"):
        backtest_walk_forward(
            panel_manual(), pesos_fijos({"A": 1.0}), costo_transaccion_bps=0, rebalanceo="diario"
        )
    with pytest.raises(ValueError, match="negativo"):
        _correr(panel_manual(), {"A": 1.0}, costo_transaccion_bps=-1.0)
    with pytest.raises(ValueError, match="al menos 2 fechas"):
        _correr(panel_manual(), {"A": 1.0}, fecha_inicio=date(2024, 3, 31))
    with pytest.raises(ValueError, match="no positivos"):
        panel = panel_manual()
        panel.loc[panel.index[1], "A"] = -1.0
        _correr(panel, {"A": 1.0})
