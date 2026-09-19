"""``TiingoPriceProvider``: precios mensuales AJUSTADOS desde el endpoint EOD de Tiingo (ADR-011).

API verificada el 2026-09-19 en https://www.tiingo.com/documentation/end-of-day y contra el
servicio real:

- ``GET {url_base}/tiingo/daily/<ticker>/prices?startDate=…&endDate=…&resampleFreq=monthly``
  devuelve una lista JSON con ``date`` (ISO 8601; en mensual, el último día hábil lun-vie de
  cada mes), ``close`` y ``adjClose`` (ajustado por splits y dividendos), entre otros.
- Autenticación por cabecera ``Authorization: Token <key>``. La key nunca viaja en la URL.
- Un token ausente o inválido devuelve **403** ``{"detail": "Invalid token."}`` (no 401); se
  tratan igual los dos códigos.

Se usa SIEMPRE ``adjClose``: el ``close`` crudo tiene saltos en cada split y no incluye
dividendos, así que sus retornos no son retornos totales.

Solo entrega meses CERRADOS (los anteriores al mes de ``hoy``): una fila fechada a fin de mes
con el precio de mitad de mes estaría mal etiquetada y rompería la continuidad de la siguiente
actualización.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from typing import Any

import httpx
import pandas as pd

from investmentsys.config import TiingoConfig
from investmentsys.data.csv_provider import COLUMNA_FECHA
from investmentsys.data.provider import DatosInvalidosError, PriceProvider

VARIABLE_API_KEY = "TIINGO_API_KEY"
CAMPO_FECHA = "date"
CAMPO_PRECIO = "adjClose"
FRECUENCIA = "monthly"
CABECERA_RETRY_AFTER = "Retry-After"


class TiingoError(RuntimeError):
    """Fallo al obtener datos de Tiingo. Las subclases dicen cuál y qué hacer."""


class TiingoCredencialError(TiingoError):
    """Falta ``TIINGO_API_KEY`` o Tiingo la rechaza (HTTP 401/403)."""


class TiingoTickerError(TiingoError):
    """Tiingo no conoce el ticker (HTTP 404)."""


class TiingoLimiteError(TiingoError):
    """Límite de peticiones (HTTP 429) que persiste tras los reintentos.

    ``retry_after``: segundos que pidió esperar el servidor (cabecera ``Retry-After``), si los dio.
    """

    def __init__(self, mensaje: str, retry_after: float | None = None) -> None:
        super().__init__(mensaje)
        self.retry_after = retry_after


class TiingoTimeoutError(TiingoError):
    """La petición no terminó a tiempo, tras los reintentos."""


def ultimo_mes_cerrado(hoy: date) -> pd.Timestamp:
    """Fin del último mes ya terminado en ``hoy`` (el mes en curso nunca cuenta)."""
    return pd.Timestamp(hoy.replace(day=1) - timedelta(days=1))


class TiingoPriceProvider(PriceProvider):
    """Descarga perezosa (una petición por activo, en la primera consulta) y en caché.

    ``hoy`` fija qué meses están cerrados; se inyecta para que la salida sea reproducible.
    ``cliente`` y ``dormir`` se inyectan en los tests (transporte falso, sin esperas reales).
    """

    _PERIODOS_POR_ANIO = 12

    def __init__(
        self,
        activos: Sequence[str],
        config: TiingoConfig,
        *,
        hoy: date,
        api_key: str | None = None,
        cliente: httpx.Client | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        if not activos:
            raise ValueError("TiingoPriceProvider necesita al menos un activo")
        key = api_key if api_key is not None else os.environ.get(VARIABLE_API_KEY, "")
        if not key.strip():
            raise TiingoCredencialError(
                f"falta la variable de entorno {VARIABLE_API_KEY} (ver .env.example)"
            )
        self._activos = tuple(activos)
        self._config = config
        self._cierre = ultimo_mes_cerrado(hoy)
        self._cabeceras = {"Authorization": f"Token {key.strip()}", "Accept": "application/json"}
        self._cliente = cliente
        self._dormir = dormir
        self._panel: pd.DataFrame | None = None

    @property
    def periodos_por_anio(self) -> int:
        return self._PERIODOS_POR_ANIO

    def activos(self) -> tuple[str, ...]:
        return self._activos

    def precios(
        self, activos: Sequence[str] | None = None, hasta: date | None = None
    ) -> pd.DataFrame:
        columnas = list(activos) if activos is not None else list(self._activos)
        desconocidos = [a for a in columnas if a not in self._activos]
        if desconocidos:
            raise KeyError(f"activos no solicitados a Tiingo: {desconocidos}")
        df = self._descargar().loc[:, columnas]
        if hasta is not None:
            df = df.loc[df.index <= pd.Timestamp(hasta)]
            if df.empty:
                raise DatosInvalidosError(f"Tiingo: sin precios hasta {hasta}")
        return df.copy()

    # --- descarga ----------------------------------------------------------------------

    def _descargar(self) -> pd.DataFrame:
        if self._panel is None:
            cliente = self._cliente or httpx.Client(timeout=self._config.timeout_s)
            try:
                series = {a: self._serie(cliente, a) for a in self._activos}
            finally:
                if self._cliente is None:
                    cliente.close()
            panel = pd.DataFrame(series).sort_index()
            panel.index.name = COLUMNA_FECHA
            self._panel = panel
        return self._panel

    def _serie(self, cliente: httpx.Client, activo: str) -> pd.Series[float]:
        filas = self._pedir(cliente, activo)
        if not isinstance(filas, list) or not filas:
            raise DatosInvalidosError(f"Tiingo: {activo} sin observaciones")
        try:
            fechas = pd.to_datetime([str(f[CAMPO_FECHA])[:10] for f in filas], format="%Y-%m-%d")
            valores = [float(f[CAMPO_PRECIO]) for f in filas]
        except (KeyError, TypeError, ValueError) as exc:
            raise DatosInvalidosError(
                f"Tiingo: {activo} sin los campos '{CAMPO_FECHA}'/'{CAMPO_PRECIO}' esperados"
            ) from exc
        # Cada observación se etiqueta con el fin de su mes natural, como el CSV.
        meses = pd.DatetimeIndex(fechas) + pd.offsets.MonthEnd(0)
        serie = pd.Series(valores, index=meses, name=activo, dtype=float).sort_index()
        serie = serie.loc[serie.index <= self._cierre]
        if serie.empty:
            raise DatosInvalidosError(f"Tiingo: {activo} sin ningún mes cerrado")
        if serie.index.has_duplicates:
            repetidos = sorted({f"{m:%Y-%m}" for m in serie.index[serie.index.duplicated()]})
            raise DatosInvalidosError(f"Tiingo: {activo} con meses duplicados: {repetidos}")
        esperados = pd.date_range(serie.index[0], serie.index[-1], freq="ME")
        faltantes = [f"{m:%Y-%m}" for m in esperados if m not in serie.index]
        if faltantes:
            raise DatosInvalidosError(f"Tiingo: {activo} con meses faltantes: {faltantes}")
        if serie.isna().any() or (serie <= 0).any():
            raise DatosInvalidosError(f"Tiingo: {activo} con precios ajustados nulos o <= 0")
        return serie

    def _pedir(self, cliente: httpx.Client, activo: str) -> Any:
        url = f"{self._config.url_base.rstrip('/')}/tiingo/daily/{activo}/prices"
        parametros = {
            "startDate": self._config.fecha_inicio.isoformat(),
            "endDate": self._cierre.date().isoformat(),
            "resampleFreq": FRECUENCIA,
            "format": "json",
        }
        reintentos = self._config.reintentos
        ultimo: TiingoError | None = None
        for intento in range(reintentos.intentos):
            if intento:
                self._dormir(self._espera(intento, ultimo))
            try:
                respuesta = cliente.get(url, params=parametros, headers=self._cabeceras)
            except httpx.TimeoutException:
                ultimo = TiingoTimeoutError(
                    f"Tiingo: {activo} sin respuesta en {self._config.timeout_s:g} s "
                    f"({intento + 1} intentos)"
                )
                continue
            except httpx.HTTPError as exc:
                raise TiingoError(f"Tiingo: error de red con {activo}: {exc!r}") from exc
            if respuesta.status_code == httpx.codes.TOO_MANY_REQUESTS:
                ultimo = TiingoLimiteError(
                    f"Tiingo: límite de peticiones (HTTP 429) con {activo} "
                    f"({intento + 1} intentos); free tier: 50/hora, 1.000/día",
                    _retry_after(respuesta),
                )
                continue
            return self._interpretar(respuesta, activo)
        assert ultimo is not None
        raise ultimo

    def _espera(self, intento: int, ultimo: TiingoError | None) -> float:
        r = self._config.reintentos
        espera = min(r.espera_inicial_s * r.base_exponencial ** (intento - 1), r.espera_maxima_s)
        pedida = ultimo.retry_after if isinstance(ultimo, TiingoLimiteError) else None
        return min(max(espera, pedida), r.espera_maxima_s) if pedida is not None else espera

    @staticmethod
    def _interpretar(respuesta: httpx.Response, activo: str) -> Any:
        codigo = respuesta.status_code
        if codigo in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            raise TiingoCredencialError(
                f"Tiingo rechazó la API key (HTTP {codigo}): revisa {VARIABLE_API_KEY}"
            )
        if codigo == httpx.codes.NOT_FOUND:
            raise TiingoTickerError(f"Tiingo no conoce el ticker {activo} (HTTP 404)")
        if codigo != httpx.codes.OK:
            raise TiingoError(f"Tiingo: HTTP {codigo} inesperado con {activo}")
        try:
            return respuesta.json()
        except ValueError as exc:
            raise DatosInvalidosError(f"Tiingo: respuesta de {activo} no es JSON") from exc


def _retry_after(respuesta: httpx.Response) -> float | None:
    crudo = respuesta.headers.get(CABECERA_RETRY_AFTER)
    try:
        return max(float(crudo), 0.0) if crudo is not None else None
    except ValueError:
        return None
