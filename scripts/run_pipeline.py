"""Corrida REAL completa contra Gemini (necesita credenciales; ver `.env.example`).

    uv run python scripts/run_pipeline.py ["contexto opcional para el analista"]

Analista ∥ Quant → Constructor ⇄ Validador → Reporter. Escribe `runs/<run_id>/run_state.json`
y `runs/<run_id>/reporte.md`, e imprime el recorrido y la ruta de la carpeta.
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from investmentsys.config import RAIZ_PROYECTO, cargar_config
from investmentsys.data import CSVPriceProvider
from investmentsys.orchestrator import CLAVE_DIRECTORIO, crear_pipeline

APP = "pipeline"
VARIABLES = (
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_GENAI_USE_ENTERPRISE",
    "GOOGLE_GENAI_USE_VERTEXAI",
)
MAX_CARACTERES_EVENTO = 600


async def correr(mensaje: str) -> str:
    config = cargar_config()
    pipeline = crear_pipeline(config, CSVPriceProvider(config.datos.ruta_csv))
    sesiones = InMemorySessionService()
    runner = Runner(node=pipeline, app_name=APP, session_service=sesiones)
    sesion = await sesiones.create_session(app_name=APP, user_id="local")
    contenido = types.Content(role="user", parts=[types.Part(text=mensaje)])
    async for evento in runner.run_async(
        user_id="local", session_id=sesion.id, new_message=contenido
    ):
        for parte in evento.content.parts if evento.content and evento.content.parts else []:
            if parte.function_call:
                print(
                    f"\n[{evento.author}] → {parte.function_call.name}({parte.function_call.args})"
                )
            elif parte.text:
                print(f"\n[{evento.author}]\n{parte.text[:MAX_CARACTERES_EVENTO]}")
    final = await sesiones.get_session(app_name=APP, user_id="local", session_id=sesion.id)
    assert final is not None
    return str(final.state[CLAVE_DIRECTORIO])


def main() -> None:
    load_dotenv(RAIZ_PROYECTO / ".env")
    if not any(os.environ.get(v) for v in VARIABLES):
        sys.exit("Sin credenciales de Gemini en el entorno ni en .env (ver .env.example).")
    mensaje = sys.argv[1] if len(sys.argv) > 1 else "Analiza el mercado y propón una cartera."
    print(f"\nCorrida guardada en: {asyncio.run(correr(mensaje))}")


if __name__ == "__main__":
    main()
