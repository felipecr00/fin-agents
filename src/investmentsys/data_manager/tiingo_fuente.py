"""``TiingoFuente``: metadata, capitalización y serie mensual desde Tiingo (ADR-011, ADR-013).

Endpoints verificados contra el servicio real el 2026-09-19 (tier gratuito; ver ADR-013):

- ``GET tiingo/daily/<ticker>`` → ``ticker, name, startDate, endDate, exchangeCode``; 404 si no
  existe. No trae moneda ni capitalización.
- ``GET tiingo/daily/<ticker>/prices?startDate=…`` → diario: ``close, adjClose, divCash,
  splitFactor``… (verificado el 2026-09-20, S10). ``divCash > 0`` marca la fecha ex-dividendo.
  Solo historia: la fuente no publica dividendos futuros.
- ``GET tiingo/fundamentals/meta?tickers=<t>`` → lista; solo acciones (un ETF no aparece):
  ``isActive, isADR, reportingCurrency``.
- ``GET tiingo/fundamentals/<ticker>/daily?startDate=…`` → ``[{date, marketCap, …}]`` en US$.
  Fuera del DOW 30, los planes Free y Power responden HTTP 400: aquí eso es "sin dato".

Criterio conservador de "capitalización del tipo correcto": acción activa, no ADR, que reporta
en USD. Todo lo demás devuelve ``None`` y la cap la aporta el usuario: nada de fuentes
secundarias improvisadas.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import httpx
import pandas as pd

from investmentsys.config import TiingoConfig
from investmentsys.data.tiingo_provider import (
    ClienteTiingo,
    TiingoPriceProvider,
    TiingoTickerError,
    ultimo_mes_cerrado,
)
from investmentsys.data_manager.fuente import (
    CapFuente,
    CierreDiario,
    Dividendo,
    MetadataActivo,
    TickerInexistenteError,
)

RUTA_FUNDAMENTALS_META = "tiingo/fundamentals/meta"
MONEDA_REPORTE_ADMITIDA = "usd"
# Días hacia atrás que se piden para encontrar la última capitalización publicada (fines de
# semana y festivos). Constante del protocolo de consulta, no un parámetro financiero.
DIAS_BUSQUEDA_CAP = 10


class TiingoFuente:
    def __init__(
        self,
        config: TiingoConfig,
        *,
        hoy: date,
        api_key: str | None = None,
        cliente: httpx.Client | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._hoy = hoy
        self._api_key = api_key
        self._cliente = cliente
        self._dormir = dormir
        self._http = ClienteTiingo(config, api_key, dormir)
        self._diarios: dict[str, tuple[date, list[dict[str, Any]]]] = {}

    def metadata(self, ticker: str) -> MetadataActivo:
        try:
            crudo = self._get(f"tiingo/daily/{ticker}", {}, ticker)
        except TiingoTickerError as exc:
            raise TickerInexistenteError(f"{ticker}: la fuente (Tiingo) no lo conoce") from exc
        if not isinstance(crudo, dict) or not crudo.get("startDate") or not crudo.get("endDate"):
            raise TickerInexistenteError(
                f"{ticker}: Tiingo lo conoce pero no tiene datos de precio"
            )
        return MetadataActivo(
            ticker=str(crudo.get("ticker") or ticker).upper(),
            nombre=str(crudo.get("name") or ticker),
            bolsa=str(crudo.get("exchangeCode") or ""),
            fecha_inicio=date.fromisoformat(str(crudo["startDate"])[:10]),
            fecha_fin=date.fromisoformat(str(crudo["endDate"])[:10]),
        )

    def capitalizacion(self, ticker: str) -> CapFuente | None:
        meta = self._get(RUTA_FUNDAMENTALS_META, {"tickers": ticker}, ticker)
        fichas = [f for f in meta or [] if str(f.get("ticker", "")).upper() == ticker.upper()]
        if not fichas:
            return None  # no es una acción (ETF, trust…): la cap la aporta el usuario
        ficha = fichas[0]
        if (
            not ficha.get("isActive")
            or ficha.get("isADR")
            or str(ficha.get("reportingCurrency", "")).lower() != MONEDA_REPORTE_ADMITIDA
        ):
            return None
        ruta = f"tiingo/fundamentals/{ticker}/daily"
        desde = self._hoy - timedelta(days=DIAS_BUSQUEDA_CAP)
        filas = self._get(
            ruta,
            {"startDate": desde.isoformat(), "endDate": self._hoy.isoformat()},
            ticker,
            codigos_sin_dato=(httpx.codes.BAD_REQUEST,),  # plan sin acceso a este ticker
        )
        validas = [f for f in filas or [] if _positivo(f.get("marketCap"))]
        if not validas:
            return None
        ultima = max(validas, key=lambda f: str(f["date"]))
        return CapFuente(
            valor_usd=float(ultima["marketCap"]),
            as_of=date.fromisoformat(str(ultima["date"])[:10]),
            detalle=f"Tiingo {ruta} (marketCap)",
        )

    def serie_mensual(self, ticker: str) -> pd.Series[float]:
        proveedor = TiingoPriceProvider(
            [ticker],
            self._config,
            hoy=self._hoy,
            api_key=self._api_key,
            cliente=self._cliente,
            dormir=self._dormir,
        )
        return proveedor.precios([ticker])[ticker]

    def dividendos(self, ticker: str, desde: date) -> tuple[Dividendo, ...]:
        return tuple(
            Dividendo(date.fromisoformat(str(f["date"])[:10]), float(f["divCash"]))
            for f in self._diario(ticker, desde)
            if _positivo(f.get("divCash"))
        )

    def ultimo_cierre(self, ticker: str) -> CierreDiario | None:
        filas = self._diario(ticker, self._hoy - timedelta(days=DIAS_BUSQUEDA_CAP))
        validas = [f for f in filas if _positivo(f.get("close")) and _positivo(f.get("adjClose"))]
        if not validas:
            return None
        ultima = max(validas, key=lambda f: str(f["date"]))
        return CierreDiario(
            fecha=date.fromisoformat(str(ultima["date"])[:10]),
            cierre=float(ultima["close"]),
            cierre_ajustado=float(ultima["adjClose"]),
        )

    def _diario(self, ticker: str, desde: date) -> list[dict[str, Any]]:
        """Filas diarias desde la más antigua pedida; una sola descarga por ticker."""
        previo = self._diarios.get(ticker)
        if previo is None or desde < previo[0]:
            try:
                filas = self._get(
                    f"tiingo/daily/{ticker}/prices",
                    {"startDate": desde.isoformat(), "endDate": self._hoy.isoformat()},
                    ticker,
                )
            except TiingoTickerError as exc:
                raise TickerInexistenteError(f"{ticker}: la fuente (Tiingo) no lo conoce") from exc
            previo = (desde, [f for f in filas or [] if isinstance(f, dict) and f.get("date")])
            self._diarios[ticker] = previo
        return [f for f in previo[1] if str(f["date"])[:10] >= desde.isoformat()]

    @property
    def ultimo_mes_cerrado(self) -> pd.Timestamp:
        return ultimo_mes_cerrado(self._hoy)

    def _get(
        self,
        ruta: str,
        parametros: dict[str, str],
        ticker: str,
        codigos_sin_dato: tuple[int, ...] = (),
    ) -> Any:
        cliente = self._cliente or httpx.Client(timeout=self._config.timeout_s)
        try:
            return self._http.get(cliente, ruta, parametros, ticker, codigos_sin_dato)
        finally:
            if self._cliente is None:
                cliente.close()


def _positivo(valor: Any) -> bool:
    return isinstance(valor, int | float) and valor > 0
