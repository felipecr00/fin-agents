"""Lo que el Gestor de Datos necesita de una fuente de mercado. Sin red y sin Tiingo aquí."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

import pandas as pd


class TickerInexistenteError(LookupError):
    """La fuente no conoce el ticker."""


@dataclass(frozen=True)
class MetadataActivo:
    ticker: str
    nombre: str
    bolsa: str
    fecha_inicio: date
    fecha_fin: date


@dataclass(frozen=True)
class CapFuente:
    """Capitalización del tipo correcto (acción) tal como la publica la fuente."""

    valor_usd: float
    as_of: date
    detalle: str
    """Endpoint y campo de origen; va a ``AssetDiagnostic.prior_fuente_detalle``."""


@dataclass(frozen=True)
class Dividendo:
    """Un pago ya ocurrido: la fuente solo publica historia, no el calendario futuro."""

    fecha_ex: date
    monto_usd_por_accion: float


@dataclass(frozen=True)
class CierreDiario:
    """Último cierre publicado: crudo y ajustado por splits y dividendos."""

    fecha: date
    cierre: float
    cierre_ajustado: float


class FuenteActivos(Protocol):
    def metadata(self, ticker: str) -> MetadataActivo:
        """Lanza ``TickerInexistenteError`` si la fuente no conoce el ticker."""

    def capitalizacion(self, ticker: str) -> CapFuente | None:
        """``None`` si la fuente no la expone con calidad (ETF, ADR, plan sin acceso…)."""

    def serie_mensual(self, ticker: str) -> pd.Series[float]:
        """Precios mensuales AJUSTADOS de meses cerrados, índice a fin de mes."""

    def dividendos(self, ticker: str, desde: date) -> tuple[Dividendo, ...]:
        """Ex-dividendos de ``ticker`` desde ``desde``, en orden cronológico (S10)."""

    def ultimo_cierre(self, ticker: str) -> CierreDiario | None:
        """``None`` si la fuente no tiene cierres recientes de ``ticker`` (S10)."""
