"""Clasificador de régimen: cada regla con series sintéticas, y sin mirar al futuro."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from investmentsys.config import RegimenConfig, cargar_config
from investmentsys.contracts import MetodoCovarianza, RegimenMercado
from investmentsys.quant import LookAheadError, clasificar_regimen, estimar

CFG: RegimenConfig = cargar_config().regimen
REFERENCIA = CFG.activos_referencia
MESES = 36


def _retornos(valores: np.ndarray, columnas: tuple[str, ...] = REFERENCIA) -> pd.DataFrame:  # type: ignore[type-arg]
    indice = pd.date_range("2023-01-31", periods=len(valores), freq="ME")
    return pd.DataFrame({c: valores for c in columnas}, index=indice)


def _ruido(semilla: int = 42, escala: float = 0.01) -> np.ndarray:  # type: ignore[type-arg]
    return np.random.default_rng(semilla).normal(0.0, escala, MESES)


def _clasificar(valores: np.ndarray) -> RegimenMercado:  # type: ignore[type-arg]
    retornos = _retornos(valores)
    return clasificar_regimen(retornos, retornos.index[-1].date(), CFG).regimen


def _con_tramo_final(paso_final: float) -> np.ndarray:  # type: ignore[type-arg]
    """Mercado plano con un vaivén fijo de ±0,2 % y un tramo final con deriva ``paso_final``."""
    valores = 0.002 * (-1.0) ** np.arange(MESES)
    valores[-CFG.ventana_tendencia_meses :] += paso_final
    return valores


def test_alcista_bajista_y_lateral_segun_la_tendencia_reciente() -> None:
    paso = 2.0 * CFG.umbral_tendencia / CFG.ventana_tendencia_meses
    assert _clasificar(_con_tramo_final(paso)) is RegimenMercado.ALCISTA
    assert _clasificar(_con_tramo_final(0.0)) is RegimenMercado.LATERAL
    # Caída ordenada: el drawdown es pequeño y la volatilidad no salta, así que no es estrés.
    assert _clasificar(_con_tramo_final(-paso)) is RegimenMercado.BAJISTA


def test_estres_exige_drawdown_y_salto_de_volatilidad() -> None:
    valores = _ruido(escala=0.01)
    valores[-CFG.ventana_volatilidad_meses :] = [-0.12, 0.06, -0.15, 0.05, -0.10, -0.04]
    retornos = _retornos(valores)
    diagnostico = clasificar_regimen(retornos, retornos.index[-1].date(), CFG)
    assert diagnostico.regimen is RegimenMercado.ESTRES
    assert diagnostico.drawdown is not None and diagnostico.drawdown >= CFG.drawdown_estres
    assert diagnostico.ratio_volatilidad is not None
    assert diagnostico.ratio_volatilidad >= CFG.ratio_volatilidad_estres
    assert "drawdown" in diagnostico.motivo


def test_muestra_corta_es_indeterminado() -> None:
    retornos = _retornos(_ruido()[: CFG.observaciones_minimas - 1])
    diagnostico = clasificar_regimen(retornos, retornos.index[-1].date(), CFG)
    assert diagnostico.regimen is RegimenMercado.INDETERMINADO
    assert diagnostico.tendencia is None


def test_datos_posteriores_a_la_fecha_de_decision_se_rechazan() -> None:
    retornos = _retornos(_ruido())
    with pytest.raises(LookAheadError):
        clasificar_regimen(retornos, retornos.index[-2].date(), CFG)


def test_el_futuro_no_cambia_el_diagnostico_de_una_fecha() -> None:
    """Sin look-ahead: truncar en la fecha da lo mismo venga lo que venga después."""
    base = _ruido()
    fecha = _retornos(base).index[-7]
    euforia, panico = base.copy(), base.copy()
    euforia[-6:], panico[-6:] = 0.2, -0.2
    diagnosticos = {
        clasificar_regimen(_retornos(v).loc[:fecha], fecha.date(), CFG) for v in (euforia, panico)
    }
    assert len(diagnosticos) == 1


def test_un_activo_de_referencia_sin_historia_no_rompe_el_indice() -> None:
    retornos = _retornos(_ruido() * 0.1 + 0.02)
    retornos.loc[retornos.index[:20], REFERENCIA[0]] = np.nan
    assert clasificar_regimen(retornos, retornos.index[-1].date(), CFG).observaciones == MESES


def test_activo_de_referencia_ausente() -> None:
    retornos = _retornos(_ruido(), columnas=("OTRO",))
    with pytest.raises(ValueError, match="sin retornos"):
        clasificar_regimen(retornos, retornos.index[-1].date(), CFG)


def test_estimar_solo_clasifica_si_recibe_la_configuracion() -> None:
    retornos = _retornos(_ruido() * 0.1 + 0.02)
    fecha: date = retornos.index[-1].date()
    comunes = {
        "fecha_decision": fecha,
        "periodos_por_anio": 12,
        "ventana_meses": MESES,
        "metodos": (MetodoCovarianza.HISTORICA,),
        "nivel_confianza": 0.95,
    }
    retornos[REFERENCIA[1]] = retornos[REFERENCIA[1]] + _ruido(7, 0.001)  # Σ no singular
    assert estimar(retornos, **comunes).regimen is RegimenMercado.INDETERMINADO  # type: ignore[arg-type]
    assert estimar(retornos, **comunes, regimen=CFG).regimen is RegimenMercado.ALCISTA  # type: ignore[arg-type]
