"""Migración única de S7: `data/precios.csv` → `data/series/<TICKER>.csv` + universo inicial.

    uv run python scripts/migrar_series.py data/precios.csv

Las series salen del CSV legado TAL CUAL (mismos números: ninguna corrida cambia por migrar);
de Tiingo solo se lee el nombre de cada activo. Las caps son las pinneadas en
`config.yaml: prior_equilibrio` (procedencia `usuario`, ADR-013). No pisa un almacén existente.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from investmentsys.config import RAIZ_PROYECTO, cargar_config
from investmentsys.data import CSVPriceProvider
from investmentsys.data.actualizacion import FORMATO_MARCA, escribir_series_atomico
from investmentsys.data_manager import GestorDatos, TiingoFuente


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    load_dotenv(RAIZ_PROYECTO / ".env")
    config = cargar_config()
    ahora = datetime.now(UTC)
    fuente = TiingoFuente(config.datos.tiingo, hoy=ahora.date())
    gestor = GestorDatos(config, fuente)
    if gestor.ruta_universo.exists() or any(gestor.directorio_series.glob("*.csv")):
        print(f"ya hay un almacén en {gestor.directorio_series}: no se migra dos veces")
        return 1
    activos = list(config.portafolio.activos)
    panel = CSVPriceProvider(Path(sys.argv[1])).precios(activos)
    escribir_series_atomico(
        panel, gestor.directorio_series, config.datos.actualizacion, ahora.strftime(FORMATO_MARCA)
    )
    universo = gestor.sembrar({a: fuente.metadata(a) for a in activos})
    print(f"universo {universo.version[:12]} con {list(universo.activos)}")
    print(gestor.diagnosticar(universo).model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
