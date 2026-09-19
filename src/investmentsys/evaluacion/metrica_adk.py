"""Métrica personalizada de ``adk eval`` para el Analista de Mercados (ADR-010).

``adk eval`` la localiza por su ruta (``tests/eval/test_config.json`` → ``custom_metrics``) y la
llama una vez por caso. De la corrida real toma la última salida del LLM del analista, la
convierte al contrato ``MarketViews`` con el mismo código que usa el agente y le aplica los
criterios del caso, que viajan como JSON en el ``final_response`` esperado del evalset.

La nota de un caso es la fracción de criterios cumplidos; cada criterio queda en el resultado
como un ``RubricScore`` con su explicación. Sin ``MarketViews`` válido la nota es 0.
"""

from __future__ import annotations

from google.adk.evaluation.eval_case import ConversationScenario, Invocation, InvocationEvents
from google.adk.evaluation.eval_metrics import EvalMetric
from google.adk.evaluation.eval_rubrics import RubricScore
from google.adk.evaluation.evaluator import EvalStatus, EvaluationResult, PerInvocationResult
from google.genai import types

from investmentsys.agents.market_analyst import MarketViewsBorrador
from investmentsys.agents.market_analyst.agente import NOMBRE
from investmentsys.config import Config, cargar_config
from investmentsys.contracts import MarketViews
from investmentsys.evaluacion.criterios import CriteriosCaso, ResultadoCriterio, evaluar_views

AUTOR_LLM = f"{NOMBRE}_llm"
CRITERIO_CONTRATO = "contrato"


def _texto(contenido: types.Content | None) -> str:
    partes = contenido.parts if contenido and contenido.parts else []
    return "".join(p.text for p in partes if p.text)


def salidas_del_llm(invocacion: Invocation) -> list[str]:
    """Textos que emitió el LLM del analista, en orden (uno por intento)."""
    datos = invocacion.intermediate_data
    if not isinstance(datos, InvocationEvents):
        return []
    textos = [_texto(e.content) for e in datos.invocation_events if e.author == AUTOR_LLM]
    return [t for t in textos if t]


def evaluar_invocacion(
    real: Invocation, esperada: Invocation, config: Config
) -> list[ResultadoCriterio]:
    criterios = CriteriosCaso.model_validate_json(_texto(esperada.final_response))
    salidas = salidas_del_llm(real)
    if not salidas:
        return [
            ResultadoCriterio(
                criterio=CRITERIO_CONTRATO, cumple=False, detalle="el LLM del analista no respondió"
            )
        ]
    try:
        views: MarketViews = MarketViewsBorrador.model_validate_json(salidas[-1]).a_contrato(
            criterios.fecha_decision,
            config.portafolio.activos,
            config.agentes.horizonte_views_meses,
        )
    except ValueError as exc:  # ValidationError incluido
        return [
            ResultadoCriterio(
                criterio=CRITERIO_CONTRATO,
                cumple=False,
                detalle=f"la última salida ({len(salidas)} intentos) no valida: {exc}",
            )
        ]
    contrato = ResultadoCriterio(
        criterio=CRITERIO_CONTRATO,
        cumple=True,
        detalle=f"MarketViews válido en el intento {len(salidas)}",
    )
    return [
        contrato,
        *evaluar_views(views, criterios, config),
    ]


def views_cumplen_criterios(
    eval_metric: EvalMetric,
    actual_invocations: list[Invocation],
    expected_invocations: list[Invocation] | None,
    conversation_scenario: ConversationScenario | None = None,
) -> EvaluationResult:
    """Punto de entrada que declara ``test_config.json`` (firma fijada por ADK)."""
    if not expected_invocations or len(expected_invocations) != len(actual_invocations):
        raise ValueError("cada invocación del caso necesita su invocación esperada con criterios")
    if eval_metric.criterion is None:
        raise ValueError(f"{eval_metric.metric_name}: falta el umbral en test_config.json")
    umbral = eval_metric.criterion.threshold
    config = cargar_config()
    por_invocacion = []
    for real, esperada in zip(actual_invocations, expected_invocations, strict=True):
        resultados = evaluar_invocacion(real, esperada, config)
        nota = sum(r.cumple for r in resultados) / len(resultados)
        if not resultados[0].cumple:
            nota = 0.0
        por_invocacion.append(
            PerInvocationResult(
                actual_invocation=real,
                expected_invocation=esperada,
                score=nota,
                eval_status=EvalStatus.PASSED if nota >= umbral else EvalStatus.FAILED,
                rubric_scores=[
                    RubricScore(rubric_id=r.criterio, rationale=r.detalle, score=float(r.cumple))
                    for r in resultados
                ],
            )
        )
    global_ = sum(p.score or 0.0 for p in por_invocacion) / len(por_invocacion)
    return EvaluationResult(
        overall_score=global_,
        overall_eval_status=EvalStatus.PASSED if global_ >= umbral else EvalStatus.FAILED,
        per_invocation_results=por_invocacion,
    )
