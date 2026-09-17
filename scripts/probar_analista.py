"""Corrida REAL del Analista de Mercados contra Gemini (necesita credenciales).

    uv run python scripts/probar_analista.py ["contexto opcional para el analista"]

Las credenciales se leen del entorno o de `.env` en la raíz (ver `.env.example`); nunca se
imprimen ni se commitean. Imprime cada evento y el `MarketViews` validado que queda en el estado.
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from investmentsys.agents.market_analyst import crear_market_analyst
from investmentsys.config import RAIZ_PROYECTO, cargar_config
from investmentsys.contracts import MarketViews
from investmentsys.data import CSVPriceProvider
from investmentsys.tools import CLAVE_MARKET_VIEWS

VARIABLES = (
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_GENAI_USE_ENTERPRISE",
    "GOOGLE_GENAI_USE_VERTEXAI",
)


async def correr(mensaje: str) -> MarketViews:
    config = cargar_config()
    agente = crear_market_analyst(config, CSVPriceProvider(config.datos.ruta_csv))
    sesiones = InMemorySessionService()
    runner = Runner(agent=agente, app_name="probar_analista", session_service=sesiones)
    sesion = await sesiones.create_session(app_name="probar_analista", user_id="local")
    contenido = types.Content(role="user", parts=[types.Part(text=mensaje)])
    async for evento in runner.run_async(
        user_id="local", session_id=sesion.id, new_message=contenido
    ):
        for parte in evento.content.parts if evento.content and evento.content.parts else []:
            if parte.text:
                print(f"\n[{evento.author}]\n{parte.text}")
    final = await sesiones.get_session(
        app_name="probar_analista", user_id="local", session_id=sesion.id
    )
    assert final is not None
    return MarketViews.model_validate(final.state[CLAVE_MARKET_VIEWS])


def main() -> None:
    load_dotenv(RAIZ_PROYECTO / ".env")
    if not any(os.environ.get(v) for v in VARIABLES):
        sys.exit("Sin credenciales de Gemini en el entorno ni en .env (ver .env.example).")
    mensaje = sys.argv[1] if len(sys.argv) > 1 else "Dame tus views para este universo."
    views = asyncio.run(correr(mensaje))
    print(f"\nModelo: {cargar_config().agentes.modelo}")
    print("MarketViews validado contra el contrato:")
    print(views.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
