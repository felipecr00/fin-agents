"""DoD S2: una cartera diseñada para violar umbrales es rechazada con las razones correctas."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import pandas as pd
import pytest

from investmentsys.config import Config
from investmentsys.contracts import CandidatePortfolio, ValidationReport, Veredicto
from investmentsys.data import CSVPriceProvider
from investmentsys.risk import validar
from tests.conftest import FECHA
from tests.unit.risk.conftest import PESOS_REFERENCIA, candidato


def _validar(
    config: Config,
    provider: CSVPriceProvider,
    precios: pd.DataFrame,
    cand: CandidatePortfolio,
    fecha: date = FECHA,
    **kw: object,
) -> ValidationReport:
    return validar(
        cand,
        precios.loc[pd.DatetimeIndex(precios.index) <= pd.Timestamp(fecha)],
        fecha_decision=fecha,
        iteracion=1,
        validacion=config.validacion,
        optimizacion=config.optimizacion,
        periodos_por_anio=provider.periodos_por_anio,
        semilla=config.reproducibilidad.semilla,
        **kw,  # type: ignore[arg-type]
    )


def test_el_portafolio_de_referencia_es_aprobado(
    config: Config,
    provider: CSVPriceProvider,
    precios_reales: pd.DataFrame,
    candidato_referencia: CandidatePortfolio,
) -> None:
    r = _validar(config, provider, precios_reales, candidato_referencia)
    assert r.veredicto is Veredicto.APROBADA
    assert r.look_ahead_verificado
    assert r.razones_rechazo == () and r.sugerencias == ()
    assert r.candidato_evaluado == "bl_referencia" and r.pesos_evaluados == PESOS_REFERENCIA
    assert r.metricas_oos.n_periodos == 60
    assert r.metricas_oos.fecha_fin == FECHA
    assert tuple(c.nombre for c in r.criterios) == (
        "sharpe_oos_minimo",
        "max_drawdown_tolerado",
        "turnover_maximo_anual",
        "concentracion_hhi_maxima",
        "peso_max",
        "peso_min",
    )
    assert {c.nombre: c.umbral for c in r.criterios} == {
        "sharpe_oos_minimo": config.validacion.sharpe_oos_minimo,
        "max_drawdown_tolerado": config.validacion.max_drawdown_tolerado,
        "turnover_maximo_anual": config.validacion.turnover_maximo_anual,
        "concentracion_hhi_maxima": config.validacion.concentracion_hhi_maxima,
        "peso_max": config.optimizacion.peso_max,
        "peso_min": config.optimizacion.peso_min,
    }
    assert tuple(s.escenario for s in r.stress) == ("tasas_2022", "cripto_2025_26")
    assert all(s.superado for s in r.stress)
    assert r.metricas_oos.costo_transaccion_total > 0.0


def test_cartera_disenada_para_violar_umbrales_es_rechazada_con_las_razones_correctas(
    config: Config, provider: CSVPriceProvider, precios_reales: pd.DataFrame
) -> None:
    """94 % en IBIT: viola peso_max (0.70), concentración (HHI 0.885 > 0.55), max drawdown
    (IBIT cayó 50 % entre 2025-07 y 2026-06) y el stress cripto 2025-26. Cumple turnover y
    peso_min, y su Sharpe OOS es positivo: el rechazo debe listar exactamente lo violado."""
    toxica = candidato("todo_en_ibit", {"IBIT": 0.94, "VOOG": 0.02, "BNS": 0.02, "VB": 0.02})
    r = _validar(config, provider, precios_reales, toxica)

    assert r.veredicto is Veredicto.RECHAZADA
    assert r.look_ahead_verificado, "no hay look-ahead: el rechazo es por los umbrales"
    incumplidos = {c.nombre: c for c in r.criterios if not c.cumple}
    assert set(incumplidos) == {"max_drawdown_tolerado", "concentracion_hhi_maxima", "peso_max"}
    assert incumplidos["peso_max"].valor == 0.94 and incumplidos["peso_max"].umbral == 0.70
    assert incumplidos["concentracion_hhi_maxima"].valor == pytest.approx(0.94**2 + 3 * 0.02**2)
    assert incumplidos["max_drawdown_tolerado"].valor > config.validacion.max_drawdown_tolerado
    assert incumplidos["max_drawdown_tolerado"].valor == r.metricas_oos.max_drawdown

    stress = {s.escenario: s for s in r.stress}
    assert not stress["cripto_2025_26"].superado
    assert stress["cripto_2025_26"].max_drawdown > 0.35
    assert stress["tasas_2022"].superado, "en 2022 IBIT no cotizaba; su peso se reparte"

    assert r.razones_rechazo == (
        f"max_drawdown_tolerado: {r.metricas_oos.max_drawdown:.4f} vs umbral 0.35",
        f"concentracion_hhi_maxima: {0.94**2 + 3 * 0.02**2:.4f} vs umbral 0.55",
        "peso_max: 0.9400 vs umbral 0.7",
        f"stress cripto_2025_26: drawdown {stress['cripto_2025_26'].max_drawdown:.2%}",
    )
    # Cada razón trae una sugerencia concreta que apunta a IBIT.
    assert len(r.sugerencias) == 4
    assert all("IBIT" in s for s in r.sugerencias)


def test_turnover_excesivo_es_rechazado(
    config: Config, provider: CSVPriceProvider, precios_reales: pd.DataFrame
) -> None:
    def alterna(precios: pd.DataFrame, fecha: date) -> Mapping[str, float]:
        """Cada mes cambia el 100 % entre VOOG y VB: turnover 2 por mes, 24 al año."""
        todo_voog = fecha.month % 2 == 0
        return {"VOOG": 1.0 if todo_voog else 0.0, "VB": 0.0 if todo_voog else 1.0}

    r = _validar(
        config,
        provider,
        precios_reales,
        candidato("veleta", {"VOOG": 0.5, "VB": 0.5}),
        estrategia=alterna,
    )
    assert r.veredicto is Veredicto.RECHAZADA
    turnover = next(c for c in r.criterios if c.nombre == "turnover_maximo_anual")
    assert not turnover.cumple
    assert turnover.valor == pytest.approx(2.0 * 59 / 5.0)
    assert "turnover_maximo_anual" in r.razones_rechazo[0]
    assert r.metricas_oos.costo_transaccion_total == pytest.approx(59 * 2.0 * 10 / 10_000)


def test_sharpe_insuficiente_es_rechazado_en_una_ventana_bajista(
    config: Config,
    provider: CSVPriceProvider,
    precios_reales: pd.DataFrame,
    candidato_referencia: CandidatePortfolio,
) -> None:
    """Decidiendo el 2022-12-31, el backtest solo ve 2021-10 → 2022-12: retorno negativo."""
    r = _validar(config, provider, precios_reales, candidato_referencia, fecha=date(2022, 12, 31))
    assert r.veredicto is Veredicto.RECHAZADA
    sharpe = next(c for c in r.criterios if c.nombre == "sharpe_oos_minimo")
    assert not sharpe.cumple and sharpe.valor < 0.0
    assert r.metricas_oos.n_periodos == 15
    # El escenario cripto está en el futuro de esa decisión: no se evalúa (sin look-ahead).
    assert tuple(s.escenario for s in r.stress) == ("tasas_2022",)
    assert r.razones_rechazo == (f"sharpe_oos_minimo: {sharpe.valor:.4f} vs umbral 0.2",)


def test_peso_bajo_el_minimo_es_rechazado(
    config: Config, provider: CSVPriceProvider, precios_reales: pd.DataFrame
) -> None:
    r = _validar(
        config,
        provider,
        precios_reales,
        candidato("sin_ibit", {"VOOG": 0.60, "BNS": 0.15, "IBIT": 0.0, "VB": 0.25}),
    )
    assert r.veredicto is Veredicto.RECHAZADA
    assert r.razones_rechazo == ("peso_min: 0.0000 vs umbral 0.02",)
    assert r.sugerencias == ("IBIT=0.00% está por debajo de peso_min=0.02",)


def test_es_determinista(
    config: Config,
    provider: CSVPriceProvider,
    precios_reales: pd.DataFrame,
    candidato_referencia: CandidatePortfolio,
) -> None:
    a = _validar(config, provider, precios_reales, candidato_referencia)
    b = _validar(config, provider, precios_reales, candidato_referencia)
    assert a == b


def test_rechaza_candidato_con_activos_fuera_del_panel(
    config: Config, provider: CSVPriceProvider, precios_reales: pd.DataFrame
) -> None:
    with pytest.raises(ValueError, match="no tiene los activos"):
        _validar(config, provider, precios_reales, candidato("otro", {"VOOG": 0.5, "QQQ": 0.5}))
