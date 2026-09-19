"""``SeriesPriceProvider``: un CSV por activo en ``data/series/<TICKER>.csv`` (S7, ADR-012).

Cada archivo tiene el formato de ``CSVPriceProvider`` con una sola columna (``fecha,<TICKER>``),
así que hereda sus reglas: fechas ``AAAA-MM`` únicas, ascendentes y sin huecos, precios > 0.
El panel se arma uniendo las series pedidas; un activo que empieza más tarde tiene ``NaN`` al
inicio, y **todas deben terminar en el mismo mes**: un almacén a medio actualizar es un error,
no un panel con ``NaN`` al final.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pandas as pd

from investmentsys.config import RAIZ_PROYECTO, Config
from investmentsys.data.csv_provider import COLUMNA_FECHA, CSVPriceProvider
from investmentsys.data.provider import DatosInvalidosError, PriceProvider

EXTENSION = ".csv"
# Un ticker no admite "_" (contracts.Ticker): los respaldos nunca se confunden con una serie.
SEPARADOR_NO_TICKER = "_"


def ruta_serie(directorio: Path, activo: str) -> Path:
    return directorio / f"{activo}{EXTENSION}"


class SeriesPriceProvider(PriceProvider):
    """Carga perezosa y en caché: cada serie se lee y valida una vez."""

    _PERIODOS_POR_ANIO = 12

    def __init__(self, directorio: str | Path, activos: Sequence[str] | None = None) -> None:
        self._directorio = Path(directorio)
        if not self._directorio.is_dir():
            raise FileNotFoundError(self._directorio)
        self._activos = tuple(activos) if activos is not None else self._descubrir()
        self._series: dict[str, pd.Series[float]] = {}

    @property
    def periodos_por_anio(self) -> int:
        return self._PERIODOS_POR_ANIO

    @property
    def directorio(self) -> Path:
        return self._directorio

    def activos(self) -> tuple[str, ...]:
        return self._activos

    def precios(
        self, activos: Sequence[str] | None = None, hasta: date | None = None
    ) -> pd.DataFrame:
        columnas = list(activos) if activos is not None else list(self._activos)
        if not columnas:
            raise DatosInvalidosError(f"{self._directorio}: no hay series")
        panel = pd.DataFrame({a: self._serie(a) for a in columnas}).sort_index()
        panel = panel.loc[:, columnas]
        # Sin frecuencia inferida: el mismo índice que entrega CSVPriceProvider.
        panel.index = pd.DatetimeIndex(panel.index.to_numpy(), name=COLUMNA_FECHA)
        ultimo = panel.index[-1]
        atrasadas = [a for a in columnas if bool(pd.isna(panel[a].to_numpy()[-1]))]
        if atrasadas:
            raise DatosInvalidosError(
                f"{self._directorio.name}: series que no llegan a {ultimo:%Y-%m}: {atrasadas} "
                "(almacén a medio actualizar: repite make update-prices)"
            )
        if hasta is not None:
            panel = panel.loc[panel.index <= pd.Timestamp(hasta)]
            if panel.empty:
                raise DatosInvalidosError(f"sin precios hasta {hasta} en {self._directorio.name}")
        return panel.copy()

    def _serie(self, activo: str) -> pd.Series[float]:
        if activo not in self._series:
            ruta = ruta_serie(self._directorio, activo)
            if not ruta.is_file():
                raise KeyError(f"sin serie para {activo} en {self._directorio}: incorpóralo antes")
            proveedor = CSVPriceProvider(ruta)
            if proveedor.activos() != (activo,):
                raise DatosInvalidosError(
                    f"{ruta.name}: se esperaba la única columna '{activo}', "
                    f"hay {proveedor.activos()}"
                )
            self._series[activo] = proveedor.precios()[activo].dropna()
        return self._series[activo]

    def _descubrir(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                p.stem
                for p in self._directorio.glob(f"*{EXTENSION}")
                if SEPARADOR_NO_TICKER not in p.stem and not p.name.startswith(".")
            )
        )


def provider_de_config(config: Config, raiz: Path = RAIZ_PROYECTO) -> SeriesPriceProvider:
    """El almacén vivo (``datos.directorio_series``). El pipeline nunca lee de la red (ADR-011)."""
    return SeriesPriceProvider(raiz / config.datos.directorio_series)
