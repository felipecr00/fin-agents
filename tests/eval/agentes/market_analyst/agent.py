"""El Analista de Mercados aislado, SOLO como sujeto de ``make eval-analista`` (``adk eval``
evalúa la carpeta de un agente). No es una interfaz: la única es ``apps/equipo`` (S11)."""

from investmentsys.agents.market_analyst import crear_market_analyst
from investmentsys.config import cargar_config
from investmentsys.data import provider_de_config

_config = cargar_config()
root_agent = crear_market_analyst(_config, provider_de_config(_config))
