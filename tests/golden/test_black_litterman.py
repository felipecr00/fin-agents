"""Golden test: el ejercicio de referencia de Black-Litterman (ver CLAUDE.md).

Codifica ``docs/referencia_black_litterman.py`` contra ``data/precios.csv``. Si este test se
rompe, el núcleo está mal: no se ajusta el test para que pase.

En S0 los módulos ``quant/`` y ``portfolio/`` son stubs que lanzan ``NotImplementedError``;
por eso cada test lleva ``xfail(raises=NotImplementedError, strict=True)``: falla por la
razón correcta (no por imports) y, en cuanto S1 implemente el núcleo, el marcador hará
fallar la suite hasta que se retire.
"""

from __future__ import annotations

from datetime import date

import pytest

from investmentsys.config import Config, cargar_config
from investmentsys.contracts import (
    CandidatePortfolio,
    MarketViews,
    MatrizCovarianza,
    MetodoCovarianza,
    PortfolioConstraints,
    QuantEstimates,
    TecnicaOptimizacion,
)
from investmentsys.data import CSVPriceProvider
from investmentsys.portfolio import optimizar_black_litterman
from investmentsys.quant import estimar, estimar_covarianza

FECHA_DECISION = date(2026, 9, 30)

# Valores esperados del ejercicio de referencia. Son el oráculo del test, no parámetros
# del sistema: por eso viven aquí y no en config.yaml.
PESOS_ESPERADOS = {"VOOG": 0.70, "BNS": 0.07, "IBIT": 0.02, "VB": 0.21}
TOLERANCIA_PESOS = 0.02  # ±2 puntos porcentuales (CLAUDE.md)

VOLATILIDADES_ESPERADAS = {"VOOG": 0.1917, "BNS": 0.2376, "IBIT": 0.5112, "VB": 0.1883}
CORRELACIONES_ESPERADAS = {
    ("VOOG", "BNS"): 0.6554,
    ("VOOG", "IBIT"): 0.4913,
    ("VOOG", "VB"): 0.7578,
    ("BNS", "IBIT"): 0.2764,
    ("BNS", "VB"): 0.7809,
    ("IBIT", "VB"): 0.4407,
}
OBSERVACIONES_ESPERADAS = {"VOOG": 60, "BNS": 60, "IBIT": 32, "VB": 60}
TOLERANCIA_ESTIMACION = 0.005

# Retornos totales esperados del posterior (μ_BL + rf) y métricas ex ante de la cartera.
RETORNOS_POSTERIOR_ESPERADOS = {"VOOG": 0.1190, "BNS": 0.1022, "IBIT": 0.1105, "VB": 0.0950}
METRICAS_ESPERADAS = {"retorno_esperado_anual": 0.1126, "volatilidad_anual": 0.1837}
TOLERANCIA_METRICAS = 0.0025

pendiente_s1 = pytest.mark.xfail(
    raises=NotImplementedError,
    strict=True,
    reason="S1 pendiente: quant/ y portfolio/ son stubs que lanzan NotImplementedError",
)


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config()


@pytest.fixture(scope="module")
def provider(config: Config) -> CSVPriceProvider:
    return CSVPriceProvider(config.datos.ruta_csv)


@pytest.fixture(scope="module")
def activos(config: Config) -> tuple[str, ...]:
    return config.portafolio.activos


@pytest.fixture(scope="module")
def restricciones(config: Config) -> PortfolioConstraints:
    return PortfolioConstraints(
        activos=config.portafolio.activos,
        peso_min=config.optimizacion.peso_min,
        peso_max=config.optimizacion.peso_max,
        permitir_cortos=config.optimizacion.permitir_cortos,
    )


def _covarianza_historica(
    config: Config, provider: CSVPriceProvider, activos: tuple[str, ...]
) -> MatrizCovarianza:
    retornos = provider.retornos_log(activos, hasta=FECHA_DECISION)
    return estimar_covarianza(
        retornos,
        metodo=MetodoCovarianza.HISTORICA,
        ventana_meses=config.datos.ventana_covarianza_meses,
        periodos_por_anio=provider.periodos_por_anio,
    )


def _estimates(
    config: Config, provider: CSVPriceProvider, activos: tuple[str, ...]
) -> QuantEstimates:
    retornos = provider.retornos_log(activos, hasta=FECHA_DECISION)
    return estimar(
        retornos,
        fecha_decision=FECHA_DECISION,
        periodos_por_anio=provider.periodos_por_anio,
        ventana_meses=config.datos.ventana_covarianza_meses,
        metodos=(MetodoCovarianza.HISTORICA,),
    )


def _optimizar(
    config: Config,
    provider: CSVPriceProvider,
    activos: tuple[str, ...],
    views_golden: MarketViews,
    restricciones: PortfolioConstraints,
) -> CandidatePortfolio:
    return optimizar_black_litterman(
        _estimates(config, provider, activos),
        views_golden,
        restricciones,
        optimizacion=config.optimizacion,
        prior=config.prior_equilibrio,
    )


def test_el_ejercicio_esta_bien_parametrizado(
    config: Config, views_golden: MarketViews, restricciones: PortfolioConstraints
) -> None:
    """Sin xfail: comprueba que los inputs del ejercicio están en config y en el contrato."""
    assert config.optimizacion.aversion_riesgo_delta == 2.5
    assert config.optimizacion.tau == 0.05
    assert config.optimizacion.tasa_libre_riesgo == 0.04
    assert config.optimizacion.metodo_omega == "he_litterman"
    assert restricciones.limites_ordenados() == [(0.02, 0.70)] * 4
    assert views_golden.fecha_decision == FECHA_DECISION
    assert views_golden.matriz_p() == [[0, 0, 1, 0], [1, 0, 0, -1], [0, 1, 0, 0]]
    assert views_golden.vector_q() == [0.03, 0.03, 0.10]
    assert set(PESOS_ESPERADOS) == set(config.portafolio.activos)
    assert sum(PESOS_ESPERADOS.values()) == pytest.approx(1.0)


@pytest.mark.golden
@pendiente_s1
def test_covarianza_historica_reproduce_la_referencia(
    config: Config, provider: CSVPriceProvider, activos: tuple[str, ...]
) -> None:
    cov = _covarianza_historica(config, provider, activos)
    assert cov.activos == activos
    assert cov.observaciones_por_activo == OBSERVACIONES_ESPERADAS
    for a, vol in VOLATILIDADES_ESPERADAS.items():
        assert cov.volatilidad(a) == pytest.approx(vol, abs=TOLERANCIA_ESTIMACION), a
    for (a, b), rho in CORRELACIONES_ESPERADAS.items():
        i, j = activos.index(a), activos.index(b)
        observada = cov.valores[i][j] / (cov.volatilidad(a) * cov.volatilidad(b))
        assert observada == pytest.approx(rho, abs=TOLERANCIA_ESTIMACION), (a, b)


@pytest.mark.golden
@pendiente_s1
def test_black_litterman_reproduce_los_pesos_del_ejercicio(
    config: Config,
    provider: CSVPriceProvider,
    activos: tuple[str, ...],
    views_golden: MarketViews,
    restricciones: PortfolioConstraints,
) -> None:
    cartera = _optimizar(config, provider, activos, views_golden, restricciones)
    assert cartera.tecnica is TecnicaOptimizacion.BLACK_LITTERMAN
    assert cartera.violaciones(restricciones) == []
    for a, esperado in PESOS_ESPERADOS.items():
        assert cartera.pesos[a] == pytest.approx(esperado, abs=TOLERANCIA_PESOS), a


@pytest.mark.golden
@pendiente_s1
def test_black_litterman_posterior_y_metricas(
    config: Config,
    provider: CSVPriceProvider,
    activos: tuple[str, ...],
    views_golden: MarketViews,
    restricciones: PortfolioConstraints,
) -> None:
    cartera = _optimizar(config, provider, activos, views_golden, restricciones)
    assert cartera.retornos_esperados is not None
    for a, esperado in RETORNOS_POSTERIOR_ESPERADOS.items():
        assert cartera.retornos_esperados[a] == pytest.approx(esperado, abs=TOLERANCIA_METRICAS), a
    for nombre, esperado in METRICAS_ESPERADAS.items():
        assert getattr(cartera.metricas, nombre) == pytest.approx(esperado, abs=TOLERANCIA_METRICAS)
