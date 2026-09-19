"""Cascada del prior de equilibrio (ADR-013): procedencias, todo-o-nada y tabla π."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

from investmentsys.config import Config, cargar_config
from investmentsys.contracts import (
    ADVERTENCIA_PRIOR_NEUTRAL,
    ADVERTENCIA_PRIOR_SOLO_VIEWS,
    MarketViews,
    MetodoCovarianza,
    MetodoPrior,
    PortfolioConstraints,
    PriorProvenance,
    QuantEstimates,
    Universe,
)
from investmentsys.data import CSVPriceProvider
from investmentsys.portfolio import (
    PriorNoDisponibleError,
    optimizar_black_litterman,
    resolver_prior,
)
from investmentsys.quant import estimar
from tests.almacen import sembrar_gestor
from tests.conftest import ACTIVOS, CSV_REFERENCIA, FECHA


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config()


@pytest.fixture(scope="module")
def universo(config: Config, tmp_path_factory: pytest.TempPathFactory) -> Universe:
    return sembrar_gestor(tmp_path_factory.mktemp("almacen"), config).universo()


def _estimates(config: Config, universo: Universe) -> QuantEstimates:
    provider = CSVPriceProvider(CSV_REFERENCIA)
    return estimar(
        provider.retornos_log(universo.activos, hasta=FECHA),
        fecha_decision=FECHA,
        periodos_por_anio=provider.periodos_por_anio,
        ventana_meses=config.datos.ventana_covarianza_meses,
        metodos=(MetodoCovarianza.HISTORICA,),
        nivel_confianza=config.estimacion.nivel_confianza,
        universe_version=universo.version,
    )


def _sin_cap(universo: Universe, ticker: str, neutral: bool) -> Universe:
    vacio = {
        "prior_cap": None,
        "prior_provenance": None,
        "prior_fuente_detalle": None,
        "prior_as_of": None,
    }
    ds = [d.model_copy(update=vacio) if d.ticker == ticker else d for d in universo.diagnosticos]
    return Universe.crear(ds, universo.origenes, prior_neutral_aceptado=neutral)


def test_prior_de_mercado_reproduce_pi_del_ejercicio(config: Config, universo: Universe) -> None:
    snap = resolver_prior(
        universo, _estimates(config, universo), config.optimizacion, config.prior_equilibrio
    )
    assert snap.metodo is MetodoPrior.CAPITALIZACION and snap.advertencia is None
    assert snap.universe_version == universo.version
    assert set(snap.procedencias.values()) == {PriorProvenance.USUARIO}
    pi = {a.activo: a.pi_exceso for a in snap.activos}
    # ADR-013: π en exceso con las caps pinneadas (IBIT ≈ 15 %).
    assert pi == pytest.approx(
        {"VOOG": 0.0917, "BNS": 0.0764, "IBIT": 0.1503, "VB": 0.0722}, abs=5e-4
    )
    assert all(a.pi_total == pytest.approx(a.pi_exceso + 0.04) for a in snap.activos)
    assert all(a.cap and a.fuente_detalle and a.as_of for a in snap.activos)


def test_el_camino_por_universe_da_exactamente_los_pesos_del_golden(
    config: Config, universo: Universe, views_golden: MarketViews
) -> None:
    """Las caps pinneadas del universo de referencia SON las de config: dos caminos, una cartera."""
    estimates = _estimates(config, universo)
    restricciones = PortfolioConstraints(
        activos=ACTIVOS,
        peso_min=config.optimizacion.peso_min,
        peso_max=config.optimizacion.peso_max,
    )
    snap = resolver_prior(universo, estimates, config.optimizacion, config.prior_equilibrio)
    por_universo = optimizar_black_litterman(
        estimates, views_golden, restricciones, config.optimizacion, snap
    )
    por_config = optimizar_black_litterman(
        estimates, views_golden, restricciones, config.optimizacion, config.prior_equilibrio
    )
    assert por_universo.pesos == pytest.approx(por_config.pesos, abs=1e-9)
    assert por_universo.pesos == pytest.approx(
        {"VOOG": 0.70, "BNS": 0.07, "IBIT": 0.02, "VB": 0.21}, abs=0.02
    )


def test_falta_una_cap_sin_aceptar_neutral_bl_no_disponible(
    config: Config, universo: Universe
) -> None:
    pendiente = _sin_cap(universo, "IBIT", neutral=False)
    with pytest.raises(PriorNoDisponibleError, match="falta la capitalización de IBIT") as exc:
        resolver_prior(
            pendiente, _estimates(config, pendiente), config.optimizacion, config.prior_equilibrio
        )
    assert "HRP y mínima varianza siguen operativos" in str(exc.value)


def test_degradacion_aceptada_todo_el_vector_neutral(config: Config, universo: Universe) -> None:
    neutral = _sin_cap(universo, "IBIT", neutral=True)
    snap = resolver_prior(
        neutral, _estimates(config, neutral), config.optimizacion, config.prior_equilibrio
    )
    assert snap.metodo is MetodoPrior.NEUTRAL and snap.advertencia == ADVERTENCIA_PRIOR_NEUTRAL
    assert set(snap.procedencias.values()) == {PriorProvenance.NEUTRAL}
    assert snap.pesos_mercado == pytest.approx(dict.fromkeys(ACTIVOS, 0.25))
    assert all(a.cap is None for a in snap.activos)  # ni siquiera las caps que sí existen
    # ADR-013: equal-weight NO es agnóstico (IBIT ≈ 24 % en exceso, frente a ≈ 15 % con caps).
    assert next(a for a in snap.activos if a.activo == "IBIT").pi_exceso == pytest.approx(
        0.2409, abs=5e-4
    )


def test_solo_views_disponible_por_config(
    config: Config, universo: Universe, views_golden: MarketViews
) -> None:
    neutral = _sin_cap(universo, "IBIT", neutral=True)
    prior = config.prior_equilibrio.model_copy(update={"degradacion": "solo_views"})
    estimates = _estimates(config, neutral)
    snap = resolver_prior(neutral, estimates, config.optimizacion, prior)
    assert (
        snap.metodo is MetodoPrior.SOLO_VIEWS and snap.advertencia == ADVERTENCIA_PRIOR_SOLO_VIEWS
    )
    assert snap.pesos_mercado is None and all(a.pi_exceso == 0.0 for a in snap.activos)
    restricciones = PortfolioConstraints(activos=ACTIVOS, peso_min=0.02, peso_max=0.70)
    cartera = optimizar_black_litterman(
        estimates, views_golden, restricciones, config.optimizacion, snap
    )
    assert sum(cartera.pesos.values()) == pytest.approx(1.0)


def test_sellos_distintos_se_rechazan(
    config: Config, universo: Universe, views_golden: MarketViews
) -> None:
    otro = _sin_cap(universo, "IBIT", neutral=True)
    with pytest.raises(ValueError, match="otra versión del universo"):
        resolver_prior(
            otro, _estimates(config, universo), config.optimizacion, config.prior_equilibrio
        )
    snap = resolver_prior(
        otro, _estimates(config, otro), config.optimizacion, config.prior_equilibrio
    )
    restricciones = PortfolioConstraints(activos=ACTIVOS, peso_min=0.02, peso_max=0.70)
    with pytest.raises(ValueError, match="versiones distintas del universo"):
        optimizar_black_litterman(
            _estimates(config, universo), views_golden, restricciones, config.optimizacion, snap
        )


def test_el_universo_de_referencia_del_repo_lleva_las_caps_de_config(config: Config) -> None:
    """``data/universo.json`` se sembró con las caps pinneadas; cambiarlas es ``refrescar_cap``
    (que deja rastro en el historial), nunca una edición a mano de uno de los dos archivos."""
    raiz = Path(__file__).resolve().parents[3]
    vivo = Universe.model_validate_json(
        (raiz / config.datos.gestor.ruta_universo).read_text("utf-8")
    )
    iniciales = {d.ticker: d for d in vivo.diagnosticos if d.ticker in config.portafolio.activos}
    assert set(iniciales) == set(config.portafolio.activos)
    assert all(
        d.tiene_cap and d.prior_as_of and d.prior_as_of <= date.today() for d in iniciales.values()
    )
    assert np.isfinite([d.prior_cap or np.nan for d in iniciales.values()]).all()
