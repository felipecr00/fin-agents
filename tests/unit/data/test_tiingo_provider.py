"""``TiingoPriceProvider`` con HTTP falso (``httpx.MockTransport``): nada de esto toca la red.

La forma de las respuestas (campos, fechas en el último día hábil, mes en curso etiquetado
con su fin de mes futuro, 403 por token inválido, 404 por ticker) se copió de una consulta
real del 2026-09-19.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
import pandas as pd
import pytest

from investmentsys.config import TiingoConfig, cargar_config
from investmentsys.data import (
    DatosInvalidosError,
    TiingoCredencialError,
    TiingoLimiteError,
    TiingoPriceProvider,
    TiingoTickerError,
    TiingoTimeoutError,
)
from investmentsys.data.tiingo_provider import VARIABLE_API_KEY, ultimo_mes_cerrado

HOY = date(2026, 9, 19)
KEY = "llave-de-prueba"
Manejador = Callable[[httpx.Request], httpx.Response]


def _fila(fecha: str, adj_close: float, close: float | None = None) -> dict[str, Any]:
    return {
        "date": f"{fecha}T00:00:00.000Z",
        "close": close if close is not None else adj_close,
        "adjClose": adj_close,
        "divCash": 0.0,
        "splitFactor": 1.0,
    }


# close crudo ≠ adjClose a propósito: el provider debe quedarse con el ajustado.
VOOG = [
    _fila("2026-05-29", 80.0, close=320.0),
    _fila("2026-06-30", 82.62, close=330.48),
    _fila("2026-07-31", 81.29),
    _fila("2026-08-31", 83.95),
    _fila("2026-09-30", 82.63),  # mes en curso: Tiingo lo fecha a fin de mes con el precio de hoy
]
IBIT = [_fila("2026-07-31", 35.64), _fila("2026-08-31", 44.67), _fila("2026-09-30", 42.80)]
RESPUESTAS = {"VOOG": VOOG, "IBIT": IBIT}


@pytest.fixture(scope="module")
def config() -> TiingoConfig:
    return cargar_config().datos.tiingo


def _ticker(request: httpx.Request) -> str:
    return request.url.path.split("/")[-2]


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=RESPUESTAS[_ticker(request)])


def _provider(
    config: TiingoConfig,
    manejador: Manejador,
    activos: tuple[str, ...] = ("VOOG", "IBIT"),
    esperas: list[float] | None = None,
) -> TiingoPriceProvider:
    return TiingoPriceProvider(
        activos,
        config,
        hoy=HOY,
        api_key=KEY,
        cliente=httpx.Client(transport=httpx.MockTransport(manejador)),
        dormir=(esperas if esperas is not None else []).append,
    )


# --- éxito ---------------------------------------------------------------------------


def test_usa_adjclose_y_etiqueta_cada_mes_con_su_fin_de_mes(config: TiingoConfig) -> None:
    precios = _provider(config, _ok).precios()
    assert list(precios.columns) == ["VOOG", "IBIT"]
    assert precios.index[0] == pd.Timestamp("2026-05-31")  # 2026-05-29 era el último día hábil
    assert precios.loc["2026-05-31", "VOOG"] == 80.0  # adjClose, no el close crudo (320)
    assert precios.loc["2026-06-30", "VOOG"] == 82.62


def test_descarta_el_mes_en_curso(config: TiingoConfig) -> None:
    precios = _provider(config, _ok).precios()
    assert precios.index[-1] == pd.Timestamp("2026-08-31") == ultimo_mes_cerrado(HOY)


def test_inicio_tardio_queda_como_nan_al_principio(config: TiingoConfig) -> None:
    precios = _provider(config, _ok).precios()
    assert precios["IBIT"].isna().tolist() == [True, True, False, False]
    assert _provider(config, _ok).fecha_inicio("IBIT") == date(2026, 7, 31)


def test_peticion_endpoint_eod_mensual_con_token_en_cabecera(config: TiingoConfig) -> None:
    vistas: list[httpx.Request] = []

    def manejador(request: httpx.Request) -> httpx.Response:
        vistas.append(request)
        return _ok(request)

    _provider(config, manejador, activos=("VOOG",)).precios()
    (request,) = vistas
    assert request.url.path == "/tiingo/daily/VOOG/prices"
    assert request.url.params["resampleFreq"] == "monthly"
    assert request.url.params["startDate"] == config.fecha_inicio.isoformat()
    assert request.url.params["endDate"] == "2026-08-31"  # nunca se pide el mes en curso
    assert request.headers["Authorization"] == f"Token {KEY}"
    assert KEY not in str(request.url)  # la key jamás viaja en la URL (queda en logs y proxies)


def test_descarga_una_sola_vez_y_respeta_hasta(config: TiingoConfig) -> None:
    llamadas: list[str] = []

    def manejador(request: httpx.Request) -> httpx.Response:
        llamadas.append(_ticker(request))
        return _ok(request)

    provider = _provider(config, manejador)
    recortado = provider.precios(["VOOG"], hasta=date(2026, 7, 31))
    provider.retornos_log()
    assert llamadas == ["VOOG", "IBIT"]
    assert recortado.index[-1] == pd.Timestamp("2026-07-31")
    with pytest.raises(KeyError, match="BNS"):
        provider.precios(["BNS"])


# --- credenciales ----------------------------------------------------------------------


def test_sin_api_key_falla_antes_de_pedir_nada(
    config: TiingoConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(VARIABLE_API_KEY, raising=False)
    with pytest.raises(TiingoCredencialError, match=VARIABLE_API_KEY):
        TiingoPriceProvider(("VOOG",), config, hoy=HOY)


def test_lee_la_api_key_del_entorno(config: TiingoConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VARIABLE_API_KEY, "del-entorno")
    vistas: list[str] = []

    def manejador(request: httpx.Request) -> httpx.Response:
        vistas.append(request.headers["Authorization"])
        return _ok(request)

    cliente = httpx.Client(transport=httpx.MockTransport(manejador))
    TiingoPriceProvider(("VOOG",), config, hoy=HOY, cliente=cliente).precios()
    assert vistas == ["Token del-entorno"]


@pytest.mark.parametrize("codigo", [401, 403])  # Tiingo responde 403 "Invalid token."
def test_key_rechazada_no_se_reintenta(config: TiingoConfig, codigo: int) -> None:
    esperas: list[float] = []
    llamadas: list[int] = []

    def manejador(request: httpx.Request) -> httpx.Response:
        llamadas.append(1)
        return httpx.Response(codigo, json={"detail": "Invalid token."})

    with pytest.raises(TiingoCredencialError, match=str(codigo)) as exc:
        _provider(config, manejador, esperas=esperas).precios()
    assert len(llamadas) == 1 and esperas == []
    assert KEY not in str(exc.value)


def test_ticker_desconocido(config: TiingoConfig) -> None:
    def manejador(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Error: Ticker 'NOPE' not found"})

    with pytest.raises(TiingoTickerError, match="NOPE"):
        _provider(config, manejador, activos=("NOPE",)).precios()


# --- límite de peticiones y timeout ------------------------------------------------------


def test_429_reintenta_con_backoff_exponencial_y_se_recupera(config: TiingoConfig) -> None:
    esperas: list[float] = []
    respuestas = iter([httpx.Response(429), httpx.Response(429), httpx.Response(200, json=VOOG)])

    precios = _provider(
        config, lambda _: next(respuestas), activos=("VOOG",), esperas=esperas
    ).precios()
    r = config.reintentos
    assert esperas == [r.espera_inicial_s, r.espera_inicial_s * r.base_exponencial]
    assert len(precios) == 4


def test_429_respeta_retry_after_sin_pasar_del_maximo(config: TiingoConfig) -> None:
    esperas: list[float] = []
    respuestas = iter(
        [
            httpx.Response(429, headers={"Retry-After": "17"}),
            httpx.Response(429, headers={"Retry-After": "99999"}),
            httpx.Response(200, json=VOOG),
        ]
    )
    _provider(config, lambda _: next(respuestas), activos=("VOOG",), esperas=esperas).precios()
    assert esperas == [17.0, config.reintentos.espera_maxima_s]


def test_429_persistente_agota_los_intentos(config: TiingoConfig) -> None:
    esperas: list[float] = []
    with pytest.raises(TiingoLimiteError, match="429"):
        _provider(config, lambda _: httpx.Response(429), esperas=esperas).precios()
    assert len(esperas) == config.reintentos.intentos - 1


def test_timeout_reintenta_y_luego_falla(config: TiingoConfig) -> None:
    esperas: list[float] = []

    def manejador(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lento", request=request)

    with pytest.raises(TiingoTimeoutError, match="sin respuesta"):
        _provider(config, manejador, esperas=esperas).precios()
    assert len(esperas) == config.reintentos.intentos - 1


# --- datos inválidos -------------------------------------------------------------------


def _responde(filas: list[dict[str, Any]]) -> Manejador:
    return lambda _: httpx.Response(200, json=filas)


def test_hueco_de_un_mes_es_un_error(config: TiingoConfig) -> None:
    con_hueco = [f for f in VOOG if not f["date"].startswith("2026-07")]
    with pytest.raises(DatosInvalidosError, match=r"meses faltantes: \['2026-07'\]"):
        _provider(config, _responde(con_hueco), activos=("VOOG",)).precios()


def test_mes_duplicado_es_un_error(config: TiingoConfig) -> None:
    duplicado = [*VOOG[:2], _fila("2026-06-15", 81.0), *VOOG[2:]]
    with pytest.raises(DatosInvalidosError, match=r"duplicados: \['2026-06'\]"):
        _provider(config, _responde(duplicado), activos=("VOOG",)).precios()


@pytest.mark.parametrize("malo", [0.0, -3.0, None])
def test_precio_ajustado_no_positivo_o_nulo(config: TiingoConfig, malo: float | None) -> None:
    filas = [dict(VOOG[0], adjClose=malo), *VOOG[1:]]
    with pytest.raises(DatosInvalidosError):
        _provider(config, _responde(filas), activos=("VOOG",)).precios()


def test_respuesta_vacia_o_sin_adjclose(config: TiingoConfig) -> None:
    with pytest.raises(DatosInvalidosError, match="sin observaciones"):
        _provider(config, _responde([]), activos=("VOOG",)).precios()
    sin_campo = [{"date": "2026-08-31T00:00:00.000Z", "close": 83.95}]
    with pytest.raises(DatosInvalidosError, match="adjClose"):
        _provider(config, _responde(sin_campo), activos=("VOOG",)).precios()
