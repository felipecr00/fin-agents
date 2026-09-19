"""Sensibilidad de la cartera Black-Litterman a sus supuestos. Código puro: sin ADK ni LLM.

Se perturba UN supuesto a la vez, se reoptimiza con el mismo ``portfolio.black_litterman`` y se
mide cuánto se alejan los pesos de la cartera base. Todo es determinista: una rejilla de
perturbaciones de ``config.yaml`` (``sensibilidad``), sin muestreo.

Familias de perturbación:
- ``views_q``: el ``q_anual`` de cada view, ± puntos porcentuales (lo que opina el analista).
- ``mu_posterior``: el retorno esperado posterior de cada activo, ± p.p., con Σ_BL fija (el
  experimento clásico de media-varianza: error en μ con el riesgo intacto).
- ``volatilidad``: la volatilidad de cada activo, ± % relativo (fila y columna de Σ).
- ``correlacion``: la correlación de cada par, ± % relativo, con las volatilidades fijas.
- ``covarianza_global``: toda Σ, ± % relativo.
- ``parametros``: δ (aversión al riesgo) y τ, ± % relativo.

Una perturbación de Σ se propaga por todo el modelo (prior π = δΣw, Ω, posterior y riesgo), que
es lo que pasaría si la estimación de Σ fuera otra. Una perturbación que deja Σ sin ser
definida positiva se omite y se informa.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from itertools import combinations

import numpy as np

from investmentsys.config import OptimizacionConfig, PriorEquilibrioConfig, SensibilidadConfig
from investmentsys.contracts import (
    MarketViews,
    MatrizCovarianza,
    PortfolioConstraints,
    QuantEstimates,
    Sensibilidad,
    View,
)
from investmentsys.portfolio._comun import Matriz, Vector, matriz, pesos_a_dict
from investmentsys.portfolio.black_litterman import pesos_optimos, posterior_black_litterman

# Campo de ``OptimizacionConfig`` → nombre en el informe.
PARAMETROS_PERTURBADOS = {"aversion_riesgo_delta": "delta", "tau": "tau"}
PP = 100.0  # fracción → puntos porcentuales (unidad de presentación, no un parámetro)


class Familia(StrEnum):
    VIEWS_Q = "views_q"
    MU_POSTERIOR = "mu_posterior"
    VOLATILIDAD = "volatilidad"
    CORRELACION = "correlacion"
    COVARIANZA_GLOBAL = "covarianza_global"
    PARAMETROS = "parametros"


class Supuesto(StrEnum):
    """Lo que el usuario puede estar estimando mal; cada familia pertenece a uno."""

    RETORNOS = "retornos esperados"
    COVARIANZAS = "covarianzas"
    PARAMETROS = "parámetros del modelo"


SUPUESTO_DE: dict[Familia, Supuesto] = {
    Familia.VIEWS_Q: Supuesto.RETORNOS,
    Familia.MU_POSTERIOR: Supuesto.RETORNOS,
    Familia.VOLATILIDAD: Supuesto.COVARIANZAS,
    Familia.CORRELACION: Supuesto.COVARIANZAS,
    Familia.COVARIANZA_GLOBAL: Supuesto.COVARIANZAS,
    Familia.PARAMETROS: Supuesto.PARAMETROS,
}


@dataclass(frozen=True)
class Perturbacion:
    familia: Familia
    parametro: str
    magnitud: float
    """Con signo. Absoluta en retornos (0.01 = 1 p.p.); relativa en el resto (0.10 = 10 %)."""
    pesos: dict[str, float]
    cambio_max_pp: float
    """Mayor cambio absoluto de un peso, en puntos porcentuales."""
    rotacion_pp: float
    """½·Σ|Δw| en p.p.: cuánto habría que mover de la cartera para pasar de la base a esta."""
    activo_mas_afectado: str

    @property
    def supuesto(self) -> Supuesto:
        return SUPUESTO_DE[self.familia]

    def a_contrato(self) -> Sensibilidad:
        return Sensibilidad(
            parametro=f"{self.familia.value}:{self.parametro}",
            perturbacion=self.magnitud,
            pesos_perturbados=self.pesos,
            cambio_max_pp=self.cambio_max_pp,
        )


@dataclass(frozen=True)
class ResumenFamilia:
    familia: Familia
    n: int
    cambio_max_pp_medio: float
    cambio_max_pp_peor: float
    rotacion_pp_media: float
    peor: Perturbacion


@dataclass(frozen=True)
class AnalisisSensibilidad:
    pesos_base: dict[str, float]
    limites_activos: tuple[str, ...]
    """Activos cuyo peso base está pegado a un límite, p. ej. ``"VOOG=max"``."""
    perturbaciones: tuple[Perturbacion, ...]
    omitidas: tuple[str, ...]

    def por_familia(self) -> list[ResumenFamilia]:
        """De la familia más frágil a la menos (por desplazamiento medio)."""
        resumenes = []
        for familia in Familia:
            grupo = [p for p in self.perturbaciones if p.familia is familia]
            if not grupo:
                continue
            resumenes.append(
                ResumenFamilia(
                    familia=familia,
                    n=len(grupo),
                    cambio_max_pp_medio=float(np.mean([p.cambio_max_pp for p in grupo])),
                    cambio_max_pp_peor=max(p.cambio_max_pp for p in grupo),
                    rotacion_pp_media=float(np.mean([p.rotacion_pp for p in grupo])),
                    peor=max(grupo, key=lambda p: p.cambio_max_pp),
                )
            )
        return sorted(resumenes, key=lambda r: r.cambio_max_pp_medio, reverse=True)

    def por_supuesto(self) -> dict[Supuesto, float]:
        """Desplazamiento medio (p.p.) por supuesto, de mayor a menor."""
        medias = {
            s: float(np.mean([p.cambio_max_pp for p in self.perturbaciones if p.supuesto is s]))
            for s in Supuesto
            if any(p.supuesto is s for p in self.perturbaciones)
        }
        return dict(sorted(medias.items(), key=lambda par: par[1], reverse=True))

    def supuesto_mas_fragil(self) -> Supuesto:
        return next(iter(self.por_supuesto()))


def analizar_sensibilidad(
    estimates: QuantEstimates,
    views: MarketViews,
    restricciones: PortfolioConstraints,
    optimizacion: OptimizacionConfig,
    prior: PriorEquilibrioConfig,
    sensibilidad: SensibilidadConfig,
) -> AnalisisSensibilidad:
    activos = estimates.activos
    delta = optimizacion.aversion_riesgo_delta

    def pesos(e: QuantEstimates, v: MarketViews, o: OptimizacionConfig) -> Vector:
        post = posterior_black_litterman(e, v, o, prior)
        return pesos_optimos(post.mu, post.sigma_bl, o.aversion_riesgo_delta, restricciones)

    base = pesos(estimates, views, optimizacion)
    post_base = posterior_black_litterman(estimates, views, optimizacion, prior)
    sigma = matriz(estimates, optimizacion.metodo_covarianza)

    def con_sigma(nueva: Matriz) -> Vector:
        return pesos(_con_covarianza(estimates, optimizacion, nueva), views, optimizacion)

    def con_q(indice: int, eps: float) -> Vector:
        return pesos(estimates, _con_q(views, indice, eps), optimizacion)

    def con_mu(indice: int, eps: float) -> Vector:
        mu = post_base.mu.copy()
        mu[indice] += eps
        return pesos_optimos(mu, post_base.sigma_bl, delta, restricciones)

    def con_volatilidad(indice: int, eps: float) -> Vector:
        return con_sigma(escalar_volatilidad(sigma, indice, 1.0 + eps))

    def con_correlacion(i: int, j: int, eps: float) -> Vector:
        return con_sigma(escalar_correlacion(sigma, i, j, 1.0 + eps))

    def con_sigma_global(eps: float) -> Vector:
        return con_sigma(sigma * (1.0 + eps))

    def con_parametro(campo: str, eps: float) -> Vector:
        valor = getattr(optimizacion, campo) * (1.0 + eps)
        return pesos(estimates, views, optimizacion.model_copy(update={campo: valor}))

    def experimentos() -> Iterator[tuple[Familia, str, float, Callable[[], Vector]]]:
        n = len(activos)
        for eps in _con_signo(sensibilidad.retornos_pp):
            for i, view in enumerate(views.views):
                nombre = f"view[{i}] {_nombre_view(view)}"
                yield Familia.VIEWS_Q, nombre, eps, partial(con_q, i, eps)
            for i, activo in enumerate(activos):
                yield Familia.MU_POSTERIOR, activo, eps, partial(con_mu, i, eps)
        for eps in _con_signo(sensibilidad.covarianza_rel):
            for i, activo in enumerate(activos):
                yield Familia.VOLATILIDAD, activo, eps, partial(con_volatilidad, i, eps)
            for i, j in combinations(range(n), 2):
                par = f"{activos[i]}-{activos[j]}"
                yield Familia.CORRELACION, par, eps, partial(con_correlacion, i, j, eps)
            yield Familia.COVARIANZA_GLOBAL, "Σ", eps, partial(con_sigma_global, eps)
        for eps in _con_signo(sensibilidad.parametros_rel):
            for campo, nombre in PARAMETROS_PERTURBADOS.items():
                yield Familia.PARAMETROS, nombre, eps, partial(con_parametro, campo, eps)

    perturbaciones: list[Perturbacion] = []
    omitidas: list[str] = []
    for familia, parametro, eps, calcular in experimentos():
        try:
            w = calcular()
        except MatrizNoDefinidaPositivaError as exc:
            omitidas.append(f"{familia.value}:{parametro} {eps:+.0%}: {exc}")
            continue
        cambio = np.abs(w - base)
        perturbaciones.append(
            Perturbacion(
                familia=familia,
                parametro=parametro,
                magnitud=eps,
                pesos=pesos_a_dict(activos, w),
                cambio_max_pp=float(cambio.max() * PP),
                rotacion_pp=float(cambio.sum() / 2.0 * PP),
                activo_mas_afectado=activos[int(cambio.argmax())],
            )
        )
    return AnalisisSensibilidad(
        pesos_base=pesos_a_dict(activos, base),
        limites_activos=_limites_activos(base, restricciones),
        perturbaciones=tuple(perturbaciones),
        omitidas=tuple(omitidas),
    )


class MatrizNoDefinidaPositivaError(ValueError):
    """La perturbación produjo una Σ que no es una covarianza válida."""


def escalar_volatilidad(sigma: Matriz, i: int, factor: float) -> Matriz:
    """σ_i → factor·σ_i con las correlaciones intactas (escala la fila y la columna ``i``)."""
    d = np.ones(sigma.shape[0])
    d[i] = factor
    return np.asarray(sigma * np.outer(d, d), dtype=float)


def escalar_correlacion(sigma: Matriz, i: int, j: int, factor: float) -> Matriz:
    """ρ_ij → factor·ρ_ij con las volatilidades intactas."""
    nueva = sigma.copy()
    nueva[i, j] = nueva[j, i] = sigma[i, j] * factor
    return _exigir_definida_positiva(nueva)


def _exigir_definida_positiva(sigma: Matriz) -> Matriz:
    minimo = float(np.linalg.eigvalsh(sigma).min())
    if minimo <= 0.0:
        raise MatrizNoDefinidaPositivaError(f"autovalor mínimo {minimo:.2e}")
    return sigma


def _con_signo(magnitudes: tuple[float, ...]) -> list[float]:
    return [signo * m for m in magnitudes for signo in (-1.0, 1.0)]


def _nombre_view(view: View) -> str:
    return "/".join(f"{'+' if c > 0 else '-'}{a}" for a, c in view.coeficientes.items())


def _con_q(views: MarketViews, indice: int, eps: float) -> MarketViews:
    nuevas = tuple(
        View.model_validate({**v.model_dump(), "q_anual": v.q_anual + eps}) if i == indice else v
        for i, v in enumerate(views.views)
    )
    return MarketViews.model_validate({**views.model_dump(exclude={"views"}), "views": nuevas})


def _con_covarianza(
    estimates: QuantEstimates, optimizacion: OptimizacionConfig, sigma: Matriz
) -> QuantEstimates:
    metodo = optimizacion.metodo_covarianza
    original = estimates.covarianza(metodo)
    perturbada = MatrizCovarianza.model_validate(
        {
            **original.model_dump(exclude={"valores"}),
            "valores": tuple(tuple(float(x) for x in fila) for fila in _exigir_simetrica(sigma)),
        }
    )
    return estimates.model_copy(
        update={"covarianzas": {**estimates.covarianzas, metodo: perturbada}}
    )


def _exigir_simetrica(sigma: Matriz) -> Matriz:
    return np.asarray((sigma + sigma.T) / 2.0, dtype=float)


def _limites_activos(w: Vector, restricciones: PortfolioConstraints) -> tuple[str, ...]:
    activos = []
    for activo, peso, (lo, hi) in zip(
        restricciones.activos, w, restricciones.limites_ordenados(), strict=True
    ):
        if np.isclose(peso, lo):
            activos.append(f"{activo}=min")
        elif np.isclose(peso, hi):
            activos.append(f"{activo}=max")
    return tuple(activos)
