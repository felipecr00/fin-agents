"""Constructor de Portafolios: decide QUÉ pedir a la herramienta; los pesos los calcula ella."""

from __future__ import annotations

import json

from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.base_llm import BaseLlm
from google.adk.tools.function_tool import FunctionTool
from google.genai import types

from investmentsys.config import Config
from investmentsys.tools import CLAVE_CANDIDATOS, CLAVE_VALIDACIONES, NucleoTools

NOMBRE = "constructor"

INSTRUCCION = """\
Eres el Constructor de Portafolios. No calculas pesos: llamas UNA vez a la herramienta
`construir_candidatos`, que optimiza Black-Litterman (con las views del analista), HRP y
mínima varianza, y luego resumes en dos o tres frases qué pediste y por qué, citando solo
cifras devueltas por la herramienta.

Iteración {iteracion} de {maximo}. Límites de config.yaml: cada peso en [{peso_min}, {peso_max}].
{situacion}
"""

PRIMERA = """\
Es la primera propuesta: recomienda "black_litterman" con los límites de config.yaml (no
pases `peso_max_por_activo`), salvo que el usuario haya pedido otra cosa."""

TRAS_RECHAZO = """\
El validador RECHAZÓ la propuesta anterior ("{recomendado}", pesos {pesos}).
Razones: {razones}
Sugerencias del validador: {sugerencias}
Decide el cambio mínimo que atienda esas razones: endurecer `peso_max_por_activo` del activo
señalado (solo puedes bajar máximos, nunca subirlos) y/o recomendar otra técnica ("hrp",
"min_varianza"). No repitas la misma petición."""


def _situacion(contexto: ReadonlyContext) -> tuple[int, str]:
    rondas = contexto.state.get(CLAVE_CANDIDATOS) or []
    validaciones = contexto.state.get(CLAVE_VALIDACIONES) or []
    if not validaciones:
        return 1, PRIMERA
    ultima, ronda = validaciones[-1], rondas[-1]
    razones = [c["nombre"] for c in ultima["criterios"] if not c["cumple"]]
    razones += [f"stress {s['escenario']}" for s in ultima["stress"] if not s["superado"]]
    return len(rondas) + 1, TRAS_RECHAZO.format(
        recomendado=ronda["recomendado"],
        pesos=json.dumps(ultima["pesos_evaluados"]),
        razones="; ".join(razones) or "look-ahead detectado",
        sugerencias="; ".join(ultima["sugerencias"]),
    )


def crear_constructor(
    config: Config, tools: NucleoTools, modelo: str | BaseLlm | None = None
) -> LlmAgent:
    def instruccion(contexto: ReadonlyContext) -> str:
        iteracion, situacion = _situacion(contexto)
        return INSTRUCCION.format(
            iteracion=iteracion,
            maximo=config.validacion.max_iteraciones_constructor,
            peso_min=config.optimizacion.peso_min,
            peso_max=config.optimizacion.peso_max,
            situacion=situacion,
        )

    return LlmAgent(
        name=NOMBRE,
        description="Decide técnica y límites; la herramienta calcula los candidatos.",
        model=modelo if modelo is not None else config.agentes.modelo,
        instruction=instruccion,
        tools=[FunctionTool(tools.construir_candidatos)],
        generate_content_config=types.GenerateContentConfig(
            temperature=config.agentes.temperatura,
            seed=config.reproducibilidad.semilla,
        ),
    )
