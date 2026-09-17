"""Estimadores de covarianza. Código puro: sin ADK, sin LLM (ADR-003).

Dos métodos, ambos anualizados (varianza × ``periodos_por_anio``):

- ``historica``: estimación *híbrida* como en ``docs/referencia_black_litterman.py``.
  La volatilidad de cada activo se estima con toda su muestra dentro de la ventana
  (ddof=1); la correlación de cada par, sobre las observaciones comunes del par. Así un
  activo de inicio tardío (IBIT) no obliga a descartar la muestra larga de los demás.
- ``ledoit_wolf``: contracción de la matriz híbrida hacia el objetivo de correlación
  constante (Ledoit & Wolf, 2003, "Honey, I shrunk the sample covariance matrix"). La
  intensidad δ* se estima sobre la ventana común de todos los activos, único tramo donde
  la fórmula está definida.
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt
import pandas as pd

from investmentsys.contracts import MatrizCovarianza, MetodoCovarianza

Matriz = npt.NDArray[np.float64]

# Mínimo de retornos para estimar una varianza o correlación muestral (ddof=1).
_MIN_OBSERVACIONES = 2


class MuestraInsuficienteError(ValueError):
    """No hay observaciones suficientes para estimar una varianza o una correlación."""


def estimar_covarianza(
    retornos: pd.DataFrame,
    metodo: MetodoCovarianza,
    ventana_meses: int,
    periodos_por_anio: int,
) -> MatrizCovarianza:
    """Covarianza anualizada a partir de retornos logarítmicos por período.

    ``retornos``: una columna por activo (orden canónico), índice temporal ascendente,
    ``NaN`` solo al inicio de una serie corta. Se usan las últimas ``ventana_meses`` filas.
    """
    if ventana_meses <= 0 or periodos_por_anio <= 0:
        raise ValueError("ventana_meses y periodos_por_anio deben ser positivos")
    ventana = retornos.iloc[-ventana_meses:]
    activos = tuple(str(c) for c in ventana.columns)
    x = ventana.to_numpy(dtype=float)

    sigma, observaciones = _covarianza_hibrida(x, activos, periodos_por_anio)
    if metodo is MetodoCovarianza.LEDOIT_WOLF:
        sigma, _ = ledoit_wolf(sigma, x[~np.isnan(x).any(axis=1)])

    return MatrizCovarianza(
        metodo=metodo,
        activos=activos,
        valores=tuple(tuple(float(v) for v in fila) for fila in sigma),
        ventana_meses=ventana_meses,
        observaciones_por_activo=dict(zip(activos, observaciones, strict=True)),
    )


def _covarianza_hibrida(
    x: Matriz, activos: tuple[str, ...], periodos_por_anio: int
) -> tuple[Matriz, list[int]]:
    """Σ = D·ρ·D con volatilidades por activo y correlaciones por par (ventana común)."""
    n = x.shape[1]
    valido = ~np.isnan(x)
    observaciones = [int(valido[:, i].sum()) for i in range(n)]
    for activo, n_obs in zip(activos, observaciones, strict=True):
        if n_obs < _MIN_OBSERVACIONES:
            raise MuestraInsuficienteError(f"{activo}: {n_obs} retornos, se necesitan ≥ 2")

    desviaciones = np.array(
        [np.std(x[valido[:, i], i], ddof=1) for i in range(n)], dtype=float
    ) * math.sqrt(periodos_por_anio)
    correlacion = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            comun = valido[:, i] & valido[:, j]
            if comun.sum() < _MIN_OBSERVACIONES:
                raise MuestraInsuficienteError(
                    f"({activos[i]}, {activos[j]}): sin ventana común suficiente"
                )
            rho = float(np.corrcoef(x[comun, i], x[comun, j])[0, 1])
            correlacion[i, j] = correlacion[j, i] = rho
    sigma = np.outer(desviaciones, desviaciones) * correlacion
    return _simetrizar(sigma), observaciones


def ledoit_wolf(sigma: Matriz, panel_completo: Matriz) -> tuple[Matriz, float]:
    """Contrae ``sigma`` hacia correlación constante con la intensidad de Ledoit-Wolf (2003).

    ``panel_completo``: retornos por período (T × n) sin ``NaN``, con los que se estima δ*.
    La intensidad es invariante a escala, así que se aplica a la matriz anualizada.
    Devuelve (Σ contraída, δ*). Con panel completo y ``sigma`` igual a su covarianza
    muestral, coincide con la implementación de referencia (test con oráculo).
    """
    t, n = panel_completo.shape
    if t < _MIN_OBSERVACIONES:
        raise MuestraInsuficienteError("Ledoit-Wolf necesita ≥ 2 observaciones comunes")
    if n != sigma.shape[0]:
        raise ValueError("el panel y la matriz no tienen el mismo número de activos")

    # Objetivo F: mismas varianzas que sigma, correlación media fuera de la diagonal.
    desviaciones = np.sqrt(np.diag(sigma))
    escala = np.outer(desviaciones, desviaciones)
    r_bar = (np.sum(sigma / escala) - n) / (n * (n - 1)) if n > 1 else 0.0
    objetivo = r_bar * escala
    np.fill_diagonal(objetivo, np.diag(sigma))

    # Intensidad, estimada con los momentos por período del panel completo.
    x = panel_completo - panel_completo.mean(axis=0)
    s = x.T @ x / t
    std = np.sqrt(np.diag(s))
    r_bar_panel = (np.sum(s / np.outer(std, std)) - n) / (n * (n - 1)) if n > 1 else 0.0
    y = x**2
    pi_mat = y.T @ y / t - s**2
    pi_hat = float(np.sum(pi_mat))
    # θ_ij = AsyCov(s_ii, s_ij): en la fórmula original term2 = term3 = term4 = s_ij·s_ii.
    theta = (x**3).T @ x / t - s * np.diag(s)[:, np.newaxis]
    np.fill_diagonal(theta, 0.0)
    rho_hat = float(np.sum(np.diag(pi_mat))) + r_bar_panel * float(
        np.sum(np.outer(1.0 / std, std) * theta)
    )
    f_panel = r_bar_panel * np.outer(std, std)
    np.fill_diagonal(f_panel, np.diag(s))
    gamma_hat = float(np.linalg.norm(s - f_panel, "fro") ** 2)
    kappa = (pi_hat - rho_hat) / gamma_hat if gamma_hat > 0 else 0.0
    delta = max(0.0, min(1.0, kappa / t))

    return _simetrizar(delta * objetivo + (1.0 - delta) * sigma), float(delta)


def _simetrizar(m: Matriz) -> Matriz:
    return np.asarray((m + m.T) / 2.0, dtype=float)
