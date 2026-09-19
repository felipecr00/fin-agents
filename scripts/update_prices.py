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
from investmentsys.contracts import Universe
from investmentsys.data import DatosInvalidosError, TiingoError, TiingoPriceProvider
from investmentsys.data.actualizacion import (
    Estado,
    actualizar_precios,
    formatear_resumen,
    guardar_resumen,
)
from investmentsys.data_manager import GestorDatos

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
        # S7: se actualiza el universo VIGENTE (incluye lo incorporado en sesión). Un activo que
        # entró con historia corta puede empezar tarde: ya lo advierte su diagnóstico.
        gestor = GestorDatos(config)
        previo = Universe.model_validate_json(gestor.ruta_universo.read_text(encoding="utf-8"))
        inicio = config.datos.tiingo.fecha_inicio
        reglas = config.datos.actualizacion
        tardios = tuple(
            d.ticker
            for d in previo.diagnosticos
            if (d.fecha_inicio_datos.year, d.fecha_inicio_datos.month) > (inicio.year, inicio.month)
        )
        reglas = reglas.model_copy(
            update={"activos_inicio_tardio": tuple({*reglas.activos_inicio_tardio, *tardios})}
        )
        fuente = TiingoPriceProvider(previo.activos, config.datos.tiingo, hoy=hoy)
        resumen = actualizar_precios(
            fuente,
            previo.activos,
            gestor.directorio_series,
            reglas,
            config.datos.tiingo.fecha_inicio,
            hoy=hoy,
            ahora=ahora,
            nombre_fuente="tiingo (EOD, resampleFreq=monthly, adjClose)",
            simular=args.dry_run,
            aceptar_discrepancias=args.aceptar_discrepancias,
        )
    except (TiingoError, DatosInvalidosError) as exc:
        print(f"ERROR de la fuente; las series vigentes no se tocaron.\n{exc}", file=sys.stderr)
        return SALIDA_FUENTE

    print(formatear_resumen(resumen))
    if resumen.estado is Estado.ESCRITO:
        nuevo = gestor.sincronizar()  # datos nuevos = universo nuevo: lo anterior queda obsoleto
        print(f"Universo re-diagnosticado: {previo.version[:12]} → {nuevo.version[:12]}")
    carpeta = guardar_resumen(
        resumen, RAIZ_PROYECTO / config.datos.actualizacion.directorio_resumenes
    )
    print(f"Resumen guardado en {carpeta}")
    if resumen.estado is Estado.ABORTADO:
        print(
            "ABORTADO: las series vigentes no se tocaron. Revisa el resumen y decide.",
            file=sys.stderr,
        )
        return SALIDA_ABORTADO
    return 0


if __name__ == "__main__":
    sys.exit(main())
