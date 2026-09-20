"""El Escéptico (Risk & Validation Lead): persona thin sobre ``diagnosticar_cartera`` (S10).

Fuera del comité diagnostica y nunca emite veredicto (ADR-014). Los pesos que trae el usuario
NO pasan por su LLM: el Director los entrega tipados (``ConsultaEsceptico.pesos``), un callback
del Director los deja en el estado y la herramienta los lee de ahí (ADR-019).
"""

from __future__ import annotations

import re
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
from investmentsys.tools.estado import CLAVE_PESOS_EN_CONSULTA, FaltaEnEstadoError
from investmentsys.tools.objetivo import cartera_objetivo

TOLERANCIA_PESOS = 1e-6  # punto flotante al serializar argumentos; no es un parámetro

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


PESOS_SIN_PROCEDENCIA = (
    "los pesos que recibió el Escéptico no son los que escribió el usuario ni los de la cartera "
    "que está sobre la mesa: no se diagnosticó nada. Si el usuario trae una cartera, pídele que "
    "escriba sus pesos en números y pásalos tal cual; si pregunta por la cartera de la mesa, "
    "consulta al Escéptico SIN `pesos`"
)
_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")
_DECIMALES = 6


def _numeros_del_usuario(tool_context: ToolContext) -> set[float]:
    """Todo número que el usuario escribió en la sesión (y en el mensaje de este turno)."""
    contenidos = [e.content for e in tool_context.session.events if e.author == "user"]
    textos = [
        parte.text
        for contenido in (*contenidos, tool_context.user_content)
        for parte in ((contenido.parts or []) if contenido else [])
        if parte.text
    ]
    return {
        round(float(n.replace(",", ".")), _DECIMALES) for t in textos for n in _NUMERO.findall(t)
    }


def _los_dijo_el_usuario(pesos: dict[str, float], dichos: set[float]) -> bool:
    if not all(isinstance(w, int | float) and not isinstance(w, bool) for w in pesos.values()):
        return False
    return all(
        round(w, _DECIMALES) in dichos or round(w * 100.0, _DECIMALES) in dichos
        for w in pesos.values()
        if w
    )


def _son_los_de_la_mesa(pesos: dict[str, float], tool_context: ToolContext) -> bool:
    try:
        mesa = cartera_objetivo(tool_context.state).pesos
    except (FaltaEnEstadoError, ValueError):
        return False
    if not all(isinstance(w, int | float) and not isinstance(w, bool) for w in pesos.values()):
        return False
    activos = set(pesos) | set(mesa)
    return all(
        abs(float(pesos.get(a, 0.0)) - mesa.get(a, 0.0)) <= TOLERANCIA_PESOS for a in activos
    )


def entregar_pesos(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
) -> dict[str, Any] | None:
    """``before_tool_callback`` del DIRECTOR: los pesos van al estado, no al LLM de la persona.

    Custodia de procedencia (visto con el modelo real: el Director copió los pesos de la mesa y
    se los pasó al Escéptico como si fueran del usuario). Solo valen como "pesos del usuario"
    los números que el usuario ESCRIBIÓ; si son los de la cartera de la mesa, se descartan y el
    Escéptico mide la de la mesa con su procedencia real; cualquier otra cosa se rechaza sin
    consultar a la persona. Se escribe en cada consulta (también ``None``): unos pesos de una
    consulta anterior no pueden colarse en esta.
    """
    if tool.name != NOMBRE:
        return None
    pesos = args.get("pesos") or None
    if pesos is not None and not _los_dijo_el_usuario(pesos, _numeros_del_usuario(tool_context)):
        if not _son_los_de_la_mesa(pesos, tool_context):
            tool_context.state[CLAVE_PESOS_EN_CONSULTA] = None
            return {
                "status": "rechazado",
                "tipo": "PesosSinProcedencia",
                "motivo": PESOS_SIN_PROCEDENCIA,
            }
        pesos = None  # son los de la mesa: que consten con SU procedencia, no como del usuario
    tool_context.state[CLAVE_PESOS_EN_CONSULTA] = pesos
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
