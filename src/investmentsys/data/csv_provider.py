"""``CSVPriceProvider``: precios mensuales desde un CSV con columna ``fecha`` (AAAA-MM)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pandas as pd

from investmentsys.data.provider import DatosInvalidosError, PriceProvider

COLUMNA_FECHA = "fecha"
FORMATO_FECHA = "%Y-%m"


class CSVPriceProvider(PriceProvider):
    """Lee y valida el CSV una sola vez; las consultas devuelven copias.

    Reglas que se verifican al cargar (un CSV que no las cumple es un error, no un aviso):
    - existe la columna ``fecha`` y al menos un activo;
    - fechas ``AAAA-MM`` únicas, ascendentes y sin meses faltantes;
    - precios estrictamente positivos;
    - los huecos solo pueden estar al inicio de una serie (inicio tardío, p. ej. IBIT).
    """

    # Frecuencia intrínseca de la fuente, no un parámetro ajustable: por eso no va en config.
    _PERIODOS_POR_ANIO = 12

    def __init__(self, ruta: str | Path) -> None:
        self._ruta = Path(ruta)
        self._precios = self._cargar(self._ruta)

    @property
    def periodos_por_anio(self) -> int:
        return self._PERIODOS_POR_ANIO

    @property
    def ruta(self) -> Path:
        return self._ruta

    def activos(self) -> tuple[str, ...]:
        return tuple(str(c) for c in self._precios.columns)

    def precios(
        self, activos: Sequence[str] | None = None, hasta: date | None = None
    ) -> pd.DataFrame:
        columnas = list(activos) if activos is not None else list(self.activos())
        desconocidos = [a for a in columnas if a not in self._precios.columns]
        if desconocidos:
            raise KeyError(f"activos no presentes en {self._ruta.name}: {desconocidos}")
        df = self._precios.loc[:, columnas]
        if hasta is not None:
            df = df.loc[df.index <= pd.Timestamp(hasta)]
            if df.empty:
                raise DatosInvalidosError(f"sin precios hasta {hasta} en {self._ruta.name}")
        return df.copy()

    @staticmethod
    def _cargar(ruta: Path) -> pd.DataFrame:
        if not ruta.exists():
            raise FileNotFoundError(ruta)
        crudo = pd.read_csv(ruta)
        if COLUMNA_FECHA not in crudo.columns:
            raise DatosInvalidosError(f"{ruta.name}: falta la columna '{COLUMNA_FECHA}'")
        activos = [str(c) for c in crudo.columns if c != COLUMNA_FECHA]
        if not activos:
            raise DatosInvalidosError(f"{ruta.name}: no hay columnas de activos")

        try:
            fechas = pd.to_datetime(crudo[COLUMNA_FECHA].astype(str), format=FORMATO_FECHA)
        except ValueError as exc:
            raise DatosInvalidosError(
                f"{ruta.name}: fecha con formato distinto de AAAA-MM"
            ) from exc
        fechas = fechas + pd.offsets.MonthEnd(0)
        if fechas.duplicated().any():
            raise DatosInvalidosError(f"{ruta.name}: fechas duplicadas")
        if not fechas.is_monotonic_increasing:
            raise DatosInvalidosError(f"{ruta.name}: las fechas deben ir en orden ascendente")
        esperadas = pd.date_range(fechas.iloc[0], fechas.iloc[-1], freq="ME")
        if len(esperadas) != len(fechas) or not esperadas.equals(pd.DatetimeIndex(fechas)):
            raise DatosInvalidosError(f"{ruta.name}: hay meses faltantes en la serie")

        precios: pd.DataFrame = crudo[activos].apply(pd.to_numeric, errors="coerce").astype(float)
        precios.index = pd.DatetimeIndex(fechas, name=COLUMNA_FECHA)
        for activo in activos:
            serie = precios[activo]
            if serie.isna().all():
                raise DatosInvalidosError(f"{ruta.name}: {activo} no tiene ningún precio")
            desde_inicio = serie.loc[serie.first_valid_index() :]
            if desde_inicio.isna().any():
                raise DatosInvalidosError(
                    f"{ruta.name}: {activo} tiene huecos después de su primer precio"
                )
            if (desde_inicio <= 0).any():
                raise DatosInvalidosError(f"{ruta.name}: {activo} tiene precios no positivos")
        return precios
