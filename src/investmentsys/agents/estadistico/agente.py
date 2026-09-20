"""El Estadístico (Quant Lead): persona thin sobre ``estimar_mercado`` (S10, ADR-019)."""

from __future__ import annotations

from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.tools.function_tool import FunctionTool
from pydantic import BaseModel, Field

from investmentsys.agents.persona import crear_persona
from investmentsys.config import Config
from investmentsys.tools import NucleoTools
from investmentsys.tools.exploratorio import correlaciones, exploratorio

NOMBRE = "estadistico"
DESCRIPCION = (
    "Estadístico (Quant Lead): volatilidades, retornos históricos con su intervalo de confianza "
    "y correlaciones por par del universo vigente. Responde él mismo al usuario, en su voz."
)

ROL = """\
Eres el Estadístico (Quant Lead) de un equipo de inversiones. Riguroso, empírico y reacio a los
supuestos no comprobados. Estimas volatilidades, retornos históricos y correlaciones del universo
vigente con tu herramienta `estimar_mercado`.

Tu sello
- Reportas SIEMPRE la confianza de tu estimación, no solo el número: el intervalo del retorno
  histórico con su nivel de confianza, cuántas observaciones usaste y sobre qué muestra. Un
  retorno histórico con un intervalo ancho es poca evidencia: dilo así.
- Si un activo tiene pocas observaciones o la muestra común es corta, adviértelo y di qué
  limita, y qué método de covarianza es más defendible en ese caso (con poca historia, una
  covarianza con encogimiento tipo Ledoit-Wolf es más estable que la histórica). Di con qué
  método se estimó (`metodo_covarianza`).
- Describes lo que muestra el dato y con cuánta incertidumbre. POR QUÉ se movió una correlación
  o un retorno es una lectura de mercado: eso es del Analista, no tuyo, y lo dices.
- Un retorno histórico no es un pronóstico. No lo presentes como lo que el activo va a rendir.
"""


class ConsultaEstadistico(BaseModel):
    pregunta: str = Field(
        description="Lo que el usuario quiere saber, en sus palabras y citado. Sin cifras tuyas."
    )


def crear_estadistico(
    config: Config, nucleo: NucleoTools, modelo: str | BaseLlm | None = None
) -> LlmAgent:
    """``modelo`` permite inyectar un LLM falso en tests; por defecto, ``config.inferencia``."""
    tool = FunctionTool(exploratorio(nucleo.estimar_mercado, anexo=correlaciones))
    return crear_persona(
        nombre=NOMBRE,
        descripcion=DESCRIPCION,
        rol=ROL,
        tool=tool,
        consulta=ConsultaEstadistico,
        config=config,
        modelo=modelo,
    )
