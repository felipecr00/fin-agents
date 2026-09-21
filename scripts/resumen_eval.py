"""Resume el último `adk eval` de una app y falla si algún caso no pasó (lo usa `make eval`).

    uv run --group eval python scripts/resumen_eval.py tests/eval/agentes/market_analyst

Imprime una fila por caso con los criterios incumplidos, guarda el mismo resumen en
`runs/evals/<id del resultado>.md` y termina con código 1 si hay casos fallidos.
"""

from __future__ import annotations

import sys
from pathlib import Path

from investmentsys.config import RAIZ_PROYECTO, cargar_config
from investmentsys.evaluacion.informe import (
    a_markdown,
    casos_evaluados,
    leer_resultado,
    ultimo_resultado,
)

SUBCARPETA = "evals"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    config = cargar_config()
    resultado = leer_resultado(ultimo_resultado(Path(sys.argv[1]).resolve()))
    casos = casos_evaluados(resultado)
    titulo = f"Evals de {resultado.eval_set_id} — modelo {config.inferencia.nivel_1.modelo}"
    informe = a_markdown(casos, titulo)
    print(informe)
    destino = RAIZ_PROYECTO / config.corridas.directorio / SUBCARPETA
    destino.mkdir(parents=True, exist_ok=True)
    archivo = destino / f"{resultado.eval_set_result_id}.md"
    archivo.write_text(informe, encoding="utf-8")
    print(f"Guardado en {archivo.relative_to(RAIZ_PROYECTO)}")
    if not all(c.aprobado for c in casos):
        sys.exit(1)


if __name__ == "__main__":
    main()
