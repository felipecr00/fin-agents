"""Tests de HRP contra el oráculo externo de ADR-003 y por propiedades."""

from __future__ import annotations

import numpy as np
import pytest

from investmentsys.config import Config
from investmentsys.contracts import (
    MetodoCovarianza,
    PortfolioConstraints,
    QuantEstimates,
    TecnicaOptimizacion,
)
from investmentsys.portfolio import optimizar_hrp, pesos_hrp
from tests.conftest import ACTIVOS

# Oráculo: PyPortfolioOpt 1.6.0 ``HRPOpt(cov_matrix=Σ).optimize(linkage_method="single")``
# con Σ la covarianza histórica híbrida de data/precios.csv (ventana 60, IBIT 32 obs.).
HRP_ORACULO = {"VOOG": 0.41497365, "BNS": 0.20307107, "IBIT": 0.05837221, "VB": 0.32358306}
TOLERANCIA_ORACULO = 1e-7


def test_reproduce_el_oraculo(estimates_reales: QuantEstimates) -> None:
    sigma = np.array(estimates_reales.covarianza(MetodoCovarianza.HISTORICA).valores)
    w = pesos_hrp(sigma)
    for i, a in enumerate(ACTIVOS):
        assert w[i] == pytest.approx(HRP_ORACULO[a], abs=TOLERANCIA_ORACULO), a


def test_pesos_suman_uno_y_son_positivos(estimates_reales: QuantEstimates) -> None:
    sigma = np.array(estimates_reales.covarianza(MetodoCovarianza.LEDOIT_WOLF).valores)
    w = pesos_hrp(sigma)
    assert w.sum() == pytest.approx(1.0)
    assert (w > 0).all()


def test_activos_independientes_reciben_varianza_inversa() -> None:
    sigma = np.diag([0.01, 0.04, 0.02, 0.05])
    w = pesos_hrp(sigma)
    assert w.sum() == pytest.approx(1.0)
    # Con Σ diagonal cada bisección reparte por varianza inversa: el más volátil pesa menos.
    assert w[0] > w[2] > w[1] > w[3]


def test_un_solo_activo() -> None:
    np.testing.assert_allclose(pesos_hrp(np.array([[0.04]])), [1.0])


def test_candidato_marca_proyeccion_cuando_viola_limites(
    config: Config, estimates_reales: QuantEstimates
) -> None:
    estrictas = PortfolioConstraints(activos=ACTIVOS, peso_min=0.10, peso_max=0.35)
    cartera = optimizar_hrp(estimates_reales, estrictas, config.optimizacion)
    assert cartera.tecnica is TecnicaOptimizacion.HRP
    assert cartera.parametros["proyectado"] is True
    assert cartera.violaciones(estrictas) == []
    assert cartera.pesos["VOOG"] == pytest.approx(0.35, abs=1e-6)
    assert cartera.pesos["IBIT"] == pytest.approx(0.10, abs=1e-6)


def test_candidato_sin_proyeccion_cuando_cumple(
    config: Config, estimates_reales: QuantEstimates, restricciones: PortfolioConstraints
) -> None:
    cartera = optimizar_hrp(estimates_reales, restricciones, config.optimizacion)
    assert cartera.parametros["proyectado"] is False
    assert cartera.violaciones(restricciones) == []
    for a in ACTIVOS:
        assert cartera.pesos[a] == pytest.approx(HRP_ORACULO[a], abs=TOLERANCIA_ORACULO)
    assert cartera.retornos_esperados is not None
    historicos = {r.activo: r.media_anual for r in estimates_reales.retornos_historicos}
    assert cartera.retornos_esperados == pytest.approx(historicos)


def test_es_determinista(
    config: Config, estimates_reales: QuantEstimates, restricciones: PortfolioConstraints
) -> None:
    a = optimizar_hrp(estimates_reales, restricciones, config.optimizacion)
    b = optimizar_hrp(estimates_reales, restricciones, config.optimizacion)
    assert a == b
