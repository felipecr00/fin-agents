"""Verificación explícita de look-ahead bias por invariancia al futuro (ADR-004).

Una estrategia sin look-ahead decide en ``fecha`` únicamente con datos ≤ ``fecha``. Por
tanto sus pesos en ``fecha`` no pueden cambiar si se altera **solo** lo posterior. Para cada
fecha de decisión se llama a la estrategia con el panel real y con tres paneles cuyo pasado
es idéntico y cuyo futuro difiere:

- ``sin_futuro``: el panel truncado en ``fecha``;
- ``futuro_invertido``: los retornos posteriores a ``fecha`` con el signo cambiado;
- ``futuro_aleatorio``: los precios posteriores reemplazados por un paseo aleatorio con
  semilla fija (``config.yaml: reproducibilidad.semilla``).

Si los pesos difieren, o si la estrategia falla al no tener el futuro, se lanza
``LookAheadDetectadoError`` con la evidencia: fecha, perturbación y ambos vectores de pesos.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import date

import numpy as np
import numpy.typing as npt
import pandas as pd

from investmentsys.contracts.common import TOLERANCIA_NUMERICA
from investmentsys.quant import LookAheadError
from investmentsys.risk.backtest import Estrategia

PERTURBACIONES = ("sin_futuro", "futuro_invertido", "futuro_aleatorio")
Vector = npt.NDArray[np.float64]


class LookAheadDetectadoError(LookAheadError):
    """La decisión en ``fecha`` cambió al alterar solo datos posteriores a ``fecha``."""

    def __init__(
        self,
        fecha: date,
        perturbacion: str,
        pesos_reales: Mapping[str, float],
        pesos_perturbados: Mapping[str, float] | None,
        detalle: str = "",
    ) -> None:
        self.fecha = fecha
        self.perturbacion = perturbacion
        self.pesos_reales = dict(pesos_reales)
        self.pesos_perturbados = None if pesos_perturbados is None else dict(pesos_perturbados)
        self.detalle = detalle
        if pesos_perturbados is None:
            consecuencia = f"la estrategia falla sin el futuro real ({detalle})"
        else:
            consecuencia = f"los pesos pasan a {_fmt(pesos_perturbados)}"
        super().__init__(
            f"look-ahead detectado en {fecha} (perturbación '{perturbacion}'): con el futuro "
            f"real decide {_fmt(pesos_reales)}; al alterar solo datos posteriores a {fecha}, "
            f"{consecuencia}"
        )


def verificar_look_ahead(
    estrategia: Estrategia,
    precios: pd.DataFrame,
    fechas: Iterable[date],
    *,
    semilla: int,
    tolerancia: float = TOLERANCIA_NUMERICA,
) -> None:
    """Lanza ``LookAheadDetectadoError`` en la primera fecha cuya decisión depende del futuro."""
    rng = np.random.default_rng(semilla)
    for fecha in fechas:
        reales = dict(estrategia(precios, fecha))
        for nombre, panel in perturbaciones(precios, fecha, rng):
            try:
                alternativos = dict(estrategia(panel, fecha))
            except Exception as exc:
                raise LookAheadDetectadoError(
                    fecha, nombre, reales, None, detalle=f"{type(exc).__name__}: {exc}"
                ) from exc
            if not _iguales(reales, alternativos, tolerancia):
                raise LookAheadDetectadoError(fecha, nombre, reales, alternativos)


def perturbaciones(
    precios: pd.DataFrame, fecha: date, rng: np.random.Generator
) -> Iterator[tuple[str, pd.DataFrame]]:
    """Paneles con el mismo pasado que ``precios`` hasta ``fecha`` y distinto futuro."""
    indice = pd.DatetimeIndex(precios.index)
    futuro = indice > pd.Timestamp(fecha)
    yield "sin_futuro", precios.loc[~futuro]
    yield "futuro_invertido", _reemplazar_futuro(precios, futuro, _invertir)

    def _aleatorio(desvio: Vector, escala: float) -> Vector:
        return np.asarray(np.cumsum(rng.standard_normal(len(desvio)) * escala), dtype=float)

    yield "futuro_aleatorio", _reemplazar_futuro(precios, futuro, _aleatorio)


def _invertir(desvio: Vector, escala: float) -> Vector:
    return -desvio


def _reemplazar_futuro(
    precios: pd.DataFrame,
    futuro: npt.NDArray[np.bool_],
    nuevo_desvio: Callable[[npt.NDArray[np.float64], float], npt.NDArray[np.float64]],
) -> pd.DataFrame:
    """Sustituye, por activo, los log-precios futuros por ``ancla + nuevo_desvio(...)``.

    El ancla es el último precio válido en o antes de la fecha; si el activo aún no cotiza,
    su primer precio futuro (la fecha de inicio no se altera). La escala del desvío es la
    desviación de los log-retornos del activo (0 si no puede estimarse).
    """
    panel = precios.astype(float).copy()
    log_panel = np.log(panel.to_numpy(dtype=float))
    for j, columna in enumerate(panel.columns):
        serie = log_panel[:, j]
        validos = ~np.isnan(serie)
        pasado_valido = validos & ~futuro
        futuro_valido = validos & futuro
        if not futuro_valido.any():
            continue
        if pasado_valido.any():
            ancla = serie[pasado_valido][-1]
            objetivo = futuro_valido
        else:
            primero = int(np.flatnonzero(futuro_valido)[0])
            ancla = serie[primero]
            objetivo = futuro_valido.copy()
            objetivo[primero] = False
        if not objetivo.any():
            continue
        retornos = np.diff(serie[validos])
        escala = float(np.std(retornos, ddof=1)) if len(retornos) >= 2 else 0.0
        desvio = serie[objetivo] - ancla
        serie_nueva = serie.copy()
        serie_nueva[objetivo] = ancla + nuevo_desvio(desvio, escala)
        panel[columna] = np.exp(serie_nueva)
    return panel


def _iguales(a: Mapping[str, float], b: Mapping[str, float], tolerancia: float) -> bool:
    return all(abs(a.get(k, 0.0) - b.get(k, 0.0)) <= tolerancia for k in set(a) | set(b))


def _fmt(pesos: Mapping[str, float]) -> str:
    return "{" + ", ".join(f"{k}: {v:.4f}" for k, v in pesos.items()) + "}"
