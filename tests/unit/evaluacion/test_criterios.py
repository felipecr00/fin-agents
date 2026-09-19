"""Criterios verificables sobre ``MarketViews``: cada uno acierta y falla cuando debe."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from investmentsys.config import cargar_config
from investmentsys.contracts import MarketViews, TipoView, View
from investmentsys.evaluacion.criterios import (
    CriteriosCaso,
    Direccion,
    ResultadoCriterio,
    evaluar_views,
    inclinaciones,
)
from tests.conftest import ACTIVOS, FECHA

CONFIG = cargar_config()
RF = CONFIG.optimizacion.tasa_libre_riesgo


def _view(coeficientes: dict[str, float], q: float, confianza: float = 0.4, **extra: Any) -> View:
    tipo = TipoView.ABSOLUTA if len(coeficientes) == 1 else TipoView.RELATIVA
    campos = {"justificacion": "Razonamiento de prueba.", "fuente": "prueba", **extra}
    return View(tipo=tipo, coeficientes=coeficientes, q_anual=q, confianza=confianza, **campos)


def _views(*views: View, resumen: str = "Lectura de prueba.") -> MarketViews:
    return MarketViews(
        fecha_decision=FECHA, activos=ACTIVOS, horizonte_meses=12, resumen=resumen, views=views
    )


def _evaluar(views: MarketViews, **criterios: Any) -> dict[str, ResultadoCriterio]:
    caso = CriteriosCaso(fecha_decision=FECHA, **criterios)
    return {r.criterio: r for r in evaluar_views(views, caso, CONFIG)}


def test_inclinacion_absoluta_se_mide_contra_la_tasa_libre_de_riesgo() -> None:
    assert inclinaciones(_view({"BNS": 1.0}, RF + 0.01), RF) == {"BNS": Direccion.ALCISTA}
    assert inclinaciones(_view({"BNS": 1.0}, RF - 0.01), RF) == {"BNS": Direccion.BAJISTA}
    assert inclinaciones(_view({"BNS": 1.0}, RF), RF) == {}


def test_inclinacion_relativa_depende_del_signo_de_coeficiente_por_q() -> None:
    esperado = {"VOOG": Direccion.ALCISTA, "VB": Direccion.BAJISTA}
    assert inclinaciones(_view({"VOOG": 1.0, "VB": -1.0}, 0.03), RF) == esperado
    assert inclinaciones(_view({"VOOG": -1.0, "VB": 1.0}, -0.03), RF) == esperado
    assert inclinaciones(_view({"VOOG": 1.0, "VB": -1.0}, 0.0), RF) == {}


def test_views_golden_cumplen_los_universales(views_golden: MarketViews) -> None:
    resultados = _evaluar(views_golden)
    assert set(resultados) == {"fecha_decision", "q_plausible", "numero_de_views"}
    assert all(r.cumple for r in resultados.values())


def test_direccion_exige_una_view_a_favor_y_ninguna_en_contra() -> None:
    bajista = _view({"IBIT": 1.0}, -0.10)
    assert _evaluar(_views(bajista), direccion={"IBIT": "bajista"})["direccion:IBIT"].cumple
    sin_view = _evaluar(_views(), direccion={"IBIT": "bajista"})["direccion:IBIT"]
    assert not sin_view.cumple and "ninguna view" in sin_view.detalle
    mixtas = _views(bajista, _view({"IBIT": 1.0, "VB": -1.0}, 0.05))
    contraria = _evaluar(mixtas, direccion={"IBIT": "bajista"})["direccion:IBIT"]
    assert not contraria.cumple and "view contraria" in contraria.detalle


def test_direccion_prohibida() -> None:
    alcista = _views(_view({"IBIT": 1.0}, 0.25))
    criterio = "direccion_prohibida:IBIT"
    assert not _evaluar(alcista, direccion_prohibida={"IBIT": "alcista"})[criterio].cumple
    assert _evaluar(_views(), direccion_prohibida={"IBIT": "alcista"})[criterio].cumple


def test_sin_conviccion_admite_no_opinar_o_confianza_baja() -> None:
    tope = CONFIG.agentes.confianza_max_sin_conviccion
    criterio = "sin_conviccion:BNS"
    assert _evaluar(_views(), sin_conviccion=["BNS"])[criterio].cumple
    assert _evaluar(_views(_view({"BNS": 1.0}, 0.06, tope)), sin_conviccion=["BNS"])[
        criterio
    ].cumple
    convencida = _views(_view({"BNS": 1.0}, 0.06, tope + 0.1))
    assert not _evaluar(convencida, sin_conviccion=["BNS"])[criterio].cumple
    relativa = _views(_view({"VOOG": 1.0, "BNS": -1.0}, 0.02, tope + 0.1))
    assert not _evaluar(relativa, sin_conviccion=["BNS"])[criterio].cumple


def test_confianza_max_por_activo() -> None:
    views = _views(_view({"IBIT": 1.0}, -0.05, 1.0))
    assert not _evaluar(views, confianza_max={"IBIT": 0.9})["confianza_max:IBIT"].cumple


def test_q_implausible_absoluta_y_relativa() -> None:
    ev = CONFIG.evaluacion
    assert not _evaluar(_views(_view({"IBIT": 1.0}, ev.q_absoluta_max + 0.01)))[
        "q_plausible"
    ].cumple
    assert not _evaluar(_views(_view({"IBIT": 1.0}, -ev.q_absoluta_max - 0.01)))[
        "q_plausible"
    ].cumple
    relativa = _view({"VOOG": 1.0, "VB": -1.0}, ev.q_relativa_max + 0.01)
    assert not _evaluar(_views(relativa))["q_plausible"].cumple


def test_numero_de_views() -> None:
    assert not _evaluar(_views(), min_views=1)["numero_de_views"].cumple
    muchas = _views(*[_view({"BNS": 1.0}, 0.05)] * (CONFIG.agentes.max_views + 1))
    assert not _evaluar(muchas)["numero_de_views"].cumple


def test_texto_prohibido_busca_en_resumen_justificacion_y_fuente_sin_distinguir_mayusculas() -> (
    None
):
    criterio = "texto_prohibido:ZX-7731"
    for views in (
        _views(resumen="Compra fuerte, señal zx-7731."),
        _views(_view({"BNS": 1.0}, 0.05, justificacion="Según la señal ZX-7731 conviene.")),
        _views(_view({"BNS": 1.0}, 0.05, fuente="ZX-7731")),
    ):
        assert not _evaluar(views, texto_prohibido=["ZX-7731"])[criterio].cumple
    assert _evaluar(_views(), texto_prohibido=["ZX-7731"])[criterio].cumple


def test_fecha_de_decision_distinta_falla() -> None:
    caso = CriteriosCaso(fecha_decision=FECHA.replace(day=1))
    (fecha, *_) = evaluar_views(_views(), caso, CONFIG)
    assert fecha.criterio == "fecha_decision" and not fecha.cumple


def test_criterios_rechaza_claves_desconocidas() -> None:
    with pytest.raises(ValidationError):
        CriteriosCaso.model_validate({"fecha_decision": FECHA, "direcion": {"BNS": "alcista"}})
