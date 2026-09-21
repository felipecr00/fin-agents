"""Sigue la bitácora de un comité desde OTRA terminal, mientras corre (S11).

    make bitacora                # espera la próxima corrida y la sigue en vivo
    make bitacora RUN=<run_id>   # una corrida concreta (en curso o ya cerrada)

Solo lee ``runs/<run_id>/bitacora.jsonl``: una línea JSON (``HitoComite``) por hito.
"""

from __future__ import annotations

import argparse
import contextlib
import time
from pathlib import Path

from investmentsys.config import RAIZ_PROYECTO, cargar_config
from investmentsys.contracts import EventoComite, HitoComite
from investmentsys.orchestrator.bitacora import ARCHIVO_BITACORA

PAUSA_S = 0.5


def _esperar_corrida_nueva(runs: Path) -> Path:
    ya_estaban = set(runs.glob(f"*/{ARCHIVO_BITACORA}"))
    print(f"Esperando la próxima corrida del comité en {runs}/ … (Ctrl-C para salir)")
    while True:
        nuevas = sorted(set(runs.glob(f"*/{ARCHIVO_BITACORA}")) - ya_estaban)
        if nuevas:
            return nuevas[-1]
        time.sleep(PAUSA_S)


def seguir(archivo: Path) -> None:
    print(f"── {archivo.parent.name}")
    inicio = None
    with archivo.open(encoding="utf-8") as bitacora:
        while True:
            linea = bitacora.readline()
            if not linea.endswith("\n"):  # aún no hay una línea completa
                time.sleep(PAUSA_S)
                continue
            hito = HitoComite.model_validate_json(linea)
            inicio = inicio or hito.timestamp
            segundos = int((hito.timestamp - inicio).total_seconds())
            print(f"+{segundos // 60:02d}:{segundos % 60:02d}  {hito.linea()}", flush=True)
            if hito.evento is EventoComite.ACTA_CONSOLIDADA:
                return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", nargs="?", help="por defecto, la próxima corrida")
    args = parser.parse_args()
    runs = RAIZ_PROYECTO / cargar_config().corridas.directorio
    archivo = runs / args.run_id / ARCHIVO_BITACORA if args.run_id else _esperar_corrida_nueva(runs)
    if not archivo.exists():
        raise SystemExit(f"no existe {archivo}")
    with contextlib.suppress(KeyboardInterrupt):
        seguir(archivo)


if __name__ == "__main__":
    main()
