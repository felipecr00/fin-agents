"""Reporter: redacta la narrativa del informe a partir de la hoja de hechos de ``RunState``."""

from __future__ import annotations

import json
from collections.abc import Callable

from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.base_llm import BaseLlm
from google.genai import types

from investmentsys.agents.modelo import resolver_modelo
from investmentsys.config import Config
from investmentsys.contracts import RunState

NOMBRE = "reporter"

INSTRUCCION = """\
Eres el redactor del informe final de un sistema de construcción de portafolios.
Escribe en español, en Markdown, entre 2 y 4 párrafos breves (sin títulos ni tablas: el
informe ya las incluye). Explica: qué opinó el analista, qué cartera se propuso, qué decidió
el validador y por qué, y —si hubo rechazo— qué cambió entre iteraciones.

Reglas estrictas:
- No calcules ni estimes nada. Las ÚNICAS cifras que puedes citar son las de la hoja de
  hechos, copiadas literalmente y sin comillas. Si dudas, describe sin números.
- No recomiendes comprar ni vender: es una herramienta de análisis, no asesoría.
- Si no hay cartera aprobada, dilo con claridad en la primera frase.

Hoja de hechos:
{hechos}
"""


def crear_reporter(
    config: Config,
    hechos: Callable[[ReadonlyContext], RunState],
    clave_salida: str,
    modelo: str | BaseLlm | None = None,
) -> LlmAgent:
    from investmentsys.agents.reporter.reporte import hoja_de_hechos

    def instruccion(contexto: ReadonlyContext) -> str:
        hoja = hoja_de_hechos(hechos(contexto))
        return INSTRUCCION.format(hechos=json.dumps(hoja, ensure_ascii=False, indent=2))

    return LlmAgent(
        name=NOMBRE,
        description="Redacta la narrativa del informe final desde RunState.",
        model=resolver_modelo(config.agentes, modelo),
        instruction=instruccion,
        output_key=clave_salida,
        generate_content_config=types.GenerateContentConfig(
            temperature=config.agentes.temperatura,
            seed=config.reproducibilidad.semilla,
        ),
    )
