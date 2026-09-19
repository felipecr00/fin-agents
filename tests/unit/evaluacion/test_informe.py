"""Del resultado que ``adk eval`` deja en disco al resumen por caso de ``make eval``."""

from __future__ import annotations

from pathlib import Path

import pytest
from google.adk.evaluation.eval_case import Invocation
from google.adk.evaluation.eval_metrics import (
    EvalMetricResult,
    EvalMetricResultDetails,
    EvalMetricResultPerInvocation,
)
from google.adk.evaluation.eval_result import EvalCaseResult, EvalSetResult
from google.adk.evaluation.eval_rubrics import RubricScore
from google.adk.evaluation.evaluator import EvalStatus
from google.genai import types

from investmentsys.evaluacion.informe import (
    CARPETA_HISTORIAL,
    a_markdown,
    casos_evaluados,
    leer_resultado,
    ultimo_resultado,
)


def _caso(eval_id: str, criterios: dict[str, bool]) -> EvalCaseResult:
    aprobado = all(criterios.values())
    estado = EvalStatus.PASSED if aprobado else EvalStatus.FAILED
    metrica = EvalMetricResult(
        metric_name="views_cumplen_criterios",
        threshold=1.0,
        score=sum(criterios.values()) / len(criterios),
        eval_status=estado,
        details=EvalMetricResultDetails(
            rubric_scores=[
                RubricScore(rubric_id=c, rationale=f"detalle de {c}", score=float(ok))
                for c, ok in criterios.items()
            ]
        ),
    )
    usuario = types.Content(role="user", parts=[types.Part(text="noticias")])
    return EvalCaseResult(
        eval_id=eval_id,
        final_eval_status=estado,
        overall_eval_metric_results=[metrica],
        eval_metric_result_per_invocation=[
            EvalMetricResultPerInvocation(
                actual_invocation=Invocation(user_content=usuario), eval_metric_results=[metrica]
            )
        ],
        session_id="s",
    )


@pytest.fixture
def carpeta_app(tmp_path: Path) -> Path:
    resultado = EvalSetResult(
        eval_set_result_id="resultado_1",
        eval_set_id="market_analyst_noticias",
        eval_case_results=[
            _caso("alcista", {"contrato": True, "direccion:BNS": True}),
            _caso("ambigua", {"contrato": True, "sin_conviccion:BNS": False}),
        ],
    )
    historial = tmp_path / CARPETA_HISTORIAL
    historial.mkdir(parents=True)
    (historial / "resultado_1.evalset_result.json").write_text(resultado.model_dump_json())
    return tmp_path


def test_resumen_por_caso_con_los_criterios_incumplidos(carpeta_app: Path) -> None:
    casos = casos_evaluados(leer_resultado(ultimo_resultado(carpeta_app)))
    assert [(c.eval_id, c.aprobado, c.nota) for c in casos] == [
        ("alcista", True, 1.0),
        ("ambigua", False, 0.5),
    ]
    assert [i.criterio for i in casos[1].incumplidos] == ["sin_conviccion:BNS"]
    informe = a_markdown(casos, "Evals")
    assert "**1/2 casos aprobados.**" in informe
    assert "- `sin_conviccion:BNS`: detalle de sin_conviccion:BNS" in informe


def test_sin_resultados_en_disco(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="sin resultados"):
        ultimo_resultado(tmp_path)
