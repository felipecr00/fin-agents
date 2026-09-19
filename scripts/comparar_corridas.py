"""Diff estructurado entre dos corridas: `make comparar A=<run_id> B=<run_id>`.

    uv run python scripts/comparar_corridas.py <antes> <después>

Cada argumento es un `run_id` de `runs/` (también busca en `runs/remotas/`) o la ruta a un
`run_state.json`. Imprime el informe y lo guarda en `runs/comparaciones/<antes>__<después>.md`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from investmentsys.comparacion import (
    EsquemaAnteriorError,
    comparar_corridas,
    diff_markdown,
    leer_corrida,
)
from investmentsys.config import RAIZ_PROYECTO, cargar_config
from investmentsys.contracts import RunState

SUBCARPETA = "comparaciones"
ARCHIVO = "run_state.json"


def _cargar(referencia: str, corridas: Path) -> RunState:
    candidatas = [
        Path(referencia),
        corridas / referencia / ARCHIVO,
        corridas / "remotas" / referencia / ARCHIVO,
    ]
    ruta = next((r for r in candidatas if r.is_file()), None)
    if ruta is None:
        sys.exit(f"no encuentro la corrida '{referencia}' (ni como ruta ni en {corridas}/)")
    try:
        return leer_corrida(ruta.read_text(encoding="utf-8"), referencia)
    except EsquemaAnteriorError as exc:
        sys.exit(str(exc))


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    config = cargar_config()
    corridas = RAIZ_PROYECTO / config.corridas.directorio
    antes, despues = (_cargar(r, corridas) for r in sys.argv[1:])
    tolerancia = config.reproducibilidad.tolerancia_replay
    informe = diff_markdown(comparar_corridas(antes, despues, tolerancia), tolerancia)
    destino = corridas / SUBCARPETA
    destino.mkdir(parents=True, exist_ok=True)
    archivo = destino / f"{antes.run_id}__{despues.run_id}.md"
    archivo.write_text(informe, encoding="utf-8")
    print(informe)
    print(f"Guardado en {archivo.relative_to(RAIZ_PROYECTO)}")


if __name__ == "__main__":
    main()
