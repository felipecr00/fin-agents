"""Gestor de Datos por línea de comandos (S7; en S8 lo conduce el Director conversacional).

    uv run python scripts/universo.py diagnosticar
    uv run python scripts/universo.py resolver AAPL
    uv run python scripts/universo.py incorporar QQQ --cap 22.0 --metodologia "cap del Nasdaq-100"
    uv run python scripts/universo.py incorporar QQQ --aceptar-neutral
    uv run python scripts/universo.py refrescar-cap BNS --cap 0.12 --metodologia "cap bursátil"
    uv run python scripts/universo.py aceptar-neutral
    uv run python scripts/universo.py retirar BNS

Las caps van en US$ billones (10^12). `resolver` y `diagnosticar` no modifican nada; el resto
cambia `data/universo.json` (otra `universe_version`) y deja rastro en el historial.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from dotenv import load_dotenv

from investmentsys.config import RAIZ_PROYECTO, cargar_config
from investmentsys.data import DatosInvalidosError, TiingoError
from investmentsys.data_manager import GestorDatos, GestorError, TiingoFuente

SALIDA_ERROR = 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="accion", required=True)
    sub.add_parser("diagnosticar")
    sub.add_parser("aceptar-neutral")
    sub.add_parser("resolver").add_argument("ticker")
    sub.add_parser("retirar").add_argument("ticker")
    for nombre in ("incorporar", "refrescar-cap"):
        p = sub.add_parser(nombre)
        p.add_argument("ticker")
        p.add_argument("--cap", type=float, default=None, help="US$ billones (10^12)")
        p.add_argument("--metodologia", default=None)
        if nombre == "incorporar":
            p.add_argument("--aceptar-neutral", action="store_true")
    args = parser.parse_args()

    load_dotenv(RAIZ_PROYECTO / ".env")
    config = cargar_config()
    try:
        con_fuente = args.accion in ("resolver", "incorporar", "refrescar-cap")
        fuente = TiingoFuente(config.datos.tiingo, hoy=date.today()) if con_fuente else None
        gestor = GestorDatos(config, fuente)
        if args.accion == "resolver":
            print(gestor.resolver(args.ticker).model_dump_json(indent=2))
            return 0
        if args.accion == "incorporar":
            gestor.incorporar(
                args.ticker, args.cap, args.metodologia, aceptar_neutral=args.aceptar_neutral
            )
        elif args.accion == "refrescar-cap":
            gestor.refrescar_cap(args.ticker.upper(), args.cap, args.metodologia)
        elif args.accion == "retirar":
            gestor.retirar(args.ticker)
        elif args.accion == "aceptar-neutral":
            gestor.aceptar_prior_neutral()
        print(gestor.diagnosticar().model_dump_json(indent=2))
    except (GestorError, TiingoError, DatosInvalidosError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return SALIDA_ERROR
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
