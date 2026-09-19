"""Sensibilidad de Black-Litterman: rejilla completa, determinista, factible y bien medida."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

from investmentsys.config import Config, cargar_config
from investmentsys.contracts import (
    DISCLAIMER,
    MarketViews,
    MetodoCovarianza,
    PortfolioConstraints,
    QuantEstimates,
)
from investmentsys.data import CSVPriceProvider
from investmentsys.portfolio import optimizar_black_litterman
from investmentsys.portfolio._comun import matriz
from investmentsys.quant import estimar
from investmentsys.risk.informe_sensibilidad import Escenario, informe_markdown
from investmentsys.risk.sensibilidad import (
    AnalisisSensibilidad,
    Familia,
    MatrizNoDefinidaPositivaError,
    Supuesto,
    analizar_sensibilidad,
    escalar_correlacion,
    escalar_volatilidad,
)
from tests.conftest import ACTIVOS, FECHA

RAIZ = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config()


@pytest.fixture(scope="module")
def estimates(config: Config) -> QuantEstimates:
    provider = CSVPriceProvider(RAIZ / config.datos.ruta_csv)
    return estimar(
        provider.retornos_log(ACTIVOS, hasta=FECHA),
        fecha_decision=FECHA,
        periodos_por_anio=provider.periodos_por_anio,
        ventana_meses=config.datos.ventana_covarianza_meses,
        metodos=(MetodoCovarianza.HISTORICA,),
        nivel_confianza=config.estimacion.nivel_confianza,
    )


@pytest.fixture(scope="module")
def restricciones(config: Config) -> PortfolioConstraints:
    opt = config.optimizacion
    return PortfolioConstraints(activos=ACTIVOS, peso_min=opt.peso_min, peso_max=opt.peso_max)


def _analizar(
    config: Config,
    estimates: QuantEstimates,
    views: MarketViews,
    restricciones: PortfolioConstraints,
    **rejilla: tuple[float, ...],
) -> AnalisisSensibilidad:
    sensibilidad = config.sensibilidad.model_copy(update=rejilla)
    return analizar_sensibilidad(
        estimates, views, restricciones, config.optimizacion, config.prior_equilibrio, sensibilidad
    )


def _views_de_referencia() -> MarketViews:
    """Las de ``views_golden`` (fixture de función), para la fixture de módulo ``analisis``."""
    return MarketViews.model_validate(
        {
            "fecha_decision": FECHA,
            "activos": ACTIVOS,
            "horizonte_meses": 12,
            "resumen": "Ejercicio de referencia.",
            "views": [
                _view_cruda("absoluta", {"IBIT": 1.0}, 0.03),
                _view_cruda("relativa", {"VOOG": 1.0, "VB": -1.0}, 0.03),
                _view_cruda("absoluta", {"BNS": 1.0}, 0.10),
            ],
        }
    )


def _view_cruda(tipo: str, coeficientes: dict[str, float], q: float) -> dict[str, object]:
    return {
        "tipo": tipo,
        "coeficientes": coeficientes,
        "q_anual": q,
        "confianza": 0.5,
        "justificacion": "Ejercicio de referencia.",
        "fuente": "ejercicio de referencia",
    }


def test_las_views_de_este_modulo_son_las_del_golden(views_golden: MarketViews) -> None:
    propias = _views_de_referencia()
    assert propias.matriz_p() == views_golden.matriz_p()
    assert propias.vector_q() == views_golden.vector_q()


@pytest.fixture(scope="module")
def analisis(
    config: Config, estimates: QuantEstimates, restricciones: PortfolioConstraints
) -> AnalisisSensibilidad:
    return _analizar(config, estimates, _views_de_referencia(), restricciones)


def test_la_cartera_base_es_la_del_optimizador(
    analisis: AnalisisSensibilidad,
    config: Config,
    estimates: QuantEstimates,
    views_golden: MarketViews,
    restricciones: PortfolioConstraints,
) -> None:
    candidato = optimizar_black_litterman(
        estimates, views_golden, restricciones, config.optimizacion, config.prior_equilibrio
    )
    assert analisis.pesos_base == pytest.approx(candidato.pesos)
    assert analisis.limites_activos == ("VOOG=max", "IBIT=min")


def test_rejilla_completa_un_supuesto_a_la_vez(
    analisis: AnalisisSensibilidad, config: Config
) -> None:
    s = config.sensibilidad
    n, pares, views = len(ACTIVOS), len(ACTIVOS) * (len(ACTIVOS) - 1) // 2, 3
    esperado = {
        Familia.VIEWS_Q: 2 * len(s.retornos_pp) * views,
        Familia.MU_POSTERIOR: 2 * len(s.retornos_pp) * n,
        Familia.VOLATILIDAD: 2 * len(s.covarianza_rel) * n,
        Familia.CORRELACION: 2 * len(s.covarianza_rel) * pares,
        Familia.COVARIANZA_GLOBAL: 2 * len(s.covarianza_rel),
        Familia.PARAMETROS: 2 * len(s.parametros_rel) * 2,
    }
    conteo = {f: sum(p.familia is f for p in analisis.perturbaciones) for f in Familia}
    assert conteo == esperado
    assert analisis.omitidas == ()
    magnitudes = {p.magnitud for p in analisis.perturbaciones if p.familia is Familia.VIEWS_Q}
    assert magnitudes == {m * signo for m in s.retornos_pp for signo in (-1.0, 1.0)}


def test_toda_cartera_perturbada_es_factible(
    analisis: AnalisisSensibilidad, restricciones: PortfolioConstraints
) -> None:
    for p in analisis.perturbaciones:
        assert sum(p.pesos.values()) == pytest.approx(1.0)
        for activo, peso in p.pesos.items():
            lo, hi = restricciones.limites(activo)
            assert lo - 1e-9 <= peso <= hi + 1e-9, f"{p.familia}:{p.parametro}"


def test_las_medidas_de_desplazamiento_salen_de_los_pesos(analisis: AnalisisSensibilidad) -> None:
    for p in analisis.perturbaciones:
        cambios = {a: abs(p.pesos[a] - analisis.pesos_base[a]) * 100.0 for a in ACTIVOS}
        assert p.cambio_max_pp == pytest.approx(max(cambios.values()))
        assert p.rotacion_pp == pytest.approx(sum(cambios.values()) / 2.0)
        assert cambios[p.activo_mas_afectado] == pytest.approx(p.cambio_max_pp)


def test_determinista(
    analisis: AnalisisSensibilidad,
    config: Config,
    estimates: QuantEstimates,
    views_golden: MarketViews,
    restricciones: PortfolioConstraints,
) -> None:
    assert _analizar(config, estimates, views_golden, restricciones) == analisis


def test_el_peso_de_un_activo_no_decrece_cuando_sube_su_mu(analisis: AnalisisSensibilidad) -> None:
    """Propiedad del QP convexo: w_i es monótono no decreciente en μ_i (con el resto fijo)."""
    mu = [p for p in analisis.perturbaciones if p.familia is Familia.MU_POSTERIOR]
    for activo in ACTIVOS:
        serie = sorted((p for p in mu if p.parametro == activo), key=lambda p: p.magnitud)
        pesos = [p.pesos[activo] for p in serie]
        assert all(b >= a - 1e-9 for a, b in pairwise(pesos)), activo
        bajadas = [p for p in serie if p.magnitud < 0]
        assert all(p.pesos[activo] <= analisis.pesos_base[activo] + 1e-9 for p in bajadas)


def test_resumenes_ordenados_de_mas_a_menos_fragil(analisis: AnalisisSensibilidad) -> None:
    medias = [f.cambio_max_pp_medio for f in analisis.por_familia()]
    assert medias == sorted(medias, reverse=True)
    por_supuesto = list(analisis.por_supuesto().values())
    assert por_supuesto == sorted(por_supuesto, reverse=True)
    assert analisis.supuesto_mas_fragil() is next(iter(analisis.por_supuesto()))


def test_hallazgo_del_informe_de_s5_la_referencia_es_mas_fragil_a_los_retornos(
    analisis: AnalisisSensibilidad,
) -> None:
    """``docs/sensibilidad.md`` lo afirma con estos datos; si deja de ser cierto, se reescribe."""
    assert analisis.supuesto_mas_fragil() is Supuesto.RETORNOS
    assert analisis.por_familia()[0].familia is Familia.MU_POSTERIOR


def test_una_sigma_invalida_se_omite_y_se_informa(
    config: Config,
    estimates: QuantEstimates,
    views_golden: MarketViews,
    restricciones: PortfolioConstraints,
) -> None:
    """ρ(BNS, VB) = 0.78: escalarla +90 % la saca de [-1, 1] y Σ deja de ser una covarianza."""
    analisis = _analizar(config, estimates, views_golden, restricciones, covarianza_rel=(0.9,))
    assert any("correlacion:BNS-VB +90%" in o for o in analisis.omitidas)
    assert all("correlacion" in o for o in analisis.omitidas)
    assert any(p.familia is Familia.VOLATILIDAD for p in analisis.perturbaciones)


def test_escalar_volatilidad_conserva_las_correlaciones(estimates: QuantEstimates) -> None:
    sigma = matriz(estimates, MetodoCovarianza.HISTORICA)
    nueva = escalar_volatilidad(sigma, 1, 1.2)

    def correlaciones(m: np.ndarray) -> np.ndarray:  # type: ignore[type-arg]
        d = np.sqrt(np.diag(m))
        return np.asarray(m / np.outer(d, d))

    assert np.sqrt(nueva[1, 1]) == pytest.approx(1.2 * np.sqrt(sigma[1, 1]))
    assert np.sqrt(nueva[0, 0]) == pytest.approx(np.sqrt(sigma[0, 0]))
    assert np.allclose(correlaciones(nueva), correlaciones(sigma))


def test_escalar_correlacion_solo_toca_el_par(estimates: QuantEstimates) -> None:
    sigma = matriz(estimates, MetodoCovarianza.HISTORICA)
    nueva = escalar_correlacion(sigma, 0, 3, 0.8)
    assert nueva[0, 3] == pytest.approx(0.8 * sigma[0, 3]) and nueva[3, 0] == nueva[0, 3]
    intactos = np.ones_like(sigma, dtype=bool)
    intactos[0, 3] = intactos[3, 0] = False
    assert np.array_equal(nueva[intactos], sigma[intactos])
    with pytest.raises(MatrizNoDefinidaPositivaError):
        escalar_correlacion(sigma, 1, 3, 1.9)


def test_cada_perturbacion_cabe_en_el_contrato_sensibilidad(
    analisis: AnalisisSensibilidad,
    config: Config,
    estimates: QuantEstimates,
    views_golden: MarketViews,
    restricciones: PortfolioConstraints,
) -> None:
    """Pendiente de S1: ``CandidatePortfolio.sensibilidad`` ya se puede poblar con esto."""
    candidato = optimizar_black_litterman(
        estimates, views_golden, restricciones, config.optimizacion, config.prior_equilibrio
    )
    sensibilidad = tuple(p.a_contrato() for p in analisis.perturbaciones)
    con_sensibilidad = candidato.model_validate(
        {**candidato.model_dump(), "sensibilidad": [s.model_dump() for s in sensibilidad]}
    )
    assert len(con_sensibilidad.sensibilidad) == len(analisis.perturbaciones)


def test_el_informe_concluye_con_las_cifras_y_lleva_el_disclaimer(
    analisis: AnalisisSensibilidad, views_golden: MarketViews
) -> None:
    escenario = Escenario(nombre="Límites reales", limites="2 %-70 %", analisis=analisis)
    informe = informe_markdown((escenario,), views_golden, "referencia", "abc123", "rejilla")
    media = analisis.por_supuesto()[Supuesto.RETORNOS]
    assert f"más frágil a: **retornos esperados** ({media:.1f} p.p." in informe
    assert "VOOG=max, IBIT=min" in informe
    assert informe.rstrip().endswith(DISCLAIMER)
