"""Almacén de series y Gestor de Datos de prueba, sembrados desde el fixture congelado.

Sin red: ``FuenteFalsa`` hace de Tiingo. El universo de referencia (4 activos, caps pinneadas
con procedencia ``usuario``) se construye igual que en la migración real de S7.
"""

from __future__ import annotations

import functools
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, TypeVar

import numpy as np
import pandas as pd
from pydantic import BaseModel

from investmentsys.config import Config, cargar_config
from investmentsys.contracts import (
    AssetDiagnostic,
    Frecuencia,
    OrigenActivo,
    PriorProvenance,
    SessionConstraints,
    Universe,
)
from investmentsys.data import CSVPriceProvider
from investmentsys.data.actualizacion import escribir_series_atomico
from investmentsys.data_manager import (
    CapFuente,
    CierreDiario,
    Dividendo,
    GestorDatos,
    MetadataActivo,
    TickerInexistenteError,
)
from investmentsys.portfolio import sesion_por_defecto
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
    pagos: dict[str, tuple[Dividendo, ...]] = field(default_factory=dict)
    cierres: dict[str, CierreDiario] = field(default_factory=dict)

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

    def dividendos(self, ticker: str, desde: date) -> tuple[Dividendo, ...]:
        return tuple(d for d in self.pagos.get(ticker, ()) if d.fecha_ex >= desde)

    def ultimo_cierre(self, ticker: str) -> CierreDiario | None:
        return self.cierres.get(ticker)


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


# ---------------------------------------------------------------- universos sin disco
@functools.cache
def universo_referencia() -> Universe:
    """El universo de referencia (4 activos, caps pinneadas) sobre el fixture congelado."""
    with tempfile.TemporaryDirectory() as carpeta:
        return sembrar_gestor(Path(carpeta), cargar_config()).universo()


def universo_de(activos: Sequence[str], cap: float = 1.0) -> Universe:
    """Universo mínimo y válido con ``activos`` (caps de usuario iguales)."""
    diagnosticos = [
        AssetDiagnostic(
            ticker=a,
            nombre=f"{a} de prueba",
            moneda="USD",
            fecha_inicio_datos=date(2021, 9, 30),
            fecha_fin_datos=date(2026, 9, 30),
            frecuencia=Frecuencia.MENSUAL,
            meses_disponibles=61,
            apto=True,
            prior_cap=cap,
            prior_provenance=PriorProvenance.USUARIO,
            prior_fuente_detalle="prueba",
            prior_as_of=date(2026, 9, 16),
        )
        for a in activos
    ]
    return Universe.crear(diagnosticos, dict.fromkeys(activos, OrigenActivo.CONFIG_INICIAL))


def sesion_de(universo: Universe) -> SessionConstraints:
    return sesion_por_defecto(universo, cargar_config().optimizacion)


M = TypeVar("M", bound=BaseModel)


def sellar(contrato: M, universo: Universe) -> M:
    """Copia de ``contrato`` sellada con ``universo`` (lo que hacen las herramientas)."""
    return type(contrato).model_validate(
        {**contrato.model_dump(), "universe_version": universo.version}
    )


def diagnosticar(tools: Any, pesos: dict[str, float] | None, ctx: Any) -> dict[str, Any]:
    """Como llega en producción (ADR-019): los pesos del usuario van al estado, no a la tool."""
    from investmentsys.tools.estado import CLAVE_PESOS_EN_CONSULTA

    ctx.state[CLAVE_PESOS_EN_CONSULTA] = pesos
    salida: dict[str, Any] = tools.diagnosticar_cartera(ctx)
    return salida


# ---------------------------------------------------------------- mundo de un caso de eval
TICKERS_DE_EVAL = ("AAPL", "QQQ")  # AAPL: acción con cap en la fuente; QQQ: ETF sin cap


def fuente_de_eval() -> FuenteFalsa:
    fin = panel_referencia().index[-1]
    return FuenteFalsa(
        series={
            "AAPL": serie_sintetica("AAPL", 80, fin),
            "QQQ": serie_sintetica("QQQ", 80, fin, semilla=11),
        },
        caps={"AAPL": cap_fuente()},
        pagos={
            "BNS": (
                Dividendo(date(2026, 4, 7), 0.792),
                Dividendo(date(2026, 7, 7), 0.803),
            )
        },
        cierres={
            "VOOG": CierreDiario(date(2026, 10, 2), 412.35, 412.35),
            "BNS": CierreDiario(date(2026, 10, 2), 94.07, 93.41),
        },
    )


def mundo_director(raiz: Path, config: Config, modelo: Any = None) -> Any:
    """Almacén aislado + Director para UN caso del evalset (ADR-015). Sin red ni ``data/``."""
    from investmentsys.agents.director import INSTRUCCION, crear_director
    from investmentsys.agents.esceptico import NOMBRE as ESCEPTICO
    from investmentsys.agents.estadistico import NOMBRE as ESTADISTICO
    from investmentsys.evaluacion.director import Mundo

    gestor = sembrar_gestor(raiz / "almacen", config, fuente_de_eval())
    runs = raiz / "runs"
    # El MISMO Director que sirve apps/equipo: lienzo en blanco (ADR-023). Los casos que no son
    # sobre la apertura declaran `sesion: guardado` (por defecto) y el arnés lo deja cargado.
    director = crear_director(config, gestor.provider(), gestor, modelo, runs, mesa_limpia=True)
    return Mundo(
        director=director,
        gestor=gestor,
        runs=runs,
        respaldo_fijo=(INSTRUCCION,),
        personas=(ESTADISTICO, ESCEPTICO),
    )
