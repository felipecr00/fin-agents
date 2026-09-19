"""Diff estructurado entre dos ``RunState``: qué cambió de una corrida a otra y cuánto.

Código puro: solo conoce los contratos. No es el replay de ADR-009 (que compara hoja a hoja una
corrida con su repetición y exige igualdad); aquí se comparan dos corridas distintas —otra
fecha, otras views, otra configuración— y el resultado es semántico: views emparejadas por lo
que opinan, estimaciones por activo y por par, pesos en puntos porcentuales, criterios que
cambian de lado.

Dos views son "la misma" si tienen el mismo tipo y la misma fila de P salvo el signo global:
``{VB: 1, VOOG: -1}, q = +2 %`` y ``{VOOG: 1, VB: -1}, q = -2 %`` dicen lo mismo. Las relativas
se normalizan (primer activo del universo con coeficiente positivo) antes de emparejar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from investmentsys.contracts import (
    CandidatePortfolio,
    MarketViews,
    QuantEstimates,
    RunState,
    TipoView,
    View,
)

PP = 100.0  # fracción → puntos porcentuales (unidad de presentación)


class CorridasIncomparablesError(ValueError):
    """Las corridas no comparten universo: no hay nada que emparejar."""


@dataclass(frozen=True)
class Cambio:
    """Un valor numérico en ambas corridas. ``None`` = ausente en esa corrida."""

    nombre: str
    antes: float | None
    despues: float | None

    @property
    def delta(self) -> float | None:
        if self.antes is None or self.despues is None:
            return None
        return self.despues - self.antes

    def cambia(self, tolerancia: float) -> bool:
        delta = self.delta
        if delta is None:
            return self.antes is not None or self.despues is not None
        return abs(delta) > tolerancia


@dataclass(frozen=True)
class CambioTexto:
    nombre: str
    antes: str | None
    despues: str | None

    @property
    def cambia(self) -> bool:
        return self.antes != self.despues


@dataclass(frozen=True)
class ViewNormalizada:
    tipo: TipoView
    coeficientes: tuple[tuple[str, float], ...]
    q_anual: float
    confianza: float

    @property
    def clave(self) -> tuple[TipoView, tuple[tuple[str, float], ...]]:
        return self.tipo, self.coeficientes

    def describir(self) -> str:
        if self.tipo is TipoView.ABSOLUTA:
            return self.coeficientes[0][0]
        largos = "+".join(a for a, c in self.coeficientes if c > 0)
        cortos = "+".join(a for a, c in self.coeficientes if c < 0)
        return f"{largos} vs {cortos}"


@dataclass(frozen=True)
class CambioView:
    antes: ViewNormalizada
    despues: ViewNormalizada

    @property
    def delta_q(self) -> float:
        return self.despues.q_anual - self.antes.q_anual

    @property
    def delta_confianza(self) -> float:
        return self.despues.confianza - self.antes.confianza


@dataclass(frozen=True)
class DiffViews:
    anadidas: tuple[ViewNormalizada, ...]
    retiradas: tuple[ViewNormalizada, ...]
    modificadas: tuple[CambioView, ...]
    sin_cambio: tuple[ViewNormalizada, ...]

    @property
    def hay_cambios(self) -> bool:
        return bool(self.anadidas or self.retiradas or self.modificadas)


@dataclass(frozen=True)
class CambioCriterio:
    nombre: str
    valor: Cambio
    cumple_antes: bool | None
    cumple_despues: bool | None

    @property
    def cambia_de_lado(self) -> bool:
        return self.cumple_antes != self.cumple_despues


@dataclass(frozen=True)
class DiffCorridas:
    metadatos: tuple[CambioTexto, ...]
    advertencias: tuple[str, ...]
    views: DiffViews
    volatilidades: tuple[Cambio, ...]
    correlaciones: tuple[Cambio, ...]
    retornos_historicos: tuple[Cambio, ...]
    peso_maximo: tuple[Cambio, ...]
    prior_caps: tuple[Cambio, ...]
    """Capitalizaciones congeladas del universo (US$ billones): un ``refrescar_cap`` sale aquí."""
    prior_procedencias: tuple[CambioTexto, ...]
    prior_pi_total: tuple[Cambio, ...]
    pesos: tuple[Cambio, ...]
    rotacion_pp: float | None
    """½·Σ|Δw| en p.p. entre las dos carteras; ``None`` si alguna corrida no tiene cartera."""
    metricas_ex_ante: tuple[Cambio, ...]
    metricas_oos: tuple[Cambio, ...]
    criterios: tuple[CambioCriterio, ...]

    def metadato(self, nombre: str) -> CambioTexto:
        return next(m for m in self.metadatos if m.nombre == nombre)


def normalizar_view(view: View, activos: tuple[str, ...]) -> ViewNormalizada:
    orden = {a: i for i, a in enumerate(activos)}
    coeficientes = sorted(view.coeficientes.items(), key=lambda par: orden[par[0]])
    signo = -1.0 if view.tipo is TipoView.RELATIVA and coeficientes[0][1] < 0 else 1.0
    return ViewNormalizada(
        tipo=view.tipo,
        coeficientes=tuple((a, signo * c) for a, c in coeficientes),
        q_anual=signo * view.q_anual,
        confianza=view.confianza,
    )


def _diff_views(
    a: MarketViews | None, b: MarketViews | None, activos: tuple[str, ...], tolerancia: float
) -> DiffViews:
    antes = {v.clave: v for v in (normalizar_view(x, activos) for x in (a.views if a else ()))}
    despues = {v.clave: v for v in (normalizar_view(x, activos) for x in (b.views if b else ()))}
    comunes = [c for c in antes if c in despues]
    modificadas, iguales = [], []
    for clave in comunes:
        cambio = CambioView(antes[clave], despues[clave])
        if abs(cambio.delta_q) > tolerancia or abs(cambio.delta_confianza) > tolerancia:
            modificadas.append(cambio)
        else:
            iguales.append(antes[clave])
    return DiffViews(
        anadidas=tuple(v for c, v in despues.items() if c not in antes),
        retiradas=tuple(v for c, v in antes.items() if c not in despues),
        modificadas=tuple(modificadas),
        sin_cambio=tuple(iguales),
    )


def _volatilidades(e: QuantEstimates | None) -> dict[str, float]:
    if e is None:
        return {}
    cov = next(iter(e.covarianzas.values()))
    return {a: cov.volatilidad(a) for a in e.activos}


def _correlaciones(e: QuantEstimates | None) -> dict[str, float]:
    if e is None:
        return {}
    cov = next(iter(e.covarianzas.values()))
    n = len(e.activos)
    return {
        f"{e.activos[i]}-{e.activos[j]}": cov.valores[i][j]
        / math.sqrt(cov.valores[i][i] * cov.valores[j][j])
        for i in range(n)
        for j in range(i + 1, n)
    }


def _retornos(e: QuantEstimates | None) -> dict[str, float]:
    return {r.activo: r.media_anual for r in e.retornos_historicos} if e else {}


def _cambios(antes: dict[str, float], despues: dict[str, float]) -> tuple[Cambio, ...]:
    nombres = [*antes, *(n for n in despues if n not in antes)]
    return tuple(Cambio(n, antes.get(n), despues.get(n)) for n in nombres)


def cartera_de(corrida: RunState) -> CandidatePortfolio | None:
    """La cartera aprobada o, si no la hay, la última que se sometió a validación."""
    if corrida.portafolio_final is not None:
        return corrida.portafolio_final
    return corrida.candidatos[-1].portafolio_recomendado if corrida.candidatos else None


def _pesos_maximos(corrida: RunState) -> dict[str, float]:
    r = corrida.restricciones
    return {a: r.limites(a)[1] for a in r.activos} if r else {}


def _metricas(modelo: object | None, campos: tuple[str, ...]) -> dict[str, float]:
    return {c: float(getattr(modelo, c)) for c in campos} if modelo is not None else {}


CAMPOS_EX_ANTE = ("retorno_esperado_anual", "volatilidad_anual", "sharpe", "concentracion_hhi")
CAMPOS_OOS = (
    "retorno_anualizado",
    "volatilidad_anualizada",
    "sharpe_oos",
    "max_drawdown",
    "turnover_anual",
)


def _caps(corrida: RunState) -> dict[str, float]:
    return {d.ticker: d.prior_cap for d in corrida.universo.diagnosticos if d.prior_cap is not None}


def _procedencias(corrida: RunState) -> dict[str, str]:
    """Procedencia EFECTIVA de cada peso del prior; sin prior, la de la cap congelada."""
    if corrida.prior is not None:
        return {a: p.value for a, p in corrida.prior.procedencias.items()}
    return {
        d.ticker: d.prior_provenance.value
        for d in corrida.universo.diagnosticos
        if d.prior_provenance is not None
    }


def _pi_total(corrida: RunState) -> dict[str, float]:
    return {a.activo: a.pi_total for a in corrida.prior.activos} if corrida.prior else {}


def _texto(valor: object | None) -> str | None:
    return None if valor is None else str(valor)


def comparar_corridas(a: RunState, b: RunState, tolerancia: float) -> DiffCorridas:
    """Diff de ``a`` (antes) a ``b`` (después); bajo ``tolerancia`` dos números son iguales."""
    if a.activos != b.activos:
        raise CorridasIncomparablesError(f"universos distintos: {a.activos} y {b.activos}")
    cartera_a, cartera_b = cartera_de(a), cartera_de(b)
    val_a, val_b = a.ultima_validacion, b.ultima_validacion
    est_a, est_b = a.quant_estimates, b.quant_estimates

    metadatos = tuple(
        CambioTexto(nombre, _texto(x), _texto(y))
        for nombre, x, y in (
            ("run_id", a.run_id, b.run_id),
            ("fecha_decision", a.fecha_decision, b.fecha_decision),
            ("etapa", a.etapa.value, b.etapa.value),
            ("iteraciones", len(a.candidatos), len(b.candidatos)),
            ("veredicto", val_a and val_a.veredicto.value, val_b and val_b.veredicto.value),
            ("candidato", cartera_a and cartera_a.nombre, cartera_b and cartera_b.nombre),
            (
                "regimen",
                a.quant_estimates and a.quant_estimates.regimen.value,
                b.quant_estimates and b.quant_estimates.regimen.value,
            ),
            ("config_hash", a.config_hash, b.config_hash),
            ("universe_version", a.universo.version, b.universo.version),
            ("prior", a.prior and a.prior.metodo.value, b.prior and b.prior.metodo.value),
            ("semilla", a.semilla, b.semilla),
        )
    )
    advertencias = []
    if a.universo.version != b.universo.version:
        advertencias.append(
            "universo distinto entre las corridas (datos, capitalizaciones congeladas o "
            "aceptación del prior neutral): es un cambio de INPUT, no de views."
        )
    if a.config_hash != b.config_hash:
        advertencias.append(
            "config.yaml distinto entre las corridas: parte de las diferencias puede venir de "
            "los parámetros y no de los datos ni de las views."
        )
    for nombre, corrida, cartera in (("antes", a, cartera_a), ("después", b, cartera_b)):
        if cartera is not None and not corrida.aprobado:
            advertencias.append(
                f"la corrida de {nombre} no tiene cartera aprobada: se compara la última "
                "recomendada."
            )

    pesos = _cambios(cartera_a.pesos if cartera_a else {}, cartera_b.pesos if cartera_b else {})
    rotacion = (
        sum(abs(c.delta or 0.0) for c in pesos) / 2.0 * PP if cartera_a and cartera_b else None
    )
    criterios_a = {c.nombre: c for c in (val_a.criterios if val_a else ())}
    criterios_b = {c.nombre: c for c in (val_b.criterios if val_b else ())}
    criterios = tuple(
        CambioCriterio(
            nombre=n,
            valor=Cambio(
                n,
                criterios_a[n].valor if n in criterios_a else None,
                criterios_b[n].valor if n in criterios_b else None,
            ),
            cumple_antes=criterios_a[n].cumple if n in criterios_a else None,
            cumple_despues=criterios_b[n].cumple if n in criterios_b else None,
        )
        for n in [*criterios_a, *(n for n in criterios_b if n not in criterios_a)]
    )
    procedencias_a, procedencias_b = _procedencias(a), _procedencias(b)
    return DiffCorridas(
        prior_caps=_cambios(_caps(a), _caps(b)),
        prior_procedencias=tuple(
            CambioTexto(activo, procedencias_a.get(activo), procedencias_b.get(activo))
            for activo in a.activos
        ),
        prior_pi_total=_cambios(_pi_total(a), _pi_total(b)),
        metadatos=metadatos,
        advertencias=tuple(advertencias),
        views=_diff_views(a.market_views, b.market_views, a.activos, tolerancia),
        volatilidades=_cambios(
            _volatilidades(a.quant_estimates), _volatilidades(b.quant_estimates)
        ),
        correlaciones=_cambios(
            _correlaciones(a.quant_estimates), _correlaciones(b.quant_estimates)
        ),
        retornos_historicos=_cambios(_retornos(est_a), _retornos(est_b)),
        peso_maximo=_cambios(_pesos_maximos(a), _pesos_maximos(b)),
        pesos=pesos,
        rotacion_pp=rotacion,
        metricas_ex_ante=_cambios(
            _metricas(cartera_a and cartera_a.metricas, CAMPOS_EX_ANTE),
            _metricas(cartera_b and cartera_b.metricas, CAMPOS_EX_ANTE),
        ),
        metricas_oos=_cambios(
            _metricas(val_a and val_a.metricas_oos, CAMPOS_OOS),
            _metricas(val_b and val_b.metricas_oos, CAMPOS_OOS),
        ),
        criterios=criterios,
    )
