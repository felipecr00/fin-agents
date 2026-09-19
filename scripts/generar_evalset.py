"""Regenera `tests/eval/market_analyst.evalset.json` desde `casos_market_analyst.yaml`.

uv run python scripts/generar_evalset.py        (o `make evalset`)
"""

from __future__ import annotations

from investmentsys.config import RAIZ_PROYECTO
from investmentsys.evaluacion.evalset import cargar_casos, construir_evalset, serializar

CARPETA = RAIZ_PROYECTO / "tests" / "eval"
CASOS = CARPETA / "casos_market_analyst.yaml"
EVALSET = CARPETA / "market_analyst.evalset.json"
APP = "market_analyst"


def main() -> None:
    casos = cargar_casos(CASOS)
    EVALSET.write_text(serializar(construir_evalset(casos, APP)), encoding="utf-8")
    print(f"{EVALSET.relative_to(RAIZ_PROYECTO)}: {len(casos.casos)} casos")


if __name__ == "__main__":
    main()
