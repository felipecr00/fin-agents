"""Fixtures de ``tools/``: un ``ToolContext`` real de ADK sobre una sesión en memoria."""

from __future__ import annotations

import asyncio

import pytest
from google.adk.agents import LlmAgent
from google.adk.agents.invocation_context import InvocationContext
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


@pytest.fixture
def ctx() -> ToolContext:
    """Contexto nuevo por test; el agente es de relleno y nunca llama a un modelo."""
    servicio = InMemorySessionService()
    # El universo es estado de la SESIÓN (lo pone `iniciar` o, en S8, el Director), no del tool.
    inicial = {CLAVE_UNIVERSO: universo_referencia().model_dump(mode="json")}
    sesion = asyncio.run(servicio.create_session(app_name="tests", user_id="tests", state=inicial))
    invocacion = InvocationContext(
        session_service=servicio,
        invocation_id="inv-tests",
        agent=LlmAgent(name="relleno"),
        session=sesion,
    )
    return ToolContext(invocacion)
