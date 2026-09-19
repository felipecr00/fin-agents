"""Criterios de éxito verificables sobre un ``MarketViews`` (ADR-010). Sin ADK ni LLM.

Cada caso de un evalset declara un ``CriteriosCaso``; ``evaluar_views`` lo contrasta con las
views que emitió el analista y devuelve un resultado por criterio, con su explicación. Los
criterios universales (retornos plausibles, número de views) salen de ``config.yaml``
(``evaluacion`` y ``agentes``).

Inclinación de una view sobre un activo:
- absoluta: alcista si ``q_anual`` supera la tasa libre de riesgo, bajista si queda por debajo
  (el exceso de retorno es lo que entra a Black-Litterman);
- relativa: alcista para el lado que se espera que gane (coeficiente × q > 0), bajista para el otro.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from investmentsys.config import Config
from investmentsys.contracts import Fraccion, MarketViews, Ticker, TipoView, View


class Direccion(StrEnum):
    ALCISTA = "alcista"
    BAJISTA = "bajista"


class CriteriosCaso(BaseModel):
    """Lo que debe cumplir el ``MarketViews`` de un caso, además de los criterios universales."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fecha_decision: date = Field(description="La misma del estado inicial de la sesión del caso.")
    direccion: dict[Ticker, Direccion] = Field(
        default_factory=dict,
        description="Al menos una view inclina el activo en esa dirección y ninguna en la opuesta.",
    )
    direccion_prohibida: dict[Ticker, Direccion] = Field(
        default_factory=dict, description="Ninguna view inclina el activo en esa dirección."
    )
    sin_conviccion: tuple[Ticker, ...] = Field(
        default=(),
        description="Sin view sobre el activo, o todas con confianza ≤ el tope de `agentes`.",
    )
    confianza_max: dict[Ticker, Fraccion] = Field(
        default_factory=dict, description="Tope de confianza de toda view que toque el activo."
    )
    min_views: int = Field(default=0, ge=0)
    texto_prohibido: tuple[str, ...] = Field(
        default=(),
        description="Cadenas que no pueden aparecer en ningún texto del MarketViews (sin may/min).",
    )


class ResultadoCriterio(BaseModel):
    model_config = ConfigDict(frozen=True)

    criterio: str
    cumple: bool
    detalle: str


def inclinaciones(view: View, tasa_libre_riesgo: float) -> dict[str, Direccion]:
    """Dirección en que ``view`` inclina cada activo que toca (ver docstring del módulo)."""
    if view.tipo is TipoView.ABSOLUTA:
        (activo,) = view.activos
        if view.q_anual == tasa_libre_riesgo:
            return {}
        return {
            activo: Direccion.ALCISTA if view.q_anual > tasa_libre_riesgo else Direccion.BAJISTA
        }
    return {
        activo: Direccion.ALCISTA if coeficiente * view.q_anual > 0 else Direccion.BAJISTA
        for activo, coeficiente in view.coeficientes.items()
        if view.q_anual != 0.0
    }


def _describir(view: View) -> str:
    return f"{view.tipo.value} {view.coeficientes} q={view.q_anual:+.1%} conf={view.confianza:.2f}"


def _textos(views: MarketViews) -> list[str]:
    return [views.resumen, *(t for v in views.views for t in (v.justificacion, v.fuente))]


def evaluar_views(
    views: MarketViews, criterios: CriteriosCaso, config: Config
) -> list[ResultadoCriterio]:
    """Un ``ResultadoCriterio`` por criterio universal y por cada criterio declarado en el caso."""
    evaluacion, agentes = config.evaluacion, config.agentes
    tasa_libre_riesgo = config.optimizacion.tasa_libre_riesgo
    resultados: list[ResultadoCriterio] = []

    def anotar(criterio: str, fallos: list[str], si_cumple: str) -> None:
        resultados.append(
            ResultadoCriterio(
                criterio=criterio, cumple=not fallos, detalle="; ".join(fallos) or si_cumple
            )
        )

    anotar(
        "fecha_decision",
        [f"el caso declara {criterios.fecha_decision} y las views son de {views.fecha_decision}"]
        if views.fecha_decision != criterios.fecha_decision
        else [],
        f"views con fecha de decisión {views.fecha_decision}",
    )

    implausibles = [
        _describir(v)
        for v in views.views
        if abs(v.q_anual)
        > (evaluacion.q_absoluta_max if v.tipo is TipoView.ABSOLUTA else evaluacion.q_relativa_max)
    ]
    anotar(
        "q_plausible",
        implausibles,
        f"|q| ≤ {evaluacion.q_absoluta_max:.0%} (absolutas) y {evaluacion.q_relativa_max:.0%} "
        "(relativas) en todas las views",
    )

    n = len(views.views)
    fuera = [] if criterios.min_views <= n <= agentes.max_views else [f"{n} views"]
    anotar("numero_de_views", fuera, f"{n} views en [{criterios.min_views}, {agentes.max_views}]")

    por_activo: dict[str, list[tuple[View, Direccion]]] = {}
    for view in views.views:
        for activo, direccion in inclinaciones(view, tasa_libre_riesgo).items():
            por_activo.setdefault(activo, []).append((view, direccion))

    for activo, esperada in criterios.direccion.items():
        vistas = por_activo.get(activo, [])
        contrarias = [_describir(v) for v, d in vistas if d is not esperada]
        fallos = (
            [f"ninguna view inclina {activo} a {esperada.value}"]
            if not any(d is esperada for _, d in vistas)
            else []
        ) + [f"view contraria: {c}" for c in contrarias]
        anotar(f"direccion:{activo}", fallos, f"{activo} {esperada.value}")

    for activo, prohibida in criterios.direccion_prohibida.items():
        fallos = [_describir(v) for v, d in por_activo.get(activo, []) if d is prohibida]
        anotar(
            f"direccion_prohibida:{activo}", fallos, f"ninguna view {prohibida.value} de {activo}"
        )

    topes = [
        *(
            ("sin_conviccion", a, agentes.confianza_max_sin_conviccion)
            for a in criterios.sin_conviccion
        ),
        *(("confianza_max", a, tope) for a, tope in criterios.confianza_max.items()),
    ]
    for nombre, activo, tope in topes:
        fallos = [
            _describir(v) for v in views.views if activo in v.coeficientes and v.confianza > tope
        ]
        anotar(f"{nombre}:{activo}", fallos, f"ninguna view de {activo} con confianza > {tope}")

    for cadena in criterios.texto_prohibido:
        fallos = [repr(t) for t in _textos(views) if cadena.lower() in t.lower()]
        anotar(f"texto_prohibido:{cadena}", fallos, f"{cadena!r} no aparece en ningún texto")

    return resultados
