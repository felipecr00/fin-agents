"""Fixtures compartidas: instancias válidas de cada contrato, con los datos del ejercicio BL."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from investmentsys.config import cargar_config
from investmentsys.contracts import (
    CandidatePortfolio,
    CandidatePortfolios,
    Criterio,
    MatrizCovarianza,
    MetodoCovarianza,
    MetricasExAnte,
    MetricasOOS,
    PortfolioConstraints,
    PriorSnapshot,
    QuantEstimates,
    RetornoEsperado,
    RunState,
    TecnicaOptimizacion,
    ValidationReport,
    Veredicto,
)
from investmentsys.portfolio import resolver_prior
from tests.almacen import sesion_de, universo_referencia
from tests.conftest import ACTIVOS, FECHA


@pytest.fixture
def activos() -> tuple[str, ...]:
    return ACTIVOS


@pytest.fixture
def fecha_decision() -> date:
    return FECHA


@pytest.fixture
def matriz_covarianza() -> MatrizCovarianza:
    return MatrizCovarianza(
        metodo=MetodoCovarianza.HISTORICA,
        activos=ACTIVOS,
        valores=(
            (0.0369, 0.0302, 0.0481, 0.0274),
            (0.0302, 0.0566, 0.0340, 0.0349),
            (0.0481, 0.0340, 0.2611, 0.0423),
            (0.0274, 0.0349, 0.0423, 0.0353),
        ),
        ventana_meses=60,
        observaciones_por_activo={"VOOG": 60, "BNS": 60, "IBIT": 32, "VB": 60},
    )


@pytest.fixture
def estimates(matriz_covarianza: MatrizCovarianza) -> QuantEstimates:
    medias = {"VOOG": 0.131, "BNS": 0.139, "IBIT": 0.212, "VB": 0.074}
    return QuantEstimates(
        fecha_decision=FECHA,
        fecha_inicio_muestra=date(2021, 9, 30),
        fecha_fin_muestra=FECHA,
        activos=ACTIVOS,
        periodos_por_anio=12,
        covarianzas={MetodoCovarianza.HISTORICA: matriz_covarianza},
        retornos_historicos=tuple(
            RetornoEsperado(
                activo=a,
                media_anual=m,
                intervalo_inferior=m - 0.1,
                intervalo_superior=m + 0.1,
                nivel_confianza=0.95,
            )
            for a, m in medias.items()
        ),
        universe_version=universo_referencia().version,
    )


@pytest.fixture
def restricciones() -> PortfolioConstraints:
    return PortfolioConstraints(activos=ACTIVOS, peso_min=0.02, peso_max=0.70)


@pytest.fixture
def candidato_bl() -> CandidatePortfolio:
    return CandidatePortfolio(
        nombre="bl_base",
        tecnica=TecnicaOptimizacion.BLACK_LITTERMAN,
        pesos={"VOOG": 0.70, "BNS": 0.07, "IBIT": 0.02, "VB": 0.21},
        metricas=MetricasExAnte(
            retorno_esperado_anual=0.1126,
            volatilidad_anual=0.1837,
            sharpe=0.40,
            concentracion_hhi=0.70**2 + 0.07**2 + 0.02**2 + 0.21**2,
        ),
        parametros={"delta": 2.5, "tau": 0.05, "metodo_omega": "he_litterman"},
    )


@pytest.fixture
def candidatos(candidato_bl: CandidatePortfolio) -> CandidatePortfolios:
    return CandidatePortfolios(
        fecha_decision=FECHA,
        activos=ACTIVOS,
        iteracion=1,
        candidatos=(candidato_bl,),
        recomendado="bl_base",
        universe_version=universo_referencia().version,
    )


@pytest.fixture
def metricas_oos() -> MetricasOOS:
    return MetricasOOS(
        fecha_inicio=date(2024, 1, 31),
        fecha_fin=FECHA,
        n_periodos=32,
        retorno_anualizado=0.12,
        volatilidad_anualizada=0.18,
        sharpe_oos=0.45,
        max_drawdown=0.22,
        turnover_anual=0.35,
        costo_transaccion_total=0.0035,
    )


@pytest.fixture
def criterios_ok() -> tuple[Criterio, ...]:
    return (
        Criterio(nombre="sharpe_oos_minimo", valor=0.45, umbral=0.20, cumple=True),
        Criterio(nombre="max_drawdown_tolerado", valor=0.22, umbral=0.35, cumple=True),
        Criterio(nombre="turnover_maximo_anual", valor=0.35, umbral=1.0, cumple=True),
    )


@pytest.fixture
def validacion_aprobada(
    candidato_bl: CandidatePortfolio,
    metricas_oos: MetricasOOS,
    criterios_ok: tuple[Criterio, ...],
) -> ValidationReport:
    return ValidationReport(
        fecha_decision=FECHA,
        iteracion=1,
        candidato_evaluado=candidato_bl.nombre,
        pesos_evaluados=candidato_bl.pesos,
        metricas_oos=metricas_oos,
        criterios=criterios_ok,
        look_ahead_verificado=True,
        veredicto=Veredicto.APROBADA,
        universe_version=universo_referencia().version,
    )


@pytest.fixture
def prior(estimates: QuantEstimates) -> PriorSnapshot:
    config = cargar_config()
    return resolver_prior(
        universo_referencia(), estimates, config.optimizacion, config.prior_equilibrio
    )


@pytest.fixture
def run_state_inicial(prior: PriorSnapshot) -> RunState:
    return RunState(
        run_id="20260930T120000-golden",
        creado_en=datetime(2026, 9, 30, 12, 0, 0),
        fecha_decision=FECHA,
        semilla=42,
        config_hash="a" * 64,
        activos=ACTIVOS,
        universo=universo_referencia(),
        restricciones_sesion=sesion_de(universo_referencia()),
        prior=prior,
    )
