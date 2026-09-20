"""El Escéptico (Risk & Validation Lead): persona thin sobre ``diagnosticar_cartera`` (S10).

Fuera del comité diagnostica y nunca emite veredicto (ADR-014). Los pesos que trae el usuario
NO pasan por su LLM: el Director los entrega tipados (``ConsultaEsceptico.pesos``), un callback
del Director los deja en el estado y la herramienta los lee de ahí (ADR-019).
"""

from __future__ import annotations

from typing import Any

from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext
from pydantic import BaseModel, Field

from investmentsys.agents.persona import crear_persona
from investmentsys.config import Config
from investmentsys.tools import NucleoTools
from investmentsys.tools.estado import CLAVE_PESOS_EN_CONSULTA

NOMBRE = "esceptico"
DESCRIPCION = (
    "Escéptico (riesgo y validación), fuera del comité: diagnostica una cartera —la que trae el "
    "usuario o la que está sobre la mesa— buscando sus grietas: backtest fuera de muestra, "
    "stress, concentración. Nunca da un veredicto. Responde él mismo al usuario, en su voz."
)

ROL = """\
Eres el Escéptico (Risk & Validation Lead) de un equipo de inversiones: el adversario
institucional. Tu trabajo es encontrar las grietas de una cartera —riesgo de cola, concentración,
fragilidad ante un escenario de stress, historia insuficiente— con tu herramienta
`diagnosticar_cartera`. La herramienta no lleva argumentos: la cartera en consulta ya está en la
sesión (los pesos que dio el usuario o, si no dio, la cartera vigente sobre la mesa). El campo
`cartera_evaluada` de la salida dice cuál se midió: dilo al empezar.

Tu sello
- Buscas lo que puede salir mal antes que lo que salió bien: empieza por lo que más te preocupa
  y apóyalo en una cifra de la salida (caída máxima, un escenario de stress, la concentración,
  un umbral de referencia que no se cumple, una advertencia de historia corta).
- Fuera del comité NUNCA emites veredicto: no apruebas, no rechazas, no dices "pasa" ni "no
  pasa", no recomiendas comprar, vender ni cambiar pesos. Los umbrales del comité que trae la
  salida son solo una referencia: di si la medición queda dentro o fuera, y que eso aquí no
  aprueba ni rechaza nada. El veredicto solo existe dentro del comité formal.
- Si `advertencias` avisa que la historia de un activo no alcanza para que el backtest o un
  stress signifiquen algo, dilo de entrada: un stress que no cubre a un activo no lo exculpa.
- Un Sharpe o un retorno fuera de muestra buenos no te tranquilizan: di qué parte de la muestra
  los sostiene y qué no se ha visto todavía.
"""


class ConsultaEsceptico(BaseModel):
    pregunta: str = Field(
        description="Lo que el usuario quiere saber, en sus palabras y citado. Sin cifras tuyas."
    )
    pesos: dict[str, float] | None = Field(
        default=None,
        description=(
            "Solo si el usuario TRAE una cartera: sus pesos como fracciones, tal como los dio "
            '(p. ej. {"VOOG": 0.5, "BNS": 0.5}); no los completes ni los renormalices. Omítelo '
            "para diagnosticar la cartera que está sobre la mesa."
        ),
    )


def entregar_pesos(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
) -> dict[str, Any] | None:
    """``before_tool_callback`` del DIRECTOR: los pesos van al estado, no al LLM de la persona.

    Se escribe en cada consulta (también ``None``): unos pesos de una consulta anterior no
    pueden colarse en esta.
    """
    if tool.name == NOMBRE:
        tool_context.state[CLAVE_PESOS_EN_CONSULTA] = args.get("pesos") or None
    return None


def crear_esceptico(
    config: Config, nucleo: NucleoTools, modelo: str | BaseLlm | None = None
) -> LlmAgent:
    """``modelo`` permite inyectar un LLM falso en tests; por defecto, ``config.inferencia``."""
    return crear_persona(
        nombre=NOMBRE,
        descripcion=DESCRIPCION,
        rol=ROL,
        tool=FunctionTool(nucleo.diagnosticar_cartera),
        consulta=ConsultaEsceptico,
        config=config,
        modelo=modelo,
    )
