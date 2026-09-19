"""Corrida REAL contra dev (Cloud Run) o prod (Agent Engine) y replay local (ADR-009).

    uv run python scripts/corrida_remota.py https://<servicio>.run.app ["contexto opcional"]
    uv run python scripts/corrida_remota.py projects/<n>/locations/<r>/reasoningEngines/<id>

1. Crea una sesión y ejecuta el pipeline: en Cloud Run por la API de `adk api_server`
   (`/apps/.../sessions`, `/run`); en Agent Engine por `:query` / `:streamQuery`
   (`create_session`, `stream_query`, `get_session`), con sesiones administradas.
2. Lee el `RunState` del estado de sesión y lo guarda en `runs/remotas/<run_id>/`.
3. Repite la corrida en local con las mismas views y restricciones y compara los números.

Autenticación con tu usuario de gcloud: identity token para Cloud Run (o la variable
ID_TOKEN), access token para Agent Engine. Una URL `http://localhost…` va sin token.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any

from investmentsys.config import RAIZ_PROYECTO, cargar_config
from investmentsys.contracts import RunState
from investmentsys.data import provider_de_config
from investmentsys.orchestrator import CLAVE_RUN_STATE, ResultadoReplay, persistir, repetir

APP = "pipeline"
USUARIO = "verificacion"
SUBDIRECTORIO = "remotas"
TIMEOUT_S = 300  # el mismo tope que la petición de Cloud Run
MAX_DIFERENCIAS = 20


def _gcloud_token(tipo: str) -> str:
    salida = subprocess.run(
        ["gcloud", "auth", f"print-{tipo}-token"], check=True, capture_output=True, text=True
    )
    return salida.stdout.strip()


def _token(url: str) -> str | None:
    if url.startswith("http://localhost") or url.startswith("http://127.0.0.1"):
        return None
    return os.environ.get("ID_TOKEN") or _gcloud_token("identity")


def _pedir(url: str, token: str | None, cuerpo: dict[str, Any] | None = None) -> str:
    cabeceras = {"Content-Type": "application/json"}
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(url, data=datos, headers=cabeceras)
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_S) as respuesta:
            texto: str = respuesta.read().decode()
            return texto
    except urllib.error.HTTPError as exc:
        # 401/403: falta permiso de invocación; 500: mirar los logs (docs/operacion.md).
        sys.exit(f"HTTP {exc.code} en {url}: {exc.read().decode(errors='replace')[:500]}")


def _llamar(url: str, token: str | None, cuerpo: dict[str, Any] | None = None) -> Any:
    return json.loads(_pedir(url, token, cuerpo))


def _extraer(estado: dict[str, Any]) -> RunState:
    if CLAVE_RUN_STATE not in estado:
        sys.exit(f"la sesión no tiene '{CLAVE_RUN_STATE}': la corrida no llegó a `cerrar`")
    return RunState.model_validate(estado[CLAVE_RUN_STATE])


def correr_agent_engine(recurso: str, mensaje: str) -> RunState:
    region = recurso.split("/")[3]
    base = f"https://{region}-aiplatform.googleapis.com/v1/{recurso}"
    token = _gcloud_token("access")

    def metodo(nombre: str, **entrada: Any) -> dict[str, Any]:
        return {"class_method": nombre, "input": {"user_id": USUARIO, **entrada}}

    sesion = _llamar(f"{base}:query", token, metodo("create_session"))["output"]["id"]
    flujo = _pedir(
        f"{base}:streamQuery?alt=sse",
        token,
        metodo("stream_query", session_id=sesion, message=mensaje),
    )
    print(f"sesión administrada {sesion}: {len(flujo.splitlines())} eventos")
    salida = _llamar(f"{base}:query", token, metodo("get_session", session_id=sesion))
    return _extraer(salida["output"]["state"])


def correr(base: str, mensaje: str) -> RunState:
    token = _token(base)
    sesiones = f"{base}/apps/{APP}/users/{USUARIO}/sessions"
    sesion = _llamar(sesiones, token, {})["id"]
    eventos = _llamar(
        f"{base}/run",
        token,
        {
            "app_name": APP,
            "user_id": USUARIO,
            "session_id": sesion,
            "new_message": {"role": "user", "parts": [{"text": mensaje}]},
        },
    )
    print(f"sesión {sesion}: {len(eventos)} eventos")
    return _extraer(_llamar(f"{sesiones}/{sesion}", token)["state"])


def informar(resultado: ResultadoReplay, tolerancia: float) -> None:
    print(f"valores comparados: {resultado.comparados}")
    print(f"desviación máxima:  {resultado.desviacion_maxima:.3e} (tolerancia {tolerancia:.0e})")
    for aviso in resultado.no_repetible:
        print(f"no repetible: {aviso}")
    for d in resultado.diferencias[:MAX_DIFERENCIAS]:
        print(f"DIFERENCIA {d.ruta}: remoto={d.remoto!r} local={d.local!r}")


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    destino = sys.argv[1].rstrip("/")
    mensaje = sys.argv[2] if len(sys.argv) > 2 else "Analiza el mercado y propón una cartera."
    config = cargar_config()
    en_prod = destino.startswith("projects/")
    corrida = correr_agent_engine(destino, mensaje) if en_prod else correr(destino, mensaje)
    carpeta = persistir(corrida, RAIZ_PROYECTO / config.corridas.directorio / SUBDIRECTORIO)
    final = corrida.portafolio_final
    print(f"corrida remota {corrida.run_id} ({corrida.etapa.value}) guardada en {carpeta}")
    print(f"semilla {corrida.semilla}, config_hash {corrida.config_hash[:12]}…")
    print(f"pesos: {dict(final.pesos) if final else 'sin cartera aprobada'}")
    resultado = repetir(corrida, config, provider_de_config(config))
    informar(resultado, config.reproducibilidad.tolerancia_replay)
    if not resultado.reproduce:
        sys.exit("La corrida remota NO reproduce la local.")
    print("OK: la corrida remota reproduce la local.")


if __name__ == "__main__":
    main()
