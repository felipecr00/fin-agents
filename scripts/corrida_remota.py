"""Corrida REAL contra el servicio desplegado en Cloud Run (dev) y replay local (ADR-009).

    uv run python scripts/corrida_remota.py https://<servicio>.run.app ["contexto opcional"]

1. Crea una sesión y ejecuta el pipeline por HTTP (`adk api_server`: `/apps/.../sessions`, `/run`).
2. Lee el `RunState` del estado de sesión y lo guarda en `runs/remotas/<run_id>/`.
3. Repite la corrida en local con las mismas views y restricciones y compara los números.

El servicio exige autenticación: el identity token sale de `gcloud auth print-identity-token`
(o de la variable ID_TOKEN). Una URL `http://localhost…` se invoca sin token.
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
from investmentsys.data import CSVPriceProvider
from investmentsys.orchestrator import CLAVE_RUN_STATE, ResultadoReplay, persistir, repetir

APP = "pipeline"
USUARIO = "verificacion"
SUBDIRECTORIO = "remotas"
TIMEOUT_S = 300  # el mismo tope que la petición de Cloud Run
MAX_DIFERENCIAS = 20


def _token(url: str) -> str | None:
    if url.startswith("http://localhost") or url.startswith("http://127.0.0.1"):
        return None
    if os.environ.get("ID_TOKEN"):
        return os.environ["ID_TOKEN"]
    salida = subprocess.run(
        ["gcloud", "auth", "print-identity-token"], check=True, capture_output=True, text=True
    )
    return salida.stdout.strip()


def _llamar(url: str, token: str | None, cuerpo: dict[str, Any] | None = None) -> Any:
    cabeceras = {"Content-Type": "application/json"}
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(url, data=datos, headers=cabeceras)
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_S) as respuesta:
            return json.load(respuesta)
    except urllib.error.HTTPError as exc:
        # 401/403: falta roles/run.invoker; 500: mirar los logs del servicio (docs/operacion.md).
        sys.exit(f"HTTP {exc.code} en {url}: {exc.read().decode(errors='replace')[:500]}")


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
    estado = _llamar(f"{sesiones}/{sesion}", token)["state"]
    if CLAVE_RUN_STATE not in estado:
        sys.exit(f"la sesión no tiene '{CLAVE_RUN_STATE}': la corrida no llegó a `cerrar`")
    return RunState.model_validate(estado[CLAVE_RUN_STATE])


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
    base = sys.argv[1].rstrip("/")
    mensaje = sys.argv[2] if len(sys.argv) > 2 else "Analiza el mercado y propón una cartera."
    config = cargar_config()
    corrida = correr(base, mensaje)
    carpeta = persistir(corrida, RAIZ_PROYECTO / config.corridas.directorio / SUBDIRECTORIO)
    final = corrida.portafolio_final
    print(f"corrida remota {corrida.run_id} ({corrida.etapa.value}) guardada en {carpeta}")
    print(f"semilla {corrida.semilla}, config_hash {corrida.config_hash[:12]}…")
    print(f"pesos: {dict(final.pesos) if final else 'sin cartera aprobada'}")
    resultado = repetir(corrida, config, CSVPriceProvider(config.datos.ruta_csv))
    informar(resultado, config.reproducibilidad.tolerancia_replay)
    if not resultado.reproduce:
        sys.exit("La corrida remota NO reproduce la local.")
    print("OK: la corrida remota reproduce la local.")


if __name__ == "__main__":
    main()
