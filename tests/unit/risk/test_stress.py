"""Tests de los stress tests históricos: ventanas, recorte y omisión sin look-ahead."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from investmentsys.config import Config, EscenarioStressConfig
from investmentsys.risk import stress_historico
from tests.conftest import FECHA
from tests.unit.risk.conftest import PESOS_REFERENCIA


def _stress(config: Config, precios: pd.DataFrame, escenarios, fecha: date = FECHA):
    return stress_historico(
        PESOS_REFERENCIA,
        precios,
        escenarios,
        fecha_decision=fecha,
        max_drawdown_tolerado=config.validacion.max_drawdown_tolerado,
        costo_transaccion_bps=config.validacion.costo_transaccion_bps,
        rebalanceo=config.validacion.rebalanceo,
    )


def test_ventanas_de_los_escenarios_del_config(
    config: Config, precios_reales: pd.DataFrame
) -> None:
    tasas, cripto = _stress(config, precios_reales, config.validacion.escenarios_stress)
    # tasas_2022: base 2021-12-31 (cierre anterior a enero), 12 retornos hasta 2022-12-31.
    assert (tasas.fecha_inicio, tasas.fecha_fin) == (date(2021, 12, 31), date(2022, 12, 31))
    assert tasas.retorno_periodo < 0 and tasas.max_drawdown > 0.25
    assert tasas.superado
    assert (cripto.fecha_inicio, cripto.fecha_fin) == (date(2025, 7, 31), date(2026, 6, 30))
    assert cripto.superado


def test_escenario_se_recorta_en_la_fecha_de_decision(
    config: Config, precios_reales: pd.DataFrame
) -> None:
    fecha = date(2022, 6, 30)
    (tasas,) = _stress(
        config,
        precios_reales.loc[precios_reales.index <= pd.Timestamp(fecha)],
        config.validacion.escenarios_stress,
        fecha=fecha,
    )
    assert tasas.fecha_fin == fecha


def test_escenario_sin_datos_se_omite(config: Config, precios_reales: pd.DataFrame) -> None:
    futuro = EscenarioStressConfig(
        nombre="futuro", desde=date(2027, 1, 31), hasta=date(2027, 12, 31)
    )
    assert _stress(config, precios_reales, (futuro,)) == ()


def test_escenario_desde_el_primer_cierre_no_tiene_base_anterior(
    config: Config, precios_reales: pd.DataFrame
) -> None:
    inicio = EscenarioStressConfig(
        nombre="inicio", desde=date(2021, 9, 30), hasta=date(2021, 12, 31)
    )
    (r,) = _stress(config, precios_reales, (inicio,))
    assert (r.fecha_inicio, r.fecha_fin) == (date(2021, 9, 30), date(2021, 12, 31))


def test_umbral_decide_superado(config: Config, precios_reales: pd.DataFrame) -> None:
    (tasas,) = stress_historico(
        PESOS_REFERENCIA,
        precios_reales,
        config.validacion.escenarios_stress[:1],
        fecha_decision=FECHA,
        max_drawdown_tolerado=0.10,
        costo_transaccion_bps=0.0,
        rebalanceo="mensual",
    )
    assert not tasas.superado
    assert tasas.max_drawdown == pytest.approx(0.29, abs=0.01)
