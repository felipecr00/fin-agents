"""App de ``adk web`` con la corrida completa: ``make run-local`` y elegir ``pipeline``."""

from investmentsys.config import cargar_config
from investmentsys.data import provider_de_config
from investmentsys.orchestrator import crear_pipeline

_config = cargar_config()
root_agent = crear_pipeline(_config, provider_de_config(_config))
