"""Resumen legible del último resultado que ``adk eval`` dejó en disco (ADR-010).

``adk eval`` imprime una tabla muy ancha y siempre termina con código 0. Este módulo lee el
``*.evalset_result.json`` que escribe en ``<app>/.adk/eval_history`` y lo reduce a una fila por
caso, con el detalle de cada criterio incumplido.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.adk.evaluation.eval_result import EvalSetResult
from google.adk.evaluation.evaluator import EvalStatus

CARPETA_HISTORIAL = Path(".adk") / "eval_history"


@dataclass(frozen=True)
class CriterioEvaluado:
    criterio: str
    cumple: bool
    detalle: str


@dataclass(frozen=True)
class CasoEvaluado:
    eval_id: str
    aprobado: bool
    nota: float | None
    criterios: tuple[CriterioEvaluado, ...]

    @property
    def incumplidos(self) -> tuple[CriterioEvaluado, ...]:
        return tuple(c for c in self.criterios if not c.cumple)


def ultimo_resultado(carpeta_app: Path) -> Path:
    archivos = sorted(
        (carpeta_app / CARPETA_HISTORIAL).glob("*.evalset_result.json"),
        key=lambda p: p.stat().st_mtime,
    )
    if not archivos:
        raise FileNotFoundError(f"sin resultados de adk eval en {carpeta_app / CARPETA_HISTORIAL}")
    return archivos[-1]


def leer_resultado(ruta: Path) -> EvalSetResult:
    crudo: Any = json.loads(ruta.read_text(encoding="utf-8"))
    if isinstance(crudo, str):  # versiones anteriores de ADK guardaban un string JSON anidado
        crudo = json.loads(crudo)
    return EvalSetResult.model_validate(crudo)


def casos_evaluados(resultado: EvalSetResult) -> list[CasoEvaluado]:
    casos = []
    for caso in resultado.eval_case_results:
        criterios: list[CriterioEvaluado] = []
        notas: list[float] = []
        for por_invocacion in caso.eval_metric_result_per_invocation:
            for metrica in por_invocacion.eval_metric_results:
                if metrica.score is not None:
                    notas.append(metrica.score)
                rubricas = metrica.details.rubric_scores if metrica.details else None
                criterios.extend(
                    CriterioEvaluado(r.rubric_id, bool(r.score), r.rationale or "")
                    for r in rubricas or []
                )
        casos.append(
            CasoEvaluado(
                eval_id=caso.eval_id,
                aprobado=caso.final_eval_status == EvalStatus.PASSED,
                nota=min(notas) if notas else None,
                criterios=tuple(criterios),
            )
        )
    return casos


def a_markdown(casos: list[CasoEvaluado], titulo: str) -> str:
    aprobados = sum(c.aprobado for c in casos)
    lineas = [
        f"# {titulo}",
        "",
        f"**{aprobados}/{len(casos)} casos aprobados.**",
        "",
        "| Caso | Resultado | Nota | Criterios | Incumplidos |",
        "|---|---|---|---|---|",
    ]
    for c in casos:
        nota = "—" if c.nota is None else f"{c.nota:.2f}"
        estado = "✅" if c.aprobado else "❌"
        incumplidos = ", ".join(i.criterio for i in c.incumplidos) or "—"
        lineas.append(f"| {c.eval_id} | {estado} | {nota} | {len(c.criterios)} | {incumplidos} |")
    fallidos = [c for c in casos if not c.aprobado]
    if fallidos:
        lineas += ["", "## Detalle de los casos fallidos", ""]
    for c in fallidos:
        lineas.append(f"### {c.eval_id}")
        if not c.criterios:
            lineas.append("- Sin evaluación: el agente no completó la corrida (ver el log).")
        lineas += [f"- `{i.criterio}`: {i.detalle}" for i in c.incumplidos]
        lineas.append("")
    return "\n".join(lineas).rstrip() + "\n"
