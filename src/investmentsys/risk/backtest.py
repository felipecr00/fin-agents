"""Backtest walk-forward con rebalanceo y costos. Código puro: sin ADK, sin LLM.

Convenciones (ADR-004):

- ``precios`` es un panel de cierres (una columna por activo, índice temporal ascendente).
  Un activo de inicio tardío tiene ``NaN`` antes de su primer precio, como lo entrega
  ``PriceProvider``.
- Una **estrategia** es una función ``(precios, fecha) -> pesos``. Recibe el panel completo y
  la fecha de decisión, y solo puede usar filas ≤ ``fecha``. Esa obligación no se confía:
  ``risk.look_ahead.verificar_look_ahead`` la comprueba por invariancia al futuro.
- En cada fecha de decisión ``d_{k-1}`` la estrategia fija los pesos objetivo; el retorno del
  período ``k`` es el de ``d_{k-1} → d_k`` con esos pesos. Nada posterior a ``d_{k-1}``
  interviene en la decisión: eso es lo que hace al backtest *walk-forward*.
- Rebalanceo: cada ``PERIODOS_ENTRE_REBALANCEOS[rebalanceo]`` períodos se vuelve a los pesos
  objetivo; entre rebalanceos los pesos derivan con los retornos. Turnover =
  Σ|w_objetivo − w_derivado| (compras más ventas) y costo = turnover × bps / 10 000, cobrado
  en CADA rebalanceo: reduce el capital al inicio del período.
- Un activo sin precio en ``d_{k-1}`` no puede comprarse: su peso objetivo se reparte
  proporcionalmente entre los disponibles (así el portafolio de referencia se evalúa sobre
  toda la muestra aunque IBIT cotice desde 2024-01).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date

import numpy as np
import numpy.typing as npt
import pandas as pd

from investmentsys.contracts.common import TOLERANCIA_NUMERICA

Vector = npt.NDArray[np.float64]
Estrategia = Callable[[pd.DataFrame, date], Mapping[str, float]]
"""``(precios, fecha_decision) -> pesos``. Solo puede usar filas de ``precios`` ≤ ``fecha``."""

PUNTOS_BASICOS_POR_UNIDAD = 10_000.0
PERIODOS_ENTRE_REBALANCEOS: dict[str, int] = {"mensual": 1}
"""Períodos del panel entre rebalanceos, por valor de ``config.yaml: validacion.rebalanceo``."""

# Mínimo de fechas para que exista al menos un período de retorno.
_MIN_FECHAS = 2


@dataclass(frozen=True)
class ResultadoBacktest:
    """Series alineadas del backtest. ``valor`` empieza en 1.0 en la primera fecha."""

    activos: tuple[str, ...]
    fechas_decision: pd.DatetimeIndex
    """``d_0 … d_{n-1}``: fechas en que se decidieron los pesos de cada período."""
    retornos: pd.Series
    """Retorno simple neto de costos de cada período, indexado por ``d_1 … d_n``."""
    pesos: pd.DataFrame
    """Pesos vigentes al inicio de cada período (tras rebalancear o derivar), por ``d_{k-1}``."""
    turnover: pd.Series
    """Σ|Δw| en cada fecha de decisión (0 cuando no se rebalancea)."""
    costos: pd.Series
    """Costo cobrado en cada fecha de decisión, como fracción del capital."""
    valor: pd.Series
    """Capital acumulado neto, indexado por ``d_0 … d_n`` (``valor[d_0] = 1``)."""

    @property
    def n_periodos(self) -> int:
        return len(self.retornos)


def backtest_walk_forward(
    precios: pd.DataFrame,
    estrategia: Estrategia,
    *,
    costo_transaccion_bps: float,
    rebalanceo: str,
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    pesos_iniciales: Mapping[str, float] | None = None,
) -> ResultadoBacktest:
    """Simula la estrategia sobre las fechas de ``precios`` en ``[fecha_inicio, fecha_fin]``.

    ``pesos_iniciales`` es la posición previa a la primera decisión; si se omite, la entrada
    se hace a los primeros pesos objetivo sin costo (el backtest mide la estrategia, no la
    transición desde una cartera concreta).
    """
    if rebalanceo not in PERIODOS_ENTRE_REBALANCEOS:
        raise ValueError(
            f"rebalanceo '{rebalanceo}' no reconocido; opciones: {list(PERIODOS_ENTRE_REBALANCEOS)}"
        )
    if costo_transaccion_bps < 0.0:
        raise ValueError("costo_transaccion_bps no puede ser negativo")
    cada = PERIODOS_ENTRE_REBALANCEOS[rebalanceo]
    panel = _panel_valido(precios)
    fechas = _fechas_en_rango(pd.DatetimeIndex(panel.index), fecha_inicio, fecha_fin)
    if len(fechas) < _MIN_FECHAS:
        raise ValueError(
            f"se necesitan al menos {_MIN_FECHAS} fechas entre {fecha_inicio} y {fecha_fin}; "
            f"hay {len(fechas)}"
        )
    activos = tuple(str(c) for c in panel.columns)
    tasa_costo = costo_transaccion_bps / PUNTOS_BASICOS_POR_UNIDAD
    niveles = panel.loc[fechas].to_numpy(dtype=float)

    n = len(fechas) - 1
    pesos = np.zeros((n, len(activos)))
    turnover = np.zeros(n)
    retornos = np.zeros(n)
    w_previos: Vector | None = None
    if pesos_iniciales is not None:
        w_previos = _pesos_sobre_disponibles(pesos_iniciales, activos, ~np.isnan(niveles[0]))

    for k in range(n):
        p0, p1 = niveles[k], niveles[k + 1]
        disponibles = ~np.isnan(p0)
        if k % cada == 0:
            propuesta = estrategia(panel, fechas[k].date())
            objetivo = _pesos_sobre_disponibles(propuesta, activos, disponibles)
            if w_previos is None:
                w_previos = objetivo
            turnover[k] = float(np.abs(objetivo - w_previos).sum())
            w = objetivo
        else:
            assert w_previos is not None  # k > 0: el primer período siempre rebalancea
            w = w_previos
        r_activos = np.where(disponibles, p1 / np.where(disponibles, p0, 1.0) - 1.0, 0.0)
        r_bruto = float(w @ r_activos)
        if 1.0 + r_bruto <= 0.0:
            raise ValueError(f"pérdida total del capital en {fechas[k + 1].date()}")
        costo = turnover[k] * tasa_costo
        retornos[k] = (1.0 - costo) * (1.0 + r_bruto) - 1.0
        pesos[k] = w
        w_previos = np.asarray(w * (1.0 + r_activos) / (1.0 + r_bruto), dtype=float)

    decision, cierre = fechas[:-1], fechas[1:]
    valor = np.concatenate(([1.0], np.cumprod(1.0 + retornos)))
    return ResultadoBacktest(
        activos=activos,
        fechas_decision=decision,
        retornos=pd.Series(retornos, index=cierre, name="retorno_neto"),
        pesos=pd.DataFrame(pesos, index=decision, columns=list(activos)),
        turnover=pd.Series(turnover, index=decision, name="turnover"),
        costos=pd.Series(turnover * tasa_costo, index=decision, name="costo"),
        valor=pd.Series(valor, index=fechas, name="valor"),
    )


def _panel_valido(precios: pd.DataFrame) -> pd.DataFrame:
    if precios.empty or len(precios.columns) == 0:
        raise ValueError("panel de precios vacío")
    indice = pd.DatetimeIndex(precios.index)
    if not indice.is_monotonic_increasing or indice.has_duplicates:
        raise ValueError("el índice de precios debe ser ascendente y sin duplicados")
    panel = precios.astype(float)
    panel.index = indice
    if (panel <= 0.0).any().any():
        raise ValueError("hay precios no positivos")
    return panel


def _fechas_en_rango(
    indice: pd.DatetimeIndex, inicio: date | None, fin: date | None
) -> pd.DatetimeIndex:
    mascara = np.ones(len(indice), dtype=bool)
    if inicio is not None:
        mascara &= indice >= pd.Timestamp(inicio)
    if fin is not None:
        mascara &= indice <= pd.Timestamp(fin)
    return indice[mascara]


def _pesos_sobre_disponibles(
    pesos: Mapping[str, float], activos: tuple[str, ...], disponibles: npt.NDArray[np.bool_]
) -> Vector:
    """Vector en el orden del panel; el peso de activos sin precio se reparte entre el resto."""
    desconocidos = sorted(set(pesos) - set(activos))
    if desconocidos:
        raise ValueError(f"la estrategia devolvió activos fuera del panel: {desconocidos}")
    w = np.array([float(pesos.get(a, 0.0)) for a in activos], dtype=float)
    if not np.all(np.isfinite(w)):
        raise ValueError("la estrategia devolvió pesos no finitos")
    if abs(w.sum() - 1.0) > TOLERANCIA_NUMERICA:
        raise ValueError(f"la estrategia devolvió pesos que suman {w.sum():.8f}, no 1")
    w = np.where(disponibles, w, 0.0)
    total = float(w.sum())
    if total <= 0.0:
        raise ValueError("ningún activo con peso positivo tiene precio en la fecha de decisión")
    return np.asarray(w / total, dtype=float)
