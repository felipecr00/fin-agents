"""Diff entre dos ``RunState`` construidos con el núcleo real en dos fechas de decisión."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from investmentsys.comparacion import (
    CorridasIncomparablesError,
    comparar_corridas,
    diff_markdown,
    normalizar_view,
)
from investmentsys.config import Config, cargar_config, hash_config
from investmentsys.contracts import (
    DISCLAIMER,
    CandidatePortfolios,
    EtapaCorrida,
    MarketViews,
    PortfolioConstraints,
    RunState,
    TipoView,
    Universe,
    View,
)
from investmentsys.data import CSVPriceProvider
from investmentsys.portfolio import optimizar_black_litterman, resolver_prior
from investmentsys.quant import estimar
from investmentsys.risk import validar
from tests.almacen import sesion_de, universo_de, universo_referencia
from tests.conftest import ACTIVOS, CSV_REFERENCIA, FECHA

FECHA_ANTERIOR = date(2026, 6, 30)
TOLERANCIA = 1e-8
OTRO_HASH = "0" * 64


def _view(coeficientes: dict[str, float], q: float, confianza: float = 0.5) -> View:
    return View(
        tipo=TipoView.ABSOLUTA if len(coeficientes) == 1 else TipoView.RELATIVA,
        coeficientes=coeficientes,
        q_anual=q,
        confianza=confianza,
        justificacion="Razonamiento de prueba.",
        fuente="prueba",
    )


def _corrida(
    config: Config,
    fecha: date,
    views: tuple[View, ...],
    run_id: str,
    peso_max: float | None = None,
    universo: Universe | None = None,
) -> RunState:
    provider = CSVPriceProvider(CSV_REFERENCIA)
    opt = config.optimizacion
    universo = universo or universo_referencia()
    estimates = estimar(
        provider.retornos_log(ACTIVOS, hasta=fecha),
        fecha_decision=fecha,
        periodos_por_anio=provider.periodos_por_anio,
        ventana_meses=config.datos.ventana_covarianza_meses,
        metodos=(opt.metodo_covarianza,),
        nivel_confianza=config.estimacion.nivel_confianza,
        universe_version=universo.version,
    )
    market_views = MarketViews(
        fecha_decision=fecha, activos=ACTIVOS, horizonte_meses=12, resumen="Prueba.", views=views
    )
    restricciones = PortfolioConstraints(
        activos=ACTIVOS, peso_min=opt.peso_min, peso_max=peso_max or opt.peso_max
    )
    prior = resolver_prior(universo, estimates, opt, config.prior_equilibrio)
    candidato = optimizar_black_litterman(estimates, market_views, restricciones, opt, prior)
    reporte = validar(
        candidato,
        provider.precios(ACTIVOS, hasta=fecha),
        fecha_decision=fecha,
        iteracion=1,
        validacion=config.validacion,
        optimizacion=opt,
        periodos_por_anio=provider.periodos_por_anio,
        semilla=config.reproducibilidad.semilla,
        universe_version=universo.version,
    )
    return RunState(
        run_id=run_id,
        creado_en=datetime(2026, 9, 18, tzinfo=UTC),
        fecha_decision=fecha,
        semilla=config.reproducibilidad.semilla,
        config_hash=hash_config(),
        activos=ACTIVOS,
        universo=universo,
        restricciones_sesion=sesion_de(universo),
        prior=prior,
        etapa=EtapaCorrida.VALIDACION,
        restricciones=restricciones,
        market_views=market_views,
        quant_estimates=estimates,
        candidatos=(
            CandidatePortfolios(
                fecha_decision=fecha,
                activos=ACTIVOS,
                iteracion=1,
                candidatos=(candidato,),
                recomendado=candidato.nombre,
                universe_version=universo.version,
            ),
        ),
        validaciones=(reporte,),
    )


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config()


@pytest.fixture(scope="module")
def junio(config: Config) -> RunState:
    views = (_view({"VOOG": 1.0, "VB": -1.0}, 0.03), _view({"BNS": 1.0}, 0.10))
    return _corrida(config, FECHA_ANTERIOR, views, "junio")


@pytest.fixture(scope="module")
def septiembre(config: Config) -> RunState:
    views = (
        _view({"VB": 1.0, "VOOG": -1.0}, -0.05, 0.6),  # la misma de junio, escrita al revés
        _view({"IBIT": 1.0}, 0.03),
    )
    return _corrida(config, FECHA, views, "septiembre", peso_max=0.5)


def test_una_corrida_contra_si_misma_no_tiene_cambios(junio: RunState) -> None:
    diff = comparar_corridas(junio, junio, TOLERANCIA)
    assert not diff.views.hay_cambios and len(diff.views.sin_cambio) == 2
    assert diff.rotacion_pp == 0.0
    numericos = (
        *diff.pesos,
        *diff.volatilidades,
        *diff.correlaciones,
        *diff.retornos_historicos,
        *diff.peso_maximo,
        *diff.metricas_ex_ante,
        *diff.metricas_oos,
    )
    assert not any(c.cambia(TOLERANCIA) for c in numericos)
    assert not any(m.cambia for m in diff.metadatos)
    assert not any(c.cambia_de_lado for c in diff.criterios)
    assert diff.advertencias == ()


def test_view_relativa_escrita_al_reves_es_la_misma_view() -> None:
    derecha = normalizar_view(_view({"VOOG": 1.0, "VB": -1.0}, 0.02), ACTIVOS)
    reves = normalizar_view(_view({"VB": 1.0, "VOOG": -1.0}, -0.02), ACTIVOS)
    assert derecha == reves
    assert derecha.describir() == "VOOG vs VB"
    contraria = normalizar_view(_view({"VB": 1.0, "VOOG": -1.0}, 0.02), ACTIVOS)
    assert contraria.clave == derecha.clave and contraria.q_anual == -0.02


def test_views_anadidas_retiradas_y_modificadas(junio: RunState, septiembre: RunState) -> None:
    views = comparar_corridas(junio, septiembre, TOLERANCIA).views
    assert [v.describir() for v in views.anadidas] == ["IBIT"]
    assert [v.describir() for v in views.retiradas] == ["BNS"]
    (modificada,) = views.modificadas
    assert modificada.antes.describir() == "VOOG vs VB"
    assert modificada.delta_q == pytest.approx(0.02)  # +3 % → +5 %
    assert modificada.delta_confianza == pytest.approx(0.1)
    assert views.sin_cambio == ()


def test_pesos_y_rotacion_entre_fechas(junio: RunState, septiembre: RunState) -> None:
    diff = comparar_corridas(junio, septiembre, TOLERANCIA)
    assert [c.nombre for c in diff.pesos] == list(ACTIVOS)
    deltas = [c.delta for c in diff.pesos]
    assert all(d is not None for d in deltas)
    assert sum(d for d in deltas if d is not None) == pytest.approx(0.0, abs=1e-9)
    assert diff.rotacion_pp == pytest.approx(
        sum(abs(d) for d in deltas if d is not None) / 2.0 * 100.0
    )
    assert diff.rotacion_pp is not None and diff.rotacion_pp > 0.0
    antes, despues = junio.portafolio_final, septiembre.portafolio_final
    assert antes is not None and despues is not None
    voog = next(c for c in diff.pesos if c.nombre == "VOOG")
    assert (voog.antes, voog.despues) == (antes.pesos["VOOG"], despues.pesos["VOOG"])


def test_estimaciones_y_restricciones_cambian_con_la_fecha_y_el_tope(
    junio: RunState, septiembre: RunState
) -> None:
    diff = comparar_corridas(junio, septiembre, TOLERANCIA)
    assert len(diff.volatilidades) == len(ACTIVOS)
    assert len(diff.correlaciones) == len(ACTIVOS) * (len(ACTIVOS) - 1) // 2
    assert any(c.cambia(TOLERANCIA) for c in diff.volatilidades)
    assert all(c.delta == pytest.approx(0.5 - 0.7) for c in diff.peso_maximo)
    assert diff.metadato("fecha_decision").cambia
    assert not diff.metadato("config_hash").cambia


def test_criterio_que_cambia_de_lado(junio: RunState, septiembre: RunState) -> None:
    diff = comparar_corridas(junio, septiembre, TOLERANCIA)
    criterios = {c.nombre: c for c in diff.criterios}
    a, b = junio.ultima_validacion, septiembre.ultima_validacion
    assert a is not None and b is not None
    for nombre, criterio in criterios.items():
        antes = next(c for c in a.criterios if c.nombre == nombre)
        despues = next(c for c in b.criterios if c.nombre == nombre)
        assert criterio.cambia_de_lado == (antes.cumple != despues.cumple)
        assert (criterio.valor.antes, criterio.valor.despues) == (antes.valor, despues.valor)


def test_corrida_sin_cartera_ni_validacion(junio: RunState) -> None:
    vacia = RunState(
        run_id="vacia",
        creado_en=datetime(2026, 9, 18, tzinfo=UTC),
        fecha_decision=FECHA_ANTERIOR,
        semilla=junio.semilla,
        config_hash=OTRO_HASH,
        activos=ACTIVOS,
        universo=junio.universo,
        restricciones_sesion=junio.restricciones_sesion,
    )
    diff = comparar_corridas(vacia, junio, TOLERANCIA)
    assert diff.rotacion_pp is None
    assert all(c.antes is None and c.despues is not None for c in diff.pesos)
    assert len(diff.views.anadidas) == 2
    assert diff.metadato("veredicto").antes is None
    assert any("config.yaml distinto" in a for a in diff.advertencias)


def test_universos_distintos_no_se_comparan(junio: RunState) -> None:
    otra = RunState(
        run_id="otra",
        creado_en=datetime(2026, 9, 18, tzinfo=UTC),
        fecha_decision=FECHA_ANTERIOR,
        semilla=1,
        config_hash=OTRO_HASH,
        activos=("VOOG", "BNS"),
        universo=universo_de(("VOOG", "BNS")),
        restricciones_sesion=sesion_de(universo_de(("VOOG", "BNS"))),
    )
    with pytest.raises(CorridasIncomparablesError):
        comparar_corridas(junio, otra, TOLERANCIA)


def test_informe_markdown(junio: RunState, septiembre: RunState) -> None:
    informe = diff_markdown(comparar_corridas(junio, septiembre, TOLERANCIA), TOLERANCIA)
    assert "# Comparación de corridas: `junio` → `septiembre`" in informe
    assert "- Añadida: absoluta IBIT" in informe and "- Retirada: absoluta BNS" in informe
    assert "- Modificada: relativa VOOG vs VB: q +3.0% → +5.0% (+2.0 p.p.)" in informe
    assert "| fecha_decision ⚠ | 2026-06-30 | 2026-09-30 |" in informe
    assert "-0.0 p.p." not in informe
    assert informe.rstrip().endswith(DISCLAIMER)


def test_un_refrescar_cap_aparece_en_el_diff(config: Config, septiembre: RunState) -> None:
    """Cambiar una cap congelada es un cambio de INPUT: otra versión del universo, otra π."""
    base = universo_referencia()
    bns = base.diagnostico("BNS").model_copy(update={"prior_cap": 1.16})
    refrescado = Universe.crear(
        [bns if d.ticker == "BNS" else d for d in base.diagnosticos], base.origenes
    )
    views = septiembre.market_views.views if septiembre.market_views else ()
    despues = _corrida(config, septiembre.fecha_decision, views, "cap_nueva", universo=refrescado)
    diff = comparar_corridas(septiembre, despues, TOLERANCIA)
    assert diff.metadato("universe_version").cambia
    assert any("cambio de INPUT" in a for a in diff.advertencias)
    caps = {c.nombre: c for c in diff.prior_caps}
    assert (caps["BNS"].antes, caps["BNS"].despues) == (0.116, 1.16)
    assert not caps["VOOG"].cambia(TOLERANCIA)
    assert any(c.cambia(TOLERANCIA) for c in diff.prior_pi_total)
    informe = diff_markdown(diff, TOLERANCIA)
    assert "| BNS ⚠ | 0.116 | 1.160 | usuario | usuario |" in informe
