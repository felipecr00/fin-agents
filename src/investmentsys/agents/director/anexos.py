"""Bloques que el CÓDIGO anexa a la respuesta del Director (S9): fichas, mesa y memorándum.

Dos callbacks de ADK sobre el Director:

- ``recoger_anexos`` (``after_tool_callback``): tras cada herramienta —también el sub-agente
  ``market_analyst``, que ADK expone como tool— arma la ficha de origen de todo resultado con
  ``validado`` y retira de la salida el bloque ya redactado (``anexo_usuario``: la mesa, el
  memorándum de convocatoria). El LLM recibe los datos, no el bloque: no hay nada que copiar mal.
- ``anexar_al_cierre`` (``after_model_callback``): cuando el modelo cierra el turno (respuesta
  final, sin llamadas pendientes), pega los bloques del turno al final del texto.

Así la etiqueta EXPLORATORIO, el prefijo de no-validado y el memorándum que el usuario aprueba
no dependen de la narración: la redacción puede ser mejor o peor; el bloque está siempre.
"""

from __future__ import annotations

from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from investmentsys.tools import CLAVE_UNIVERSO
from investmentsys.tools.ficha import ATIENDE, CLAVE_ANEXO, construir_ficha

CLAVE_ANEXOS_TURNO = "director_anexos_turno"
SEPARADOR = "\n\n---\n\n"
NOTA_ANEXO = (
    "bloque ya redactado por código: se anexa solo al final de tu respuesta. No lo copies ni "
    "lo reconstruyas; coméntalo."
)
NOTA_FICHA = (
    "la ficha de origen de este resultado (fuente, herramienta, cifras clave, sello y etiqueta) "
    "se anexa sola al final de tu respuesta. Igual nombra al especialista cuando cites una cifra."
)


def _bloques_del_turno(estado: Any, invocacion: str) -> list[str]:
    guardado = estado.get(CLAVE_ANEXOS_TURNO) or {}
    return list(guardado.get("bloques", [])) if guardado.get("invocacion") == invocacion else []


def recoger_anexos(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, tool_response: dict[str, Any]
) -> dict[str, Any] | None:
    if not isinstance(tool_response, dict) or tool.name not in ATIENDE:
        return None
    respuesta = dict(tool_response)
    nuevos = []
    anexo = respuesta.pop(CLAVE_ANEXO, None)
    if anexo:
        nuevos.append(str(anexo))
        respuesta["anexo"] = NOTA_ANEXO
    vigente = (tool_context.state.get(CLAVE_UNIVERSO) or {}).get("version")
    ficha = construir_ficha(tool.name, respuesta, vigente)
    if ficha:
        nuevos.append(ficha)
        respuesta["ficha_origen"] = NOTA_FICHA
    if not nuevos:
        return None
    invocacion = tool_context.invocation_id
    bloques = _bloques_del_turno(tool_context.state, invocacion)
    bloques += [b for b in nuevos if b not in bloques]
    tool_context.state[CLAVE_ANEXOS_TURNO] = {"invocacion": invocacion, "bloques": bloques}
    return respuesta


def anexar_al_cierre(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> LlmResponse | None:
    contenido = llm_response.content
    if llm_response.partial or contenido is None or not contenido.parts:
        return None
    if any(p.function_call or p.function_response for p in contenido.parts):
        return None  # el turno sigue: todavía hay herramientas por correr
    bloques = _bloques_del_turno(callback_context.state, callback_context.invocation_id)
    if not bloques:
        return None
    callback_context.state[CLAVE_ANEXOS_TURNO] = None
    anexo = SEPARADOR + SEPARADOR.join(bloques)
    partes = list(contenido.parts)
    ultima = next((i for i in reversed(range(len(partes))) if partes[i].text), None)
    if ultima is None:
        partes.append(types.Part(text=anexo.lstrip()))
    else:  # mismo Part: para la interfaz y para el historial es UNA respuesta
        partes[ultima] = types.Part(text=f"{partes[ultima].text}{anexo}")
    return llm_response.model_copy(
        update={"content": types.Content(role=contenido.role, parts=partes)}
    )
