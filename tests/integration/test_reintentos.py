"""Un 429 del modelo se reintenta con ``agentes.reintentos_modelo`` en vez de tumbar la corrida.

Servidor HTTP local que imita a la API: N respuestas 429 y después una correcta. Se ejerce el
cliente real que entrega ``resolver_modelo`` (sin red externa ni credenciales).
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, ClassVar

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.genai import types

from investmentsys.agents.modelo import VARIABLES_VERTEX, resolver_modelo
from investmentsys.config import Config

AGOTADO = {"error": {"code": 429, "message": "Resource exhausted", "status": "RESOURCE_EXHAUSTED"}}
CORRECTA = {
    "candidates": [
        {"content": {"role": "model", "parts": [{"text": "ok"}]}, "finishReason": "STOP"}
    ]
}
ESPERA_DE_PRUEBA_S = 0.01


class _ApiFalsa(BaseHTTPRequestHandler):
    fallos_restantes: ClassVar[int] = 0
    peticiones: ClassVar[int] = 0

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        cls = type(self)
        cls.peticiones += 1
        cuerpo: dict[str, Any] = AGOTADO if cls.fallos_restantes > 0 else CORRECTA
        cls.fallos_restantes -= 1
        datos = json.dumps(cuerpo).encode()
        self.send_response(429 if cuerpo is AGOTADO else 200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    for variable in (*VARIABLES_VERTEX, "GOOGLE_CLOUD_PROJECT"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "llave-falsa")
    _ApiFalsa.peticiones = 0
    servidor = HTTPServer(("127.0.0.1", 0), _ApiFalsa)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{servidor.server_port}"
    servidor.shutdown()


def _agentes(config: Config, intentos: int) -> Config:
    reintentos = config.agentes.reintentos_modelo.model_copy(
        update={"intentos": intentos, "espera_inicial_s": ESPERA_DE_PRUEBA_S}
    )
    agentes = config.agentes.model_copy(update={"reintentos_modelo": reintentos})
    return config.model_copy(update={"agentes": agentes})


def _preguntar(config: Config, url: str) -> str | None:
    modelo: Any = resolver_modelo(config, "director")
    assert isinstance(modelo, BaseLlm)
    modelo.base_url = url
    contenido = types.Content(role="user", parts=[types.Part(text="hola")])
    peticion = LlmRequest(model=config.inferencia.nivel_1.modelo, contents=[contenido])

    async def _una() -> str | None:
        async for respuesta in modelo.generate_content_async(peticion):
            assert respuesta.content and respuesta.content.parts
            return respuesta.content.parts[0].text
        return None

    return asyncio.run(_una())


def test_dos_429_seguidos_se_absorben(config: Config, api: str) -> None:
    _ApiFalsa.fallos_restantes = 2
    assert _preguntar(_agentes(config, intentos=3), api) == "ok"
    assert _ApiFalsa.peticiones == 3


def test_agotados_los_intentos_el_error_se_propaga(config: Config, api: str) -> None:
    _ApiFalsa.fallos_restantes = 5
    with pytest.raises(Exception, match="RESOURCE_EXHAUSTED"):
        _preguntar(_agentes(config, intentos=2), api)
    assert _ApiFalsa.peticiones == 2
