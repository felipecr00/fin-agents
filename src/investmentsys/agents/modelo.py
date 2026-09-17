"""Qué modelo recibe cada ``LlmAgent``: el id de ``config.yaml`` o, en Vertex AI, un ``Gemini``
con la ubicación del modelo fijada (ADR-008).

Los Gemini 3.x se sirven en el endpoint ``global`` de Vertex, no en los regionales: en Agent
Engine ``GOOGLE_CLOUD_LOCATION`` es la región del despliegue (``us-central1``) y el modelo
responde 404. La ubicación solo se fija cuando el cliente va a Vertex con proyecto; con API key
(Gemini API o modo express) el SDK no admite ``location``.
"""

from __future__ import annotations

import os

from google.adk.models.base_llm import BaseLlm
from google.adk.models.google_llm import Gemini

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
    if agentes.ubicacion_vertex and _vertex_con_proyecto():
        return Gemini(model=agentes.modelo, client_kwargs={"location": agentes.ubicacion_vertex})
    return agentes.modelo
