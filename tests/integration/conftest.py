"""LLM falso y ejecución de agentes con el ``Runner`` real de ADK (sin red ni credenciales)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, ClassVar

import pytest
from google.adk.agents.base_agent import BaseAgent
from google.adk.events.event import Event
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import BaseNode
from google.genai import types
from pydantic import PrivateAttr

from investmentsys.config import Config, cargar_config
from investmentsys.data import CSVPriceProvider


class LlmGuionado(BaseLlm):
    """Devuelve las respuestas del guion en orden y registra cada petición recibida."""

    model: str = "llm-guionado"
    _guion: list[str | Exception] = PrivateAttr(default_factory=list)
    _peticiones: list[LlmRequest] = PrivateAttr(default_factory=list)

    def __init__(self, *respuestas: str | dict[str, Any] | Exception) -> None:
        super().__init__()
        self._guion = [r if isinstance(r, str | Exception) else json.dumps(r) for r in respuestas]

    @property
    def peticiones(self) -> list[LlmRequest]:
        return self._peticiones

    def instruccion(self, llamada: int) -> str:
        return str(self._peticiones[llamada].config.system_instruction)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self._peticiones.append(llm_request)
        if not self._guion:
            raise AssertionError("el agente llamó al LLM más veces de las previstas en el guion")
        texto = self._guion.pop(0)
        if isinstance(texto, Exception):
            raise texto
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=texto)]))


class Llamada(dict[str, Any]):
    """Respuesta del guion que es una llamada a un tool: ``Llamada("tool", arg=...)``."""

    def __init__(self, nombre: str, **args: Any) -> None:
        super().__init__(args)
        self.nombre = nombre


class LlmPorAgente(BaseLlm):
    """Un guion por agente, elegido por una frase distintiva de su instrucción de sistema."""

    model: str = "llm-por-agente"
    _guiones: dict[str, list[Any]] = PrivateAttr(default_factory=dict)
    _instrucciones: dict[str, list[str]] = PrivateAttr(default_factory=dict)

    def __init__(self, **guiones: list[Any]) -> None:
        super().__init__()
        self._guiones = {k: list(v) for k, v in guiones.items()}
        self._instrucciones = {k: [] for k in guiones}

    MARCAS: ClassVar[dict[str, str]] = {
        "analista": "Eres el Analista de Mercados",
        "constructor": "Eres el Constructor de Portafolios",
        "reporter": "Eres el redactor del informe",
    }

    def instrucciones(self, agente: str) -> list[str]:
        return self._instrucciones[agente]

    def pendientes(self) -> dict[str, int]:
        return {k: len(v) for k, v in self._guiones.items() if v}

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        sistema = str(llm_request.config.system_instruction)
        (agente,) = [a for a, marca in self.MARCAS.items() if marca in sistema]
        self._instrucciones[agente].append(sistema)
        if not self._guiones.get(agente):
            raise AssertionError(f"{agente}: llamada al LLM no prevista en el guion")
        paso = self._guiones[agente].pop(0)
        if isinstance(paso, Llamada):
            parte = types.Part(function_call=types.FunctionCall(name=paso.nombre, args=dict(paso)))
        else:
            parte = types.Part(text=paso if isinstance(paso, str) else json.dumps(paso))
        yield LlmResponse(content=types.Content(role="model", parts=[parte]))


@dataclass
class Corrida:
    eventos: list[Event] = field(default_factory=list)
    estado: dict[str, Any] = field(default_factory=dict)

    def textos(self, autor: str) -> list[str]:
        return [
            parte.text
            for e in self.eventos
            if e.author == autor and e.content and e.content.parts
            for parte in e.content.parts
            if parte.text
        ]


def ejecutar(
    agente: BaseAgent | BaseNode, mensaje: str = "adelante", estado: dict[str, Any] | None = None
) -> Corrida:
    async def _correr() -> Corrida:
        sesiones = InMemorySessionService()
        if isinstance(agente, BaseAgent):
            runner = Runner(agent=agente, app_name="tests", session_service=sesiones)
        else:
            runner = Runner(node=agente, app_name="tests", session_service=sesiones)
        sesion = await sesiones.create_session(app_name="tests", user_id="u", state=estado or {})
        corrida = Corrida()
        contenido = types.Content(role="user", parts=[types.Part(text=mensaje)])
        try:
            async for evento in runner.run_async(
                user_id="u", session_id=sesion.id, new_message=contenido
            ):
                corrida.eventos.append(evento)
        finally:
            final = await sesiones.get_session(app_name="tests", user_id="u", session_id=sesion.id)
            assert final is not None
            corrida.estado = dict(final.state)
        return corrida

    return asyncio.run(_correr())


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config()


@pytest.fixture(scope="module")
def provider(config: Config) -> CSVPriceProvider:
    return CSVPriceProvider(config.datos.ruta_csv)
