"""Hitos del comité EN VIVO en el chat del Director (S11, ADR-021).

Mientras ``convocar_comite`` corre, el Runner de la sesión principal no emite nada. ADK 2.9.1 no
documenta cómo emitir desde una tool fuera del modo live, pero toda invocación tiene una cola de
eventos (``InvocationContext._enqueue_event``) que el Runner consume: añade el evento a la sesión
y lo entrega al cliente. Es API PRIVADA: ``tests/test_hitos_en_vivo.py`` fija la semántica de la
que dependemos y, si algo falla, ``transmitir`` devuelve ``False`` y el comité sigue —quedan la
bitácora y la cronología del cierre—. Nunca tumba una corrida.

El texto lleva ``MARCA_HITO`` (invisible): ``agents/anexos.py`` retira del historial del modelo
todo contenido que la lleve. Lo que el modelo ve, lo imita (S9).
"""

from __future__ import annotations

import logging

from google.adk.events.event import Event
from google.adk.tools.tool_context import ToolContext
from google.genai import types
from pydantic import ValidationError

AUTOR_COMITE = "comite"
# U+2062 (invisible times) ×2: distinta de la marca de los anexos (U+2063) a propósito, porque
# aquella recorta "desde la marca" y esta retira el contenido entero.
MARCA_HITO = "⁢⁢"

logger = logging.getLogger(__name__)


async def transmitir(ctx: ToolContext, texto: str) -> bool:
    """Encola ``texto`` como evento del comité en la invocación en curso. ``False`` = no se pudo
    (sin cola, API cambiada): quien llama deja de intentarlo en esta corrida."""
    invocacion = getattr(ctx, "_invocation_context", None)
    encolar = getattr(invocacion, "_enqueue_event", None)
    if encolar is None or getattr(invocacion, "_event_queue", None) is None:
        return False
    rama = ctx.function_call_id
    try:
        await encolar(
            Event(
                invocation_id=ctx.invocation_id,
                author=AUTOR_COMITE,
                branch=f"convocar_comite@{rama}" if rama else "convocar_comite",
                content=types.Content(
                    role="model", parts=[types.Part(text=f"{MARCA_HITO}{texto}")]
                ),
            )
        )
    except (AttributeError, RuntimeError, TypeError, ValidationError) as exc:
        logger.warning("hitos en vivo desactivados para esta corrida: %s", exc)
        return False
    return True
