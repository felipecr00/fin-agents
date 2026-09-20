"""``TiingoFuente`` con HTTP falso. Las respuestas se copiaron del servicio real el 2026-09-19
(tier gratuito): metadata sin moneda ni cap, ``fundamentals/meta`` solo con acciones, y
``marketCap`` restringido al DOW 30 (HTTP 400 para el resto). Ver ADR-013.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest

from investmentsys.config import TiingoConfig, cargar_config
from investmentsys.data import TiingoCredencialError
from investmentsys.data_manager import TickerInexistenteError, TiingoFuente

HOY = date(2026, 9, 19)

META = {
    "AAPL": {
        "ticker": "AAPL",
        "name": "Apple Inc",
        "description": "Apple Inc. (Apple) designs…",
        "startDate": "1980-12-12",
        "endDate": "2026-09-18",
        "exchangeCode": "NASDAQ",
    },
    "VOOG": {
        "ticker": "VOOG",
        "name": "VANGUARD S&P 500 GROWTH INDEX FUND ETF SHARES",
        "description": "The Fund employs an indexing…",
        "startDate": "2010-09-09",
        "endDate": "2026-09-18",
        "exchangeCode": "NYSE",
    },
    "BNS": {
        "ticker": "BNS",
        "name": "Bank Of Nova Scotia",
        "description": "The Bank of Nova Scotia…",
        "startDate": "2002-06-10",
        "endDate": "2026-09-18",
        "exchangeCode": "NYSE",
    },
}
FICHAS = {
    "AAPL": {"ticker": "aapl", "isActive": True, "isADR": False, "reportingCurrency": "usd"},
    "BNS": {"ticker": "bns", "isActive": True, "isADR": True, "reportingCurrency": "cad"},
    "NVDA": {"ticker": "nvda", "isActive": True, "isADR": False, "reportingCurrency": "usd"},
}
CAP_AAPL = [
    {"date": "2026-09-17T00:00:00.000Z", "marketCap": 4949638972000.0, "peRatio": 38.39},
    {"date": "2026-09-18T00:00:00.000Z", "marketCap": 4936860972280.0, "peRatio": 38.29},
]
ERROR_DOW30 = {
    "detail": "Error: Free and Power plans are limited to the DOW 30. If you would like access "
    "to all supported tickers, then please E-mail support@tiingo.com…"
}


# S10: `tiingo/daily/<t>/prices` diario, copiado del servicio real el 2026-09-20 (recortado).
DIARIO_BNS = [
    {"date": "2026-07-06T00:00:00.000Z", "close": 90.10, "adjClose": 89.31, "divCash": 0.0},
    {"date": "2026-07-07T00:00:00.000Z", "close": 89.55, "adjClose": 89.55, "divCash": 0.803},
    {"date": "2026-09-17T00:00:00.000Z", "close": 93.80, "adjClose": 93.80, "divCash": 0.0},
    {"date": "2026-09-18T00:00:00.000Z", "close": 94.07, "adjClose": 94.07, "divCash": 0.0},
]
PEDIDOS_DIARIOS: list[str] = []


def _manejador(request: httpx.Request) -> httpx.Response:
    ruta = request.url.path
    if ruta.endswith("/prices"):
        ticker = ruta.split("/")[3]
        PEDIDOS_DIARIOS.append(f"{ticker} desde {request.url.params['startDate']}")
        if ticker != "BNS":
            return httpx.Response(404, json={"detail": "Not found."})
        desde = request.url.params["startDate"]
        return httpx.Response(200, json=[f for f in DIARIO_BNS if f["date"][:10] >= desde])
    if ruta == "/tiingo/fundamentals/meta":
        pedido = request.url.params["tickers"].upper()
        return httpx.Response(200, json=[FICHAS[pedido]] if pedido in FICHAS else [])
    if ruta.startswith("/tiingo/fundamentals/"):
        ticker = ruta.split("/")[3]
        if ticker == "AAPL":
            return httpx.Response(200, json=CAP_AAPL)
        return httpx.Response(400, json=ERROR_DOW30)
    ticker = ruta.split("/")[3]
    if ticker in META:
        return httpx.Response(200, json=META[ticker])
    return httpx.Response(404, json={"detail": "Not found."})


@pytest.fixture(scope="module")
def config() -> TiingoConfig:
    return cargar_config().datos.tiingo


def _fuente(config: TiingoConfig, manejador: Any = _manejador) -> TiingoFuente:
    cliente = httpx.Client(transport=httpx.MockTransport(manejador))
    return TiingoFuente(config, hoy=HOY, api_key="llave", cliente=cliente, dormir=lambda _: None)


def test_metadata(config: TiingoConfig) -> None:
    meta = _fuente(config).metadata("VOOG")
    assert meta.nombre.startswith("VANGUARD") and meta.bolsa == "NYSE"
    assert meta.fecha_inicio == date(2010, 9, 9) and meta.fecha_fin == date(2026, 9, 18)


def test_ticker_inexistente(config: TiingoConfig) -> None:
    with pytest.raises(TickerInexistenteError, match="NOEXISTE"):
        _fuente(config).metadata("NOEXISTE")


def test_capitalizacion_de_accion_del_dow30(config: TiingoConfig) -> None:
    cap = _fuente(config).capitalizacion("AAPL")
    assert cap is not None
    assert cap.valor_usd == 4936860972280.0 and cap.as_of == date(2026, 9, 18)  # la más reciente
    assert cap.detalle == "Tiingo tiingo/fundamentals/AAPL/daily (marketCap)"


@pytest.mark.parametrize(
    ("ticker", "por_que"),
    [
        ("VOOG", "ETF: no aparece en fundamentals/meta"),
        ("BNS", "ADR que reporta en CAD: tipo incorrecto aunque el plan lo diera"),
        ("NVDA", "acción fuera del DOW 30: el plan gratuito responde 400"),
    ],
)
def test_sin_capitalizacion_de_calidad_devuelve_none(
    config: TiingoConfig, ticker: str, por_que: str
) -> None:
    assert _fuente(config).capitalizacion(ticker) is None, por_que


def test_bns_ni_siquiera_consulta_el_marketcap(config: TiingoConfig) -> None:
    rutas: list[str] = []

    def espia(request: httpx.Request) -> httpx.Response:
        rutas.append(request.url.path)
        return _manejador(request)

    _fuente(config, espia).capitalizacion("BNS")
    assert rutas == ["/tiingo/fundamentals/meta"]


def test_credencial_rechazada_no_se_confunde_con_sin_dato(config: TiingoConfig) -> None:
    fuente = _fuente(config, lambda _: httpx.Response(403, json={"detail": "Invalid token."}))
    with pytest.raises(TiingoCredencialError):
        fuente.capitalizacion("AAPL")


def test_la_key_viaja_en_la_cabecera_nunca_en_la_url(config: TiingoConfig) -> None:
    vistas: list[httpx.Request] = []

    def espia(request: httpx.Request) -> httpx.Response:
        vistas.append(request)
        return _manejador(request)

    _fuente(config, espia).capitalizacion("AAPL")
    assert all(r.headers["Authorization"] == "Token llave" for r in vistas)
    assert all("llave" not in str(r.url) for r in vistas)


# ------------------------------------------------------------ datos diarios (S10, ADR-020)
def test_dividendos_son_los_dias_con_div_cash_en_orden(config: TiingoConfig) -> None:
    (pago,) = _fuente(config).dividendos("BNS", date(2026, 1, 1))
    assert pago.fecha_ex == date(2026, 7, 7) and pago.monto_usd_por_accion == 0.803
    assert _fuente(config).dividendos("BNS", date(2026, 8, 1)) == ()


def test_ultimo_cierre_crudo_y_ajustado(config: TiingoConfig) -> None:
    cierre = _fuente(config).ultimo_cierre("BNS")
    assert cierre is not None and cierre.fecha == date(2026, 9, 18)
    assert cierre.cierre == 94.07 and cierre.cierre_ajustado == 94.07


def test_una_sola_descarga_diaria_por_ticker_si_la_ventana_ya_esta_cubierta(
    config: TiingoConfig,
) -> None:
    """Cuota: 50 peticiones/hora. Pedir cierres tras dividendos no vuelve a la red."""
    PEDIDOS_DIARIOS.clear()
    fuente = _fuente(config)
    fuente.dividendos("BNS", date(2026, 1, 1))
    fuente.ultimo_cierre("BNS")
    fuente.dividendos("BNS", date(2026, 6, 1))
    assert PEDIDOS_DIARIOS == ["BNS desde 2026-01-01"]


def test_datos_diarios_de_un_ticker_inexistente(config: TiingoConfig) -> None:
    with pytest.raises(TickerInexistenteError, match="NOEXISTE"):
        _fuente(config).dividendos("NOEXISTE", date(2026, 1, 1))
