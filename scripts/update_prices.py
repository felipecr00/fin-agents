"""Actualiza `data/precios.csv` desde Tiingo, con validación previa (ADR-011).

    make update-prices                      # descarga, valida y, si todo está verde, escribe
    make update-prices SIMULAR=1            # valida y muestra el resumen sin escribir
    make update-prices ACEPTAR_DISCREPANCIAS=1   # tras revisar TÚ un aborto por continuidad

Necesita `TIINGO_API_KEY` en el entorno o en `.env`. Deja el resumen en
`runs/actualizaciones/<marca>/` también cuando aborta. Código de salida: 0 escrito, sin cambios
o simulación; 1 abortado por una validación (el CSV vigente queda intacto); 2 fallo de la fuente.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime

from dotenv import load_dotenv

from investmentsys.config import RAIZ_PROYECTO, cargar_config
from investmentsys.data import DatosInvalidosError, TiingoError, TiingoPriceProvider
from investmentsys.data.actualizacion import (
    Estado,
    actualizar_precios,
    formatear_resumen,
    guardar_resumen,
)

SALIDA_ABORTADO = 1
SALIDA_FUENTE = 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="valida y resume; no escribe")
    parser.add_argument(
        "--aceptar-discrepancias",
        action="store_true",
        help="escribe aunque la continuidad difiera (decisión humana tras revisar el aborto)",
    )
    parser.add_argument(
        "--hoy", type=date.fromisoformat, default=None, help="AAAA-MM-DD; por defecto, hoy"
    )
    args = parser.parse_args()

    load_dotenv(RAIZ_PROYECTO / ".env")
    config = cargar_config()
    ahora = datetime.now(UTC)
    hoy = args.hoy or date.today()
    try:
        fuente = TiingoPriceProvider(config.portafolio.activos, config.datos.tiingo, hoy=hoy)
        resumen = actualizar_precios(
            fuente,
            config.portafolio.activos,
            RAIZ_PROYECTO / config.datos.ruta_csv,
            config.datos.actualizacion,
            config.datos.tiingo.fecha_inicio,
            hoy=hoy,
            ahora=ahora,
            nombre_fuente="tiingo (EOD, resampleFreq=monthly, adjClose)",
            simular=args.dry_run,
            aceptar_discrepancias=args.aceptar_discrepancias,
        )
    except (TiingoError, DatosInvalidosError) as exc:
        print(f"ERROR de la fuente; el CSV vigente no se tocó.\n{exc}", file=sys.stderr)
        return SALIDA_FUENTE

    print(formatear_resumen(resumen))
    carpeta = guardar_resumen(
        resumen, RAIZ_PROYECTO / config.datos.actualizacion.directorio_resumenes
    )
    print(f"Resumen guardado en {carpeta}")
    if resumen.estado is Estado.ABORTADO:
        print("ABORTADO: el CSV vigente no se tocó. Revisa el resumen y decide.", file=sys.stderr)
        return SALIDA_ABORTADO
    return 0


if __name__ == "__main__":
    sys.exit(main())
