"""Modo comando (S11): el comité completo sin conversación, como TARGET de despliegue.

No es una interfaz: ``adk web`` sirve solo ``apps/equipo``. Este módulo es lo que despliegan
``make deploy-prod`` (Agent Engine) y el contenedor de dev (API, para ``make corrida-dev`` y el
replay de ADR-009). En local, el modo comando es ``make comando``.
"""

from investmentsys.config import cargar_config
from investmentsys.data import provider_de_config
from investmentsys.orchestrator import crear_pipeline

_config = cargar_config()
root_agent = crear_pipeline(_config, provider_de_config(_config))
