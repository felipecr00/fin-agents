from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from investmentsys.contracts import (
    Criterio,
    MetricasOOS,
    ResultadoStress,
    ValidationReport,
    Veredicto,
)


def test_round_trip_json(validacion_aprobada: ValidationReport) -> None:
    assert (
        ValidationReport.model_validate_json(validacion_aprobada.model_dump_json())
        == validacion_aprobada
    )
    assert validacion_aprobada.razones_rechazo == ()


def _con(v: ValidationReport, **cambios: object) -> ValidationReport:
    return ValidationReport(**{**v.model_dump(), **cambios})


def test_aprobada_con_criterio_incumplido_es_incoherente(
    validacion_aprobada: ValidationReport,
) -> None:
    fallido = Criterio(nombre="sharpe_oos_minimo", valor=0.1, umbral=0.2, cumple=False)
    with pytest.raises(ValidationError, match="APROBADA es incompatible"):
        _con(validacion_aprobada, criterios=(fallido,))


def test_aprobada_sin_verificar_look_ahead_es_incoherente(
    validacion_aprobada: ValidationReport,
) -> None:
    with pytest.raises(ValidationError, match="look-ahead"):
        _con(validacion_aprobada, look_ahead_verificado=False)


def test_rechazada_sin_razon_es_incoherente(validacion_aprobada: ValidationReport) -> None:
    with pytest.raises(ValidationError, match="falta la razón"):
        _con(validacion_aprobada, veredicto=Veredicto.RECHAZADA)


def test_rechazada_lista_sus_razones(validacion_aprobada: ValidationReport) -> None:
    fallido = Criterio(nombre="max_drawdown_tolerado", valor=0.41, umbral=0.35, cumple=False)
    stress = ResultadoStress(
        escenario="cripto_2025_26",
        fecha_inicio=date(2025, 10, 31),
        fecha_fin=date(2026, 6, 30),
        retorno_periodo=-0.30,
        max_drawdown=0.41,
        superado=False,
    )
    r = _con(
        validacion_aprobada,
        criterios=(fallido,),
        stress=(stress,),
        veredicto=Veredicto.RECHAZADA,
        sugerencias=("reducir IBIT",),
    )
    assert r.razones_rechazo == (
        "max_drawdown_tolerado: 0.4100 vs umbral 0.35",
        "stress cripto_2025_26: drawdown 41.00%",
    )


def test_backtest_posterior_a_la_decision_es_look_ahead(
    validacion_aprobada: ValidationReport, metricas_oos: MetricasOOS
) -> None:
    tarde = MetricasOOS(**{**metricas_oos.model_dump(), "fecha_fin": date(2026, 12, 31)})
    with pytest.raises(ValidationError, match="look-ahead"):
        _con(validacion_aprobada, metricas_oos=tarde)


def test_drawdown_es_fraccion_positiva(metricas_oos: MetricasOOS) -> None:
    with pytest.raises(ValidationError):
        MetricasOOS(**{**metricas_oos.model_dump(), "max_drawdown": -0.2})
