"""Genera el evalset de ADK a partir de los casos legibles en YAML (ADR-010).

Los criterios de cada caso viajan como JSON en el ``final_response`` esperado, que es lo que la
métrica personalizada recibe de ``adk eval``; la fecha de decisión va además al estado inicial
de la sesión, de donde la lee el analista.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from google.adk.evaluation.eval_case import EvalCase, Invocation, SessionInput
from google.adk.evaluation.eval_set import EvalSet
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field, model_validator

from investmentsys.evaluacion.criterios import CriteriosCaso
from investmentsys.tools.estado import CLAVE_FECHA_DECISION

USUARIO = "eval"


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Caso(_Modelo):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    categoria: str = Field(min_length=1)
    noticias: str | None = Field(default=None, min_length=1)
    mensaje: str | None = Field(
        default=None, min_length=1, description="Mensaje literal del usuario, sin noticias."
    )
    criterios: dict[str, Any]

    @model_validator(mode="after")
    def _noticias_o_mensaje(self) -> Caso:
        if (self.noticias is None) == (self.mensaje is None):
            raise ValueError(f"{self.id}: define `noticias` o `mensaje`, no ambos")
        return self


class Casos(_Modelo):
    eval_set_id: str = Field(pattern=r"^[a-z0-9_]+$")
    nombre: str
    descripcion: str
    fecha_decision: date
    encabezado: str
    cierre: str
    casos: tuple[Caso, ...] = Field(min_length=1)

    def criterios(self, caso: Caso) -> CriteriosCaso:
        return CriteriosCaso.model_validate(
            {"fecha_decision": self.fecha_decision, **caso.criterios}
        )

    def mensaje(self, caso: Caso) -> str:
        if caso.noticias is None:
            return caso.mensaje or ""
        noticias = f"<noticias>\n{caso.noticias.strip()}\n</noticias>"
        return f"{self.encabezado}\n\n{noticias}\n\n{self.cierre}"


def cargar_casos(ruta: Path) -> Casos:
    with ruta.open(encoding="utf-8") as f:
        return Casos.model_validate(yaml.safe_load(f))


def construir_evalset(casos: Casos, app: str) -> EvalSet:
    ids = [c.id for c in casos.casos]
    if len(set(ids)) != len(ids):
        raise ValueError("ids de caso repetidos")
    return EvalSet(
        eval_set_id=casos.eval_set_id,
        name=casos.nombre,
        description=casos.descripcion,
        eval_cases=[
            EvalCase(
                eval_id=caso.id,
                conversation=[
                    Invocation(
                        invocation_id=caso.id,
                        user_content=types.Content(
                            role="user", parts=[types.Part(text=casos.mensaje(caso))]
                        ),
                        final_response=types.Content(
                            role="model",
                            parts=[
                                types.Part(
                                    text=casos.criterios(caso).model_dump_json(
                                        exclude_defaults=True
                                    )
                                )
                            ],
                        ),
                    )
                ],
                session_input=SessionInput(
                    app_name=app,
                    user_id=USUARIO,
                    state={CLAVE_FECHA_DECISION: casos.fecha_decision.isoformat()},
                ),
            )
            for caso in casos.casos
        ],
    )


def serializar(evalset: EvalSet) -> str:
    return evalset.model_dump_json(indent=2, exclude_none=True, exclude_defaults=True) + "\n"
