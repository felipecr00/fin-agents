"""MODO COMANDO: el comité completo contra el modelo real, sin conversación (`make comando`).

    uv run python scripts/run_pipeline.py ["contexto opcional para el analista"]

Analista ∥ Quant → Constructor ⇄ Validador → Reporter. Escribe `runs/<run_id>/run_state.json`,
`reporte.md` y `bitacora.jsonl`, e imprime los HITOS del comité a medida que ocurren (S11): es
un target de make y de despliegue, no un visor. Necesita credenciales (ver `.env.example`).
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
from investmentsys.contracts import HitoComite
from investmentsys.data import provider_de_config
from investmentsys.orchestrator import CLAVE_DIRECTORIO, crear_pipeline
from investmentsys.orchestrator.bitacora import CLAVE_HITOS, linea_con_tiempo

APP = "pipeline"
VARIABLES = (
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_GENAI_USE_ENTERPRISE",
    "GOOGLE_GENAI_USE_VERTEXAI",
)


async def correr(mensaje: str) -> str:
    config = cargar_config()
    pipeline = crear_pipeline(config, provider_de_config(config))
    sesiones = InMemorySessionService()
    runner = Runner(node=pipeline, app_name=APP, session_service=sesiones)
    sesion = await sesiones.create_session(app_name=APP, user_id="local")
    contenido = types.Content(role="user", parts=[types.Part(text=mensaje)])
    impresos = 0
    async for evento in runner.run_async(
        user_id="local", session_id=sesion.id, new_message=contenido
    ):
        crudos = (evento.actions.state_delta or {}).get(CLAVE_HITOS) or []
        hitos = [HitoComite.model_validate(c) for c in crudos]
        for hito in hitos[impresos:]:
            print(linea_con_tiempo(hito, hitos[0].timestamp).replace("**", ""), flush=True)
        impresos = max(impresos, len(hitos))
    final = await sesiones.get_session(app_name=APP, user_id="local", session_id=sesion.id)
    assert final is not None
    return str(final.state[CLAVE_DIRECTORIO])


def main() -> None:
    load_dotenv(RAIZ_PROYECTO / ".env")
    if not any(os.environ.get(v) for v in VARIABLES):
        sys.exit("Sin credenciales del modelo en el entorno ni en .env (ver .env.example).")
    mensaje = sys.argv[1] if len(sys.argv) > 1 else "Analiza el mercado y propón una cartera."
    print(f"\nCorrida guardada en: {asyncio.run(correr(mensaje))}")


if __name__ == "__main__":
    main()
