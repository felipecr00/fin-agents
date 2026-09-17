from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from investmentsys.contracts import (
    MatrizCovarianza,
    MetodoCovarianza,
    QuantEstimates,
    RegimenMercado,
)


def test_round_trip_json(estimates: QuantEstimates) -> None:
    assert QuantEstimates.model_validate_json(estimates.model_dump_json()) == estimates
    assert estimates.regimen is RegimenMercado.INDETERMINADO


def test_volatilidad_desde_varianza(matriz_covarianza: MatrizCovarianza) -> None:
    assert matriz_covarianza.volatilidad("IBIT") == pytest.approx(0.2611**0.5)
    assert matriz_covarianza.observaciones_por_activo["IBIT"] < matriz_covarianza.ventana_meses


def test_matriz_no_cuadrada(activos: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError, match="4×4"):
        MatrizCovarianza(
            metodo=MetodoCovarianza.HISTORICA,
            activos=activos,
            valores=((1.0, 0.0), (0.0, 1.0)),
            ventana_meses=60,
            observaciones_por_activo=dict.fromkeys(activos, 60),
        )


def test_matriz_no_simetrica(activos: tuple[str, ...]) -> None:
    filas = [[0.0] * 4 for _ in range(4)]
    for i in range(4):
        filas[i][i] = 0.04
    filas[0][1] = 0.01
    with pytest.raises(ValidationError, match="no simétrica"):
        MatrizCovarianza(
            metodo=MetodoCovarianza.HISTORICA,
            activos=activos,
            valores=tuple(tuple(f) for f in filas),
            ventana_meses=60,
            observaciones_por_activo=dict.fromkeys(activos, 60),
        )


def test_observaciones_exceden_ventana(activos: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError, match="fuera de"):
        MatrizCovarianza(
            metodo=MetodoCovarianza.HISTORICA,
            activos=activos,
            valores=tuple(tuple(0.04 if i == j else 0.0 for j in range(4)) for i in range(4)),
            ventana_meses=60,
            observaciones_por_activo={**dict.fromkeys(activos, 60), "IBIT": 61},
        )


def test_muestra_posterior_a_la_decision_es_look_ahead(estimates: QuantEstimates) -> None:
    with pytest.raises(ValidationError, match="look-ahead"):
        QuantEstimates(**{**estimates.model_dump(), "fecha_fin_muestra": date(2026, 10, 31)})


def test_metodo_de_la_clave_debe_coincidir(
    estimates: QuantEstimates, matriz_covarianza: MatrizCovarianza
) -> None:
    with pytest.raises(ValidationError, match="registrada como"):
        QuantEstimates(
            **{
                **estimates.model_dump(),
                "covarianzas": {MetodoCovarianza.LEDOIT_WOLF: matriz_covarianza},
            }
        )


def test_retornos_en_orden_canonico(estimates: QuantEstimates) -> None:
    invertidos = tuple(reversed(estimates.retornos_historicos))
    with pytest.raises(ValidationError, match="orden canónico"):
        QuantEstimates(**{**estimates.model_dump(), "retornos_historicos": invertidos})
