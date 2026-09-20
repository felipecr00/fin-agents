"""Bloques que el CÓDIGO anexa a la respuesta del Director (S9): fichas, mesa y memorándum.

Tres callbacks de ADK:

- ``recoger_anexos`` (``after_tool_callback``): tras cada herramienta —también el sub-agente
  ``market_analyst``, que ADK expone como tool— arma la ficha de origen de todo resultado con
  ``validado`` y retira de la salida el bloque ya redactado (``anexo_usuario``: la mesa, el
  memorándum de convocatoria). El LLM recibe los datos, no el bloque: no hay nada que copiar mal.
  Desde S10 (ADR-019) es también el callback de las PERSONAS thin: el Director solo recibe el
  texto de la persona, así que la ficha la recoge quien ve la salida de la herramienta. Estado
  e ``invocation_id`` son los del turno, y el Director la anexa al cierre igual que las suyas.
- ``anexar_al_cierre`` (``after_model_callback``): cuando el modelo cierra el turno (respuesta
  final, sin llamadas pendientes), pega los bloques del turno al final del texto.
- ``ocultar_anexos_al_modelo`` (``before_model_callback``): recorta esos bloques del historial
  que ve el LLM. Sin esto, desde el segundo turno el modelo los toma por texto suyo y los IMITA
  (observado en la demo de S9: su copia de la mesa salió sin el prefijo de no-validado, y
  duplicada con la del código). Lo que no ve, no lo puede copiar mal.

Así la etiqueta EXPLORATORIO, el prefijo de no-validado y el memorándum que el usuario aprueba
no dependen de la narración: la redacción puede ser mejor o peor; el bloque está siempre.
"""

from __future__ import annotations

from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from investmentsys.tools import CLAVE_UNIVERSO
from investmentsys.tools.ficha import ATIENDE, CLAVE_ANEXO, construir_ficha

CLAVE_ANEXOS_TURNO = "director_anexos_turno"
SEPARADOR = "\n\n---\n\n"
# Separador invisible (U+2063) que abre el anexo: ningún renderizador lo muestra y permite
# recortar del historial exactamente lo que añadió el código.
MARCA_ANEXO = "\u2063\u2063"
CIERRE_SIN_TEXTO = (
    "Aquí está el resultado; el detalle y su origen van debajo. Dime cómo quieres seguir."
)
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
    if llm_response.partial or llm_response.error_code:
        return None
    contenido = llm_response.content
    partes_previas = list(contenido.parts or []) if contenido is not None else []
    if any(p.function_call or p.function_response for p in partes_previas):
        return None  # el turno sigue: todavía hay herramientas por correr
    bloques = _bloques_del_turno(callback_context.state, callback_context.invocation_id)
    # S10: el modelo a veces cierra el turno SIN texto (visto en el eval y en la demo reales:
    # 3 de 8 turnos). La ficha se entrega igual, y el turno nunca queda mudo: un cierre vacío
    # confundía además al modelo en el turno siguiente (contestó la pregunta anterior).
    mudo = not any(p.text and p.text.strip() and not p.thought for p in partes_previas)
    if mudo:
        partes_previas = [*partes_previas, types.Part(text=CIERRE_SIN_TEXTO)]
    elif not bloques:
        return None
    rol = contenido.role if contenido is not None and contenido.role else "model"
    if not bloques:
        return llm_response.model_copy(
            update={"content": types.Content(role=rol, parts=partes_previas)}
        )
    callback_context.state[CLAVE_ANEXOS_TURNO] = None
    # La marca va en su propia línea: los títulos de los bloques deben empezar su línea limpios.
    anexo = f"\n\n{MARCA_ANEXO}{SEPARADOR}{SEPARADOR.join(bloques)}"
    partes = partes_previas
    ultima = next(
        (i for i in reversed(range(len(partes))) if partes[i].text and not partes[i].thought), None
    )
    if ultima is None:
        partes.append(types.Part(text=anexo.lstrip()))
    else:  # mismo Part: para la interfaz y para el historial es UNA respuesta
        partes[ultima] = types.Part(text=f"{partes[ultima].text}{anexo}")
    return llm_response.model_copy(update={"content": types.Content(role=rol, parts=partes)})


def ocultar_anexos_al_modelo(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    for contenido in llm_request.contents:
        for i, parte in enumerate(contenido.parts or []):
            if parte.text and MARCA_ANEXO in parte.text:
                propio = parte.text.split(MARCA_ANEXO)[0].rstrip()
                assert contenido.parts is not None
                # Sin nota en su lugar: el modelo imita lo que ve al final de sus propios turnos
                # (en la demo real repitió la nota tal cual). Del anexo ya avisa la salida de
                # la herramienta, que sí conserva.
                contenido.parts[i] = types.Part(text=propio)
    return None
