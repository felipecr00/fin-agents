"""Fixtures de ``tools/``: un ``ToolContext`` real de ADK sobre una sesión en memoria."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest
from google.adk.agents import LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.sessions import InMemorySessionService
from google.adk.tools import ToolContext

from investmentsys.config import Config, cargar_config
from investmentsys.data import CSVPriceProvider
from investmentsys.tools import CLAVE_UNIVERSO, NucleoTools
from tests.almacen import universo_referencia
from tests.conftest import CSV_REFERENCIA


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config()


@pytest.fixture(scope="module")
def tools(config: Config) -> NucleoTools:
    return NucleoTools(config, CSVPriceProvider(CSV_REFERENCIA))


Turnos = Callable[[str], ToolContext]


@pytest.fixture
def turnos() -> Turnos:
    """``turnos("inv-1")``: un ``ToolContext`` por invocación, todos sobre la MISMA sesión.

    Cada mensaje del usuario es una invocación de ADK; el agente es de relleno y nunca llama a
    un modelo.
    """
    servicio = InMemorySessionService()
    # El universo es estado de la SESIÓN (lo pone `iniciar` o, en S8, el Director), no del tool.
    inicial = {CLAVE_UNIVERSO: universo_referencia().model_dump(mode="json")}
    sesion = asyncio.run(servicio.create_session(app_name="tests", user_id="tests", state=inicial))

    def turno(invocation_id: str) -> ToolContext:
        # Como el Runner: el mensaje del usuario abre la invocación y queda en los eventos.
        if invocation_id not in {e.invocation_id for e in sesion.events}:
            sesion.events.append(Event(invocation_id=invocation_id, author="user"))
        invocacion = InvocationContext(
            session_service=servicio,
            invocation_id=invocation_id,
            agent=LlmAgent(name="relleno"),
            session=sesion,
        )
        return ToolContext(invocacion)

    return turno


@pytest.fixture
def ctx(turnos: Turnos) -> ToolContext:
    """Contexto nuevo por test, de una sola invocación."""
    return turnos("inv-tests")
