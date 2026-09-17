"""Validación adversarial: backtest walk-forward, stress, look-ahead y veredicto. Sin ADK ni LLM."""

from investmentsys.risk.backtest import (
    PERIODOS_ENTRE_REBALANCEOS,
    Estrategia,
    ResultadoBacktest,
    backtest_walk_forward,
)
from investmentsys.risk.estrategias import pesos_fijos, reestimada, retornos_log
from investmentsys.risk.look_ahead import (
    PERTURBACIONES,
    LookAheadDetectadoError,
    perturbaciones,
    verificar_look_ahead,
)
from investmentsys.risk.metricas import (
    concentracion_hhi,
    drawdown_por_activo,
    max_drawdown,
    metricas_oos,
)
from investmentsys.risk.stress import stress_historico
from investmentsys.risk.validacion import validar

__all__ = [
    "PERIODOS_ENTRE_REBALANCEOS",
    "PERTURBACIONES",
    "Estrategia",
    "LookAheadDetectadoError",
    "ResultadoBacktest",
    "backtest_walk_forward",
    "concentracion_hhi",
    "drawdown_por_activo",
    "max_drawdown",
    "metricas_oos",
    "perturbaciones",
    "pesos_fijos",
    "reestimada",
    "retornos_log",
    "stress_historico",
    "validar",
    "verificar_look_ahead",
]
