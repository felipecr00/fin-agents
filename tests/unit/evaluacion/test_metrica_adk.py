"""La métrica de ``adk eval``: de los eventos de una corrida a la nota del caso."""

from __future__ import annotations

import json
from typing import Any

import pytest
from google.adk.evaluation.eval_case import Invocation, InvocationEvent, InvocationEvents
from google.adk.evaluation.eval_config import EvalConfig, get_eval_metrics_from_config
from google.adk.evaluation.eval_metrics import EvalMetric
from google.adk.evaluation.evaluator import EvalStatus
from google.genai import types

from investmentsys.evaluacion.metrica_adk import AUTOR_LLM, views_cumplen_criterios
from tests.conftest import FECHA

CONFIG_EVAL = "tests/eval/test_config.json"


def _contenido(texto: str, rol: str = "model") -> types.Content:
    return types.Content(role=rol, parts=[types.Part(text=texto)])


def _borrador(*views: dict[str, Any]) -> str:
    return json.dumps({"resumen": "Lectura de prueba.", "views": list(views)})


def _view(activo: str, q: float, confianza: float = 0.4) -> dict[str, Any]:
    return {
        "tipo": "absoluta",
        "coeficientes": [{"activo": activo, "coeficiente": 1.0}],
        "q_anual": q,
        "confianza": confianza,
        "justificacion": "Razonamiento de prueba.",
        "fuente": "prueba",
        "fecha_fuente": None,
    }


def _real(*salidas_llm: str) -> Invocation:
    eventos = [InvocationEvent(author="market_analyst", content=_contenido("Analizando…"))]
    eventos += [InvocationEvent(author=AUTOR_LLM, content=_contenido(s)) for s in salidas_llm]
    return Invocation(
        user_content=_contenido("noticias", "user"),
        final_response=_contenido("MarketViews válido…"),
        intermediate_data=InvocationEvents(invocation_events=eventos),
    )


def _esperada(**criterios: Any) -> Invocation:
    cuerpo = json.dumps({"fecha_decision": FECHA.isoformat(), **criterios})
    return Invocation(
        user_content=_contenido("noticias", "user"), final_response=_contenido(cuerpo)
    )


@pytest.fixture
def metrica() -> EvalMetric:
    """La métrica tal como ``adk eval`` la construye desde ``tests/eval/test_config.json``."""
    with open(CONFIG_EVAL, encoding="utf-8") as f:
        (metrica,) = get_eval_metrics_from_config(EvalConfig.model_validate_json(f.read()))
    return metrica


def test_caso_que_cumple_todo(metrica: EvalMetric) -> None:
    resultado = views_cumplen_criterios(
        metrica,
        [_real(_borrador(_view("IBIT", -0.10)))],
        [_esperada(direccion={"IBIT": "bajista"})],
    )
    assert resultado.overall_score == 1.0
    assert resultado.overall_eval_status is EvalStatus.PASSED
    (invocacion,) = resultado.per_invocation_results
    assert invocacion.rubric_scores is not None
    assert [r.rubric_id for r in invocacion.rubric_scores] == [
        "contrato",
        "fecha_decision",
        "q_plausible",
        "numero_de_views",
        "direccion:IBIT",
    ]


def test_un_criterio_incumplido_baja_la_nota_y_reprueba(metrica: EvalMetric) -> None:
    resultado = views_cumplen_criterios(
        metrica,
        [_real(_borrador(_view("IBIT", 0.85, 1.0)))],
        [_esperada(direccion={"IBIT": "bajista"})],
    )
    assert resultado.overall_score == pytest.approx(3 / 5)
    assert resultado.overall_eval_status is EvalStatus.FAILED
    (invocacion,) = resultado.per_invocation_results
    assert invocacion.rubric_scores is not None
    fallidos = {r.rubric_id for r in invocacion.rubric_scores if not r.score}
    assert fallidos == {"q_plausible", "direccion:IBIT"}


def test_se_evalua_el_ultimo_intento_del_llm(metrica: EvalMetric) -> None:
    real = _real("esto no es JSON", _borrador(_view("BNS", 0.08)))
    resultado = views_cumplen_criterios(metrica, [real], [_esperada(direccion={"BNS": "alcista"})])
    assert resultado.overall_eval_status is EvalStatus.PASSED
    (invocacion,) = resultado.per_invocation_results
    assert invocacion.rubric_scores is not None
    assert "intento 2" in (invocacion.rubric_scores[0].rationale or "")


@pytest.mark.parametrize(
    "salidas",
    [
        (),
        ("esto no es JSON",),
        (_borrador(_view("TSLA", 0.10)),),  # fuera del universo: no valida contra el contrato
    ],
)
def test_sin_market_views_valido_la_nota_es_cero(metrica: EvalMetric, salidas: tuple[str]) -> None:
    resultado = views_cumplen_criterios(metrica, [_real(*salidas)], [_esperada()])
    assert resultado.overall_score == 0.0
    assert resultado.overall_eval_status is EvalStatus.FAILED


def test_sin_invocacion_esperada_es_un_error_del_evalset(metrica: EvalMetric) -> None:
    with pytest.raises(ValueError, match="invocación esperada"):
        views_cumplen_criterios(metrica, [_real(_borrador())], None)
