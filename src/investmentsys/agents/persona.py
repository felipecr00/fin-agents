"""Personas thin (S10, ADR-019): un ``LlmAgent`` ``single_turn`` con voz propia y UNA tool.

Lo que una persona es, por construcción y no por prompt:
- habla ella: su respuesta es un evento propio que el usuario lee; el Director no la re-narra;
- una sola herramienta: sin ``transfer_to_agent`` (ADK se lo declara a todo sub-agente);
- la ficha de origen la recoge ella (``recoger_anexos``): el Director solo recibe su texto;
- no ve la conversación: solo su encargo tipado (``input_schema``) y el estado de la sesión.
"""

from __future__ import annotations

from typing import Any

from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.base_llm import BaseLlm
from google.adk.tools.function_tool import FunctionTool
from google.genai import types
from pydantic import BaseModel

from investmentsys.agents.anexos import recoger_anexos
from investmentsys.agents.modelo import resolver_modelo
from investmentsys.config import Config
from investmentsys.contracts import DISCLAIMER
from investmentsys.tools.estado import CLAVE_UNIVERSO

REGLAS_COMUNES = """\
Reglas de toda persona del equipo
- Hablas en primera persona y directamente al usuario: tu respuesta es la que él lee. El
  Director solo te pasó su pregunta; no te dirijas al Director ni hables de él.
- Tienes UNA herramienta: `{tool}`. Llámala SIEMPRE antes de responder, una sola vez. No
  respondes de memoria ni con cifras de una respuesta anterior.
- Toda cifra que digas debe aparecer, idéntica, en la salida de tu herramienta. Puedes
  redondearla al expresarla; no hagas aritmética propia (sumar, restar, promediar, anualizar,
  comparar con un número que no esté en la salida).
- Tu resultado es EXPLORATORIO: no pasó por el comité y no es una recomendación. Dilo.
- Si la herramienta responde `status` "error" o "rechazado": explica el motivo que trae y qué
  falta para poder responder. No reintentes ni rellenes con cifras.
- No tienes otras capacidades: no buscas noticias, no predices precios, no ejecutas órdenes y
  no construyes carteras. Si la pregunta pide eso, di que no es tu silla y responde solo lo tuyo.
- La ficha de origen de tu resultado se anexa sola al final del turno: no la escribas.
- Responde lo que se preguntó y nada más: como mucho unas 150 palabras, sin tablas. Di cada
  cifra UNA sola vez, redondeada al más cercano, sin truncar (0.28816 es 28.82 %, no 28.81 %;
  porcentajes con uno o dos decimales; si al redondear una medición queda igual a su umbral,
  da un decimal más para que se vea de qué lado está); nunca pegues al lado el
  valor crudo de la herramienta ni nombres de campos. Cierra con: "{disclaimer}"

Universo vigente de la sesión: {universo}
"""


def _universo(contexto: ReadonlyContext) -> str:
    universo = contexto.state.get(CLAVE_UNIVERSO)
    if not universo:
        return "no hay universo cargado."
    return ", ".join(d["ticker"] for d in universo["diagnosticos"]) + "."


def crear_persona(
    *,
    nombre: str,
    descripcion: str,
    rol: str,
    tool: FunctionTool,
    consulta: type[BaseModel],
    config: Config,
    modelo: str | BaseLlm | None = None,
) -> LlmAgent:
    """``descripcion`` es lo que el Director lee para decidir a quién consultar."""

    def instruccion(contexto: ReadonlyContext) -> str:
        reglas = REGLAS_COMUNES.format(
            tool=tool.name, disclaimer=DISCLAIMER, universo=_universo(contexto)
        )
        return f"{rol}\n\n{reglas}"

    return LlmAgent(
        name=nombre,
        description=descripcion,
        model=resolver_modelo(config, nombre, modelo),
        mode="single_turn",
        instruction=instruccion,
        input_schema=consulta,
        tools=[tool],
        after_tool_callback=recoger_anexos,
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        generate_content_config=types.GenerateContentConfig(
            temperature=config.agentes.temperatura_personas,
            seed=config.reproducibilidad.semilla,
        ),
    )


NOTA_AL_DIRECTOR = (
    "El usuario YA LEYÓ esta respuesta completa, en la voz de {persona}. No la repitas, no la "
    "resumas y no cites NINGUNA de sus cifras. Tu cierre: de una a tres frases que solo "
    "coordinan (qué sigue, a quién más conviene oír, o en qué discrepa de otro especialista), "
    "sin proponer tú valores ni umbrales, ni siquiera como ejemplo (nada de «por ejemplo, 50 %»): "
    "si hace falta un valor, lo pone el usuario."
)


def resultado_para_el_director(persona: str, respuesta: Any) -> dict[str, Any] | None:
    """Lo que el Director recibe de una persona: su texto, con la regla JUNTO al texto.

    Visto con el modelo real (S10): con la regla solo en el cableado, el Director re-narraba las
    cifras de la persona. ``None`` si la persona no devolvió texto (un rechazo previo, p. ej.).
    """
    if not isinstance(respuesta, str):
        return None
    return {
        "respuesta_de_la_persona": respuesta,
        "nota": NOTA_AL_DIRECTOR.format(persona=persona),
    }
