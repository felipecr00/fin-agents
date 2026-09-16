from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from investmentsys.contracts import MarketViews, TipoView, View


def _view(**cambios: object) -> View:
    base: dict[str, object] = {
        "tipo": TipoView.ABSOLUTA,
        "coeficientes": {"IBIT": 1.0},
        "q_anual": 0.03,
        "confianza": 0.5,
        "justificacion": "justificación suficientemente larga",
        "fuente": "test",
    }
    return View(**{**base, **cambios})  # type: ignore[arg-type]


def test_matriz_p_y_q_del_ejercicio(views_golden: MarketViews) -> None:
    assert views_golden.matriz_p() == [
        [0.0, 0.0, 1.0, 0.0],
        [1.0, 0.0, 0.0, -1.0],
        [0.0, 1.0, 0.0, 0.0],
    ]
    assert views_golden.vector_q() == [0.03, 0.03, 0.10]
    assert views_golden.vector_confianza() == [0.5, 0.5, 0.5]


def test_sin_views_es_valido(activos: tuple[str, ...], fecha_decision: date) -> None:
    mv = MarketViews(
        fecha_decision=fecha_decision, activos=activos, horizonte_meses=12, resumen="neutral"
    )
    assert mv.matriz_p() == [] and mv.vector_q() == []


def test_round_trip_json(views_golden: MarketViews) -> None:
    assert MarketViews.model_validate_json(views_golden.model_dump_json()) == views_golden


def test_es_inmutable(views_golden: MarketViews) -> None:
    with pytest.raises(ValidationError):
        views_golden.horizonte_meses = 6  # type: ignore[misc]


@pytest.mark.parametrize(
    "cambios",
    [
        {"tipo": TipoView.ABSOLUTA, "coeficientes": {"IBIT": 0.5}},
        {"tipo": TipoView.ABSOLUTA, "coeficientes": {"IBIT": 1.0, "VB": 1.0}},
        {"tipo": TipoView.RELATIVA, "coeficientes": {"VOOG": 1.0}},
        {"tipo": TipoView.RELATIVA, "coeficientes": {"VOOG": 1.0, "VB": -0.5}},
        {"tipo": TipoView.RELATIVA, "coeficientes": {"VOOG": 1.0, "VB": 0.0, "BNS": -1.0}},
        {"confianza": 0.0},
        {"confianza": 1.5},
        {"q_anual": float("nan")},
        {"justificacion": "corta"},
        {"coeficientes": {"ibit": 1.0}},
    ],
)
def test_views_invalidas(cambios: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _view(**cambios)


def test_view_fuera_del_universo(activos: tuple[str, ...], fecha_decision: date) -> None:
    with pytest.raises(ValidationError, match="fuera del universo"):
        MarketViews(
            fecha_decision=fecha_decision,
            activos=activos,
            horizonte_meses=12,
            resumen="x",
            views=(_view(coeficientes={"AAPL": 1.0}),),
        )


def test_fuente_posterior_a_la_decision_es_look_ahead(
    activos: tuple[str, ...], fecha_decision: date
) -> None:
    with pytest.raises(ValidationError, match="look-ahead"):
        MarketViews(
            fecha_decision=fecha_decision,
            activos=activos,
            horizonte_meses=12,
            resumen="x",
            views=(_view(fecha_fuente=date(2026, 10, 1)),),
        )


def test_campo_desconocido_es_error(activos: tuple[str, ...], fecha_decision: date) -> None:
    with pytest.raises(ValidationError):
        MarketViews(
            fecha_decision=fecha_decision,
            activos=activos,
            horizonte_meses=12,
            resumen="x",
            regimen="alcista",  # type: ignore[call-arg]
        )
