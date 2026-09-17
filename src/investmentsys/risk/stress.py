"""Stress tests históricos: los pesos propuestos sobre ventanas adversas de la muestra."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

import pandas as pd

from investmentsys.config import EscenarioStressConfig
from investmentsys.contracts import ResultadoStress
from investmentsys.contracts.common import TOLERANCIA_NUMERICA
from investmentsys.risk.backtest import backtest_walk_forward
from investmentsys.risk.estrategias import pesos_fijos
from investmentsys.risk.metricas import max_drawdown


def stress_historico(
    pesos: Mapping[str, float],
    precios: pd.DataFrame,
    escenarios: Sequence[EscenarioStressConfig],
    *,
    fecha_decision: date,
    max_drawdown_tolerado: float,
    costo_transaccion_bps: float,
    rebalanceo: str,
) -> tuple[ResultadoStress, ...]:
    """Evalúa los pesos (fijos, con el mismo rebalanceo y costos) en cada escenario.

    Se incluyen los retornos de los meses en ``[desde, hasta]``: el precio base es el cierre
    anterior a ``desde`` (o el primero del panel si no lo hay). Un escenario se recorta en
    ``fecha_decision`` y se omite si no le queda ningún período: sin datos no hay stress
    posible sin look-ahead.
    """
    indice = pd.DatetimeIndex(precios.index)
    estrategia = pesos_fijos(pesos)
    resultados: list[ResultadoStress] = []
    for escenario in escenarios:
        anteriores = indice[indice < pd.Timestamp(escenario.desde)]
        base = anteriores[-1].date() if len(anteriores) else None
        fin = min(escenario.hasta, fecha_decision)
        desde = pd.Timestamp(base or escenario.desde)
        en_ventana = indice[(indice >= desde) & (indice <= pd.Timestamp(fin))]
        if len(en_ventana) < 2:
            continue
        resultado = backtest_walk_forward(
            precios,
            estrategia,
            costo_transaccion_bps=costo_transaccion_bps,
            rebalanceo=rebalanceo,
            fecha_inicio=en_ventana[0].date(),
            fecha_fin=fin,
        )
        caida = max_drawdown(resultado.valor)
        resultados.append(
            ResultadoStress(
                escenario=escenario.nombre,
                fecha_inicio=resultado.fechas_decision[0].date(),
                fecha_fin=pd.Timestamp(resultado.valor.index[-1]).date(),
                retorno_periodo=float(resultado.valor.iloc[-1]) - 1.0,
                max_drawdown=caida,
                superado=caida <= max_drawdown_tolerado + TOLERANCIA_NUMERICA,
            )
        )
    return tuple(resultados)
