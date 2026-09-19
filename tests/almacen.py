"""Almacén de series y Gestor de Datos de prueba, sembrados desde el fixture congelado.

Sin red: ``FuenteFalsa`` hace de Tiingo. El universo de referencia (4 activos, caps pinneadas
con procedencia ``usuario``) se construye igual que en la migración real de S7.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from investmentsys.config import Config
from investmentsys.data import CSVPriceProvider
from investmentsys.data.actualizacion import escribir_series_atomico
from investmentsys.data_manager import (
    CapFuente,
    GestorDatos,
    MetadataActivo,
    TickerInexistenteError,
)
from tests.conftest import ACTIVOS, CSV_REFERENCIA

AHORA = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
NOMBRES = {
    "VOOG": "VANGUARD S&P 500 GROWTH INDEX FUND ETF SHARES",
    "BNS": "Bank Of Nova Scotia",
    "IBIT": "iShares Bitcoin Trust",
    "VB": "Vanguard Morningstar Small-Cap ETF",
}


def panel_referencia() -> pd.DataFrame:
    return CSVPriceProvider(CSV_REFERENCIA).precios(list(ACTIVOS))


def serie_sintetica(
    ticker: str, meses: int, fin: pd.Timestamp, semilla: int = 7, vol_mensual: float = 0.05
) -> pd.Series[float]:
    """Serie mensual determinista de ``meses`` precios que termina en ``fin``."""
    rng = np.random.default_rng(semilla)
    indice = pd.date_range(end=fin, periods=meses, freq="ME")
    retornos = rng.normal(0.008, vol_mensual, size=meses)
    return pd.Series(100.0 * np.exp(np.cumsum(retornos)), index=indice, name=ticker)


@dataclass
class FuenteFalsa:
    """``FuenteActivos`` en memoria. Registra las consultas de capitalización."""

    series: dict[str, pd.Series[float]] = field(default_factory=dict)
    bolsas: dict[str, str] = field(default_factory=dict)
    caps: dict[str, CapFuente] = field(default_factory=dict)
    consultas_cap: list[str] = field(default_factory=list)

    def metadata(self, ticker: str) -> MetadataActivo:
        if ticker not in self.series:
            raise TickerInexistenteError(f"{ticker}: la fuente no lo conoce")
        serie = self.series[ticker]
        return MetadataActivo(
            ticker=ticker,
            nombre=NOMBRES.get(ticker, f"{ticker} Corp"),
            bolsa=self.bolsas.get(ticker, "NYSE"),
            fecha_inicio=serie.index[0].date(),
            fecha_fin=serie.index[-1].date(),
        )

    def capitalizacion(self, ticker: str) -> CapFuente | None:
        self.consultas_cap.append(ticker)
        return self.caps.get(ticker)

    def serie_mensual(self, ticker: str) -> pd.Series[float]:
        return self.series[ticker].copy()


def sembrar_gestor(raiz: Path, config: Config, fuente: FuenteFalsa | None = None) -> GestorDatos:
    """Gestor sobre ``raiz`` con el universo de referencia ya migrado (como en S7)."""
    fuente = fuente or FuenteFalsa()
    panel = panel_referencia()
    for a in ACTIVOS:
        fuente.series.setdefault(a, panel[a].dropna())
    gestor = GestorDatos(config, fuente, raiz=raiz, reloj=lambda: AHORA)
    escribir_series_atomico(
        panel, gestor.directorio_series, config.datos.actualizacion, "20261005T120000"
    )
    gestor.sembrar({a: fuente.metadata(a) for a in ACTIVOS})
    return gestor


def cap_fuente(valor_usd: float = 4.9e12) -> CapFuente:
    return CapFuente(
        valor_usd=valor_usd,
        as_of=date(2026, 10, 2),
        detalle="Tiingo tiingo/fundamentals/AAPL/daily (marketCap)",
    )
