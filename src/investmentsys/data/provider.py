"""Interfaz abstracta de acceso a precios.

Toda fuente de datos (CSV hoy, mercado en vivo después) implementa ``PriceProvider``.
El parámetro ``hasta`` es la guarda de look-ahead de la capa de datos: nada posterior a
esa fecha sale del proveedor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date
from typing import cast

import numpy as np
import pandas as pd


class DatosInvalidosError(ValueError):
    """La fuente de precios no cumple el formato esperado."""


class PriceProvider(ABC):
    """Series de precios de cierre, una columna por activo, índice de fechas ascendente."""

    @property
    @abstractmethod
    def periodos_por_anio(self) -> int:
        """Frecuencia de la serie: 12 para mensual, 252 para diaria."""

    @abstractmethod
    def activos(self) -> tuple[str, ...]:
        """Activos disponibles, en el orden de la fuente."""

    @abstractmethod
    def precios(
        self, activos: Sequence[str] | None = None, hasta: date | None = None
    ) -> pd.DataFrame:
        """Precios hasta ``hasta`` inclusive (o todos), columnas en el orden de ``activos``.

        Un activo que cotiza desde más tarde que el resto tiene ``NaN`` antes de su
        primera observación; nunca hay ``NaN`` después de ella.
        """

    def fecha_inicio(self, activo: str) -> date:
        """Primera fecha con precio para ``activo``."""
        serie = self.precios([activo])[activo]
        primera = serie.first_valid_index()
        if primera is None:
            raise DatosInvalidosError(f"{activo}: sin observaciones")
        return cast(pd.Timestamp, primera).date()

    def retornos_log(
        self, activos: Sequence[str] | None = None, hasta: date | None = None
    ) -> pd.DataFrame:
        """Retornos logarítmicos ``ln(P_t / P_{t-1})``; se descarta el primer período.

        Un activo de inicio tardío conserva ``NaN`` hasta su segundo precio.
        """
        precios = self.precios(activos, hasta)
        log_precios = pd.DataFrame(
            np.log(precios.to_numpy(dtype=float)), index=precios.index, columns=precios.columns
        )
        return log_precios.diff().iloc[1:]
