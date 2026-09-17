"""Qué modelo recibe cada ``LlmAgent``: un ``Gemini`` de ADK con el id de ``config.yaml``, los
reintentos ante errores transitorios y, en Vertex AI, la ubicación del modelo (ADR-008).

- Reintentos: un 429/503 de Gemini es transitorio y sin ellos tumba la corrida entera. Los
  hace el cliente de google-genai (``HttpRetryOptions``) con los valores de
  ``agentes.reintentos_modelo``.
- Ubicación: los Gemini 3.x se sirven en el endpoint ``global`` de Vertex, no en los
  regionales; en Agent Engine ``GOOGLE_CLOUD_LOCATION`` es la región del despliegue
  (``us-central1``) y el modelo responde 404. Solo se fija cuando el cliente va a Vertex con
  proyecto; con API key (Gemini API o modo express) el SDK no admite ``location``.
"""

from __future__ import annotations

import os

from google.adk.models.base_llm import BaseLlm
from google.adk.models.google_llm import Gemini
from google.genai import types

from investmentsys.config import AgentesConfig

VARIABLES_VERTEX = ("GOOGLE_GENAI_USE_ENTERPRISE", "GOOGLE_GENAI_USE_VERTEXAI")
VERDADERO = ("1", "true")


def _vertex_con_proyecto() -> bool:
    usa_vertex = any(os.environ.get(v, "").lower() in VERDADERO for v in VARIABLES_VERTEX)
    return usa_vertex and bool(os.environ.get("GOOGLE_CLOUD_PROJECT"))


def resolver_modelo(agentes: AgentesConfig, modelo: str | BaseLlm | None = None) -> str | BaseLlm:
    """``modelo`` permite inyectar un LLM falso en tests; por defecto, ``config.agentes``."""
    if modelo is not None:
        return modelo
    reintentos = agentes.reintentos_modelo
    fijar_ubicacion = bool(agentes.ubicacion_vertex) and _vertex_con_proyecto()
    return Gemini(
        model=agentes.modelo,
        retry_options=types.HttpRetryOptions(
            attempts=reintentos.intentos,
            initial_delay=reintentos.espera_inicial_s,
            max_delay=reintentos.espera_maxima_s,
            exp_base=reintentos.base_exponencial,
            http_status_codes=list(reintentos.codigos_http),
        ),
        client_kwargs={"location": agentes.ubicacion_vertex} if fijar_ubicacion else None,
    )
