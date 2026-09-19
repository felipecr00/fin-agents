"""App de ``adk web`` para probar el Analista de Mercados aislado: ``make run-local``."""

from investmentsys.agents.market_analyst import crear_market_analyst
from investmentsys.config import cargar_config
from investmentsys.data import provider_de_config

_config = cargar_config()
root_agent = crear_market_analyst(_config, provider_de_config(_config))
