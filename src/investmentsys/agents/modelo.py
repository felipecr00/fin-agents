"""Qué modelo recibe cada ``LlmAgent``: el del NIVEL de inferencia que ``config.yaml`` asigna a
ese agente (ADR-018), con los reintentos ante errores transitorios y, en Vertex AI, la ubicación
del modelo (ADR-008). Aquí no hay nombres de modelos ni de proveedores: la clase cliente de ADK
y el id del modelo se leen de ``inferencia.<nivel>``.

- Reintentos: un 429/503 del proveedor es transitorio y sin ellos tumba la corrida entera. Los
  hace el cliente de google-genai (``HttpRetryOptions``) con los valores de
  ``agentes.reintentos_modelo``.
- Ubicación: el modelo de Nivel 1 se sirve en el endpoint ``global`` de Vertex, no en los
  regionales; en Agent Engine ``GOOGLE_CLOUD_LOCATION`` es la región del despliegue
  (``us-central1``) y el modelo responde 404. Solo se fija cuando el cliente va a Vertex con
  proyecto; con API key (AI Studio o modo express) el SDK no admite ``location``.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable

from google.adk.models.base_llm import BaseLlm
from google.genai import types

from investmentsys.config import Config, NivelLLM

VARIABLES_VERTEX = ("GOOGLE_GENAI_USE_ENTERPRISE", "GOOGLE_GENAI_USE_VERTEXAI")
VERDADERO = ("1", "true")


def _vertex_con_proyecto() -> bool:
    usa_vertex = any(os.environ.get(v, "").lower() in VERDADERO for v in VARIABLES_VERTEX)
    return usa_vertex and bool(os.environ.get("GOOGLE_CLOUD_PROJECT"))


def clase_cliente(nivel: NivelLLM) -> type[BaseLlm]:
    """La clase de ADK declarada en ``inferencia.<nivel>.cliente`` ("módulo:Clase")."""
    modulo, _, nombre = nivel.cliente.partition(":")
    clase = getattr(importlib.import_module(modulo), nombre)
    if not (isinstance(clase, type) and issubclass(clase, BaseLlm)):
        raise TypeError(f"inferencia: {nivel.cliente} no es un BaseLlm de ADK")
    return clase


def resolver_modelo(
    config: Config, agente: str, modelo: str | BaseLlm | None = None
) -> str | BaseLlm:
    """``modelo`` permite inyectar un LLM falso en tests; por defecto, el nivel de ``agente``."""
    if modelo is not None:
        return modelo
    nivel = config.inferencia.de(agente)
    reintentos = config.agentes.reintentos_modelo
    ubicacion = config.agentes.ubicacion_vertex
    fijar_ubicacion = bool(ubicacion) and _vertex_con_proyecto()
    # Los argumentos son los del cliente de google-genai; otra clase cliente debe aceptarlos.
    construir: Callable[..., BaseLlm] = clase_cliente(nivel)
    return construir(
        model=nivel.modelo,
        retry_options=types.HttpRetryOptions(
            attempts=reintentos.intentos,
            initial_delay=reintentos.espera_inicial_s,
            max_delay=reintentos.espera_maxima_s,
            exp_base=reintentos.base_exponencial,
            http_status_codes=list(reintentos.codigos_http),
        ),
        client_kwargs={"location": ubicacion} if fijar_ubicacion else None,
    )
