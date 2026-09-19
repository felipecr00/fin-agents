"""App de ``adk web`` con el Director de Análisis: ``make run-local`` y elegir ``equipo``."""

from datetime import date

from investmentsys.agents.director import crear_director
from investmentsys.config import cargar_config
from investmentsys.data import TiingoCredencialError, provider_de_config
from investmentsys.data_manager import GestorDatos, TiingoFuente

_config = cargar_config()
try:
    _fuente = TiingoFuente(_config.datos.tiingo, hoy=date.today())
except TiingoCredencialError:
    # Sin TIINGO_API_KEY el Director conversa y analiza el universo vigente; las altas y el
    # refresco de caps responden con el error del Gestor ("necesita una fuente de mercado").
    _fuente = None
root_agent = crear_director(_config, provider_de_config(_config), GestorDatos(_config, _fuente))
