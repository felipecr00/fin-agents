"""Tests de las estrategias: pesos fijos y re-estimación walk-forward."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from investmentsys.config import Config
from investmentsys.contracts import MetodoCovarianza, PortfolioConstraints, QuantEstimates
from investmentsys.data import CSVPriceProvider
from investmentsys.portfolio import optimizar_min_varianza
from investmentsys.quant import estimar
from investmentsys.risk import pesos_fijos, reestimada, retornos_log
from tests.conftest import ACTIVOS, FECHA
from tests.unit.risk.conftest import PESOS_REFERENCIA


def test_pesos_fijos_devuelve_siempre_lo_mismo(precios_reales: pd.DataFrame) -> None:
    estrategia = pesos_fijos(PESOS_REFERENCIA)
    assert estrategia(precios_reales, date(2022, 1, 31)) == PESOS_REFERENCIA
    assert estrategia(precios_reales, FECHA) == PESOS_REFERENCIA


def test_retornos_log_coincide_con_el_proveedor(
    provider: CSVPriceProvider, precios_reales: pd.DataFrame
) -> None:
    pd.testing.assert_frame_equal(
        retornos_log(precios_reales), provider.retornos_log(ACTIVOS, hasta=FECHA)
    )


def test_reestimada_reproduce_al_optimizador_sobre_la_historia_truncada(
    config: Config, provider: CSVPriceProvider, precios_reales: pd.DataFrame
) -> None:
    restricciones = PortfolioConstraints(
        activos=ACTIVOS,
        peso_min=config.optimizacion.peso_min,
        peso_max=config.optimizacion.peso_max,
    )

    def constructor(est: QuantEstimates):
        return optimizar_min_varianza(est, restricciones, config.optimizacion)

    estrategia = reestimada(
        constructor,
        ventana_meses=config.datos.ventana_covarianza_meses,
        metodos=(MetodoCovarianza.HISTORICA,),
        nivel_confianza=config.estimacion.nivel_confianza,
        periodos_por_anio=provider.periodos_por_anio,
    )
    fecha = date(2025, 6, 30)
    esperado = optimizar_min_varianza(
        estimar(
            provider.retornos_log(ACTIVOS, hasta=fecha),
            fecha_decision=fecha,
            periodos_por_anio=12,
            ventana_meses=config.datos.ventana_covarianza_meses,
            metodos=(MetodoCovarianza.HISTORICA,),
            nivel_confianza=config.estimacion.nivel_confianza,
        ),
        restricciones,
        config.optimizacion,
    ).pesos
    obtenido = estrategia(precios_reales, fecha)
    for a in ACTIVOS:
        assert obtenido[a] == pytest.approx(esperado[a])
