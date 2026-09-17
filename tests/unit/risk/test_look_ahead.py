"""DoD S2: se inyecta look-ahead bias a propósito y se demuestra que se detecta.

Las estrategias tramposas de este archivo reciben el panel completo y miran más allá de
la fecha de decisión. ``verificar_look_ahead`` las desenmascara por invariancia al futuro:
una decisión honesta en ``fecha`` no puede cambiar si solo se altera lo posterior a ``fecha``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import numpy as np
import pandas as pd
import pytest

from investmentsys.config import Config
from investmentsys.contracts import MetodoCovarianza, PortfolioConstraints, QuantEstimates
from investmentsys.data import CSVPriceProvider
from investmentsys.portfolio import optimizar_min_varianza
from investmentsys.quant import LookAheadError
from investmentsys.risk import (
    PERTURBACIONES,
    LookAheadDetectadoError,
    perturbaciones,
    pesos_fijos,
    reestimada,
    validar,
    verificar_look_ahead,
)
from tests.conftest import ACTIVOS, FECHA
from tests.unit.risk.conftest import PESOS_REFERENCIA, candidato

SEMILLA = 42


def _equiponderado(activos: list[str]) -> dict[str, float]:
    return {a: 1.0 / len(activos) for a in activos}


def vision_perfecta(precios: pd.DataFrame, fecha: date) -> Mapping[str, float]:
    """TRAMPA: invierte el 100 % en el activo con mejor retorno en el MES SIGUIENTE a ``fecha``.

    Si no existe el mes siguiente (panel truncado), reparte por igual.
    """
    indice = pd.DatetimeIndex(precios.index)
    hoy = int(np.flatnonzero(indice == pd.Timestamp(fecha))[0])
    if hoy + 1 >= len(indice):
        return _equiponderado([str(c) for c in precios.columns])
    retorno_futuro = precios.iloc[hoy + 1] / precios.iloc[hoy] - 1.0
    ganador = str(retorno_futuro.idxmax())
    return {a: (1.0 if a == ganador else 0.0) for a in map(str, precios.columns)}


def volatilidad_inversa_muestra_completa(precios: pd.DataFrame, fecha: date) -> Mapping[str, float]:
    """TRAMPA sutil: pondera por 1/σ con la volatilidad de TODA la muestra, futuro incluido.

    Invariante a cambiar el signo de los retornos futuros (la varianza no cambia), así que
    solo la caza la perturbación aleatoria o la truncada.
    """
    log_retornos = np.log(precios).diff()
    sigma = log_retornos.std(ddof=1)
    inv = 1.0 / sigma
    return {str(a): float(v) for a, v in (inv / inv.sum()).items()}


def test_vision_perfecta_es_detectada_con_evidencia(precios_reales: pd.DataFrame) -> None:
    fechas = [d.date() for d in precios_reales.index[:-1]]
    with pytest.raises(LookAheadDetectadoError) as info:
        verificar_look_ahead(vision_perfecta, precios_reales, fechas, semilla=SEMILLA)
    error = info.value
    # Se detecta en la PRIMERA fecha de decisión y con la primera perturbación.
    assert error.fecha == date(2021, 9, 30)
    assert error.perturbacion == "sin_futuro"
    # Con el futuro real: 100 % en VOOG (subió 9.1 % en 2021-10, más que BNS y VB).
    assert error.pesos_reales == {"VOOG": 1.0, "BNS": 0.0, "VB": 0.0, "IBIT": 0.0}
    # Sin el futuro la trampa no puede decidir y reparte por igual: la decisión cambió.
    assert error.pesos_perturbados == pytest.approx(_equiponderado(list(ACTIVOS)))
    assert "look-ahead detectado en 2021-09-30" in str(error)
    assert isinstance(error, LookAheadError)


def test_cada_perturbacion_altera_solo_el_futuro_y_cambia_la_decision_tramposa(
    precios_reales: pd.DataFrame,
) -> None:
    fecha = date(2024, 3, 31)
    rng = np.random.default_rng(SEMILLA)
    real = vision_perfecta(precios_reales, fecha)
    # En 2024-04 IBIT cayó 17 %, VOOG 3.8 %, VB 6.5 % y BNS 9.9 %: la trampa elige VOOG.
    assert real["VOOG"] == 1.0
    nombres = []
    for nombre, panel in perturbaciones(precios_reales, fecha, rng):
        nombres.append(nombre)
        limite = pd.Timestamp(fecha)
        pd.testing.assert_frame_equal(
            panel.loc[panel.index <= limite], precios_reales.loc[precios_reales.index <= limite]
        )
        alterado = vision_perfecta(panel, fecha)
        assert alterado != real, nombre
        if nombre == "futuro_invertido":
            # Con los retornos futuros invertidos el peor activo (IBIT) pasa a ser el mejor.
            assert alterado["IBIT"] == 1.0
            assert panel.loc[pd.Timestamp("2024-04-30"), "IBIT"] == pytest.approx(40.47**2 / 33.57)
        if nombre == "futuro_aleatorio":
            assert panel.isna().equals(precios_reales.isna())
            assert (panel.loc[panel.index > limite] > 0).all().all()
    assert tuple(nombres) == PERTURBACIONES


def test_trampa_sutil_invariante_al_signo_tambien_es_detectada(
    precios_reales: pd.DataFrame,
) -> None:
    fechas = [d.date() for d in precios_reales.index[:-1]]
    with pytest.raises(LookAheadDetectadoError) as info:
        verificar_look_ahead(
            volatilidad_inversa_muestra_completa, precios_reales, fechas, semilla=SEMILLA
        )
    assert info.value.perturbacion in {"sin_futuro", "futuro_aleatorio"}
    assert info.value.pesos_perturbados is not None
    assert info.value.pesos_perturbados != info.value.pesos_reales


def test_estrategia_que_falla_sin_el_futuro_es_detectada(precios_reales: pd.DataFrame) -> None:
    def indexa_el_mes_siguiente(precios: pd.DataFrame, fecha: date) -> Mapping[str, float]:
        siguiente = precios.index[precios.index.get_loc(pd.Timestamp(fecha)) + 1]
        return {"VOOG": float(precios.loc[siguiente, "VOOG"] > 0)}

    with pytest.raises(LookAheadDetectadoError, match="falla sin el futuro real"):
        verificar_look_ahead(
            indexa_el_mes_siguiente,
            precios_reales,
            [FECHA - pd.Timedelta(days=30)],
            semilla=SEMILLA,
        )


def test_las_estrategias_honestas_pasan(
    config: Config, provider: CSVPriceProvider, precios_reales: pd.DataFrame
) -> None:
    fechas = [d.date() for d in precios_reales.index[:-1]]
    verificar_look_ahead(pesos_fijos(PESOS_REFERENCIA), precios_reales, fechas, semilla=SEMILLA)

    restricciones = PortfolioConstraints(
        activos=ACTIVOS,
        peso_min=config.optimizacion.peso_min,
        peso_max=config.optimizacion.peso_max,
    )

    def constructor(est: QuantEstimates):
        return optimizar_min_varianza(est, restricciones, config.optimizacion)

    min_var = reestimada(
        constructor,
        ventana_meses=config.datos.ventana_covarianza_meses,
        metodos=(MetodoCovarianza.HISTORICA,),
        nivel_confianza=config.estimacion.nivel_confianza,
        periodos_por_anio=provider.periodos_por_anio,
    )
    # Desde 2024-03 IBIT tiene ≥ 2 retornos y la re-estimación es posible cada mes.
    desde_2024 = [f for f in fechas if f >= date(2024, 3, 31)]
    verificar_look_ahead(min_var, precios_reales, desde_2024, semilla=SEMILLA)


def test_validar_rechaza_la_estrategia_tramposa_y_lo_dice(
    config: Config, provider: CSVPriceProvider, precios_reales: pd.DataFrame
) -> None:
    reporte = validar(
        candidato("tramposa", PESOS_REFERENCIA),
        precios_reales,
        fecha_decision=FECHA,
        iteracion=1,
        validacion=config.validacion,
        optimizacion=config.optimizacion,
        periodos_por_anio=provider.periodos_por_anio,
        semilla=config.reproducibilidad.semilla,
        estrategia=vision_perfecta,
    )
    assert reporte.veredicto.value == "RECHAZADA"
    assert reporte.look_ahead_verificado is False
    assert "look-ahead no verificado" in reporte.razones_rechazo
    assert any("look-ahead detectado en 2021-09-30" in s for s in reporte.sugerencias)
    # La visión perfecta "gana" en el backtest: por eso el veto no puede depender de las métricas.
    assert reporte.metricas_oos.sharpe_oos > config.validacion.sharpe_oos_minimo


def test_validar_no_acepta_precios_posteriores_a_la_decision(
    config: Config, provider: CSVPriceProvider, precios_reales: pd.DataFrame
) -> None:
    with pytest.raises(LookAheadError, match="posteriores a la fecha de decisión"):
        validar(
            candidato("bl", PESOS_REFERENCIA),
            precios_reales,
            fecha_decision=date(2026, 8, 31),
            iteracion=1,
            validacion=config.validacion,
            optimizacion=config.optimizacion,
            periodos_por_anio=provider.periodos_por_anio,
            semilla=config.reproducibilidad.semilla,
        )
