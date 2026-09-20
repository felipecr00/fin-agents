"""Bandas de inercia (No-Trade Zones) de Fintual Acciones (S10, ADR-020). Nivel 3, puro.

La banda es ABSOLUTA, en puntos porcentuales alrededor del peso objetivo: con objetivo 55 % y
banda 0.05, el rango admisible es [50 %, 60 %]. Mientras el peso actual esté dentro, la orden
del activo es ``HOLD`` obligatorio: se evitan rotación y fricción cambiaria. Fuera de banda,
aquí solo se SEÑALA (``FUERA_DE_BANDA``); cuánto comprar con aportes es de S11.
"""

from __future__ import annotations

from collections.abc import Mapping

from investmentsys.config import FintualConfig
from investmentsys.contracts import DecisionInercia, OrdenInercia, PlanInercia
from investmentsys.contracts.common import TOLERANCIA_NUMERICA, validar_suma
from investmentsys.fintual.montos import montos_fraccionados


def banda_de(activo: str, config: FintualConfig) -> float:
    return config.bandas_por_activo.get(activo, config.banda_inercia)


def plan_inercia(
    objetivo: Mapping[str, float],
    actual: Mapping[str, float],
    valor_usd: float,
    config: FintualConfig,
    *,
    universe_version: str,
    validado: bool,
    origen_objetivo: str,
) -> PlanInercia:
    """Compara la cartera ``actual`` con la ``objetivo``, activo por activo.

    Un activo que está en una sola de las dos carteras pesa 0 en la otra. El orden de las
    decisiones es el de ``objetivo`` y luego lo que solo está en ``actual``.
    """
    validar_suma(objetivo, 1.0, "cartera objetivo")
    validar_suma(actual, 1.0, "cartera actual")
    activos = [*objetivo, *(a for a in actual if a not in objetivo)]
    pesos_objetivo = {a: objetivo.get(a, 0.0) for a in activos}
    pesos_actuales = {a: actual.get(a, 0.0) for a in activos}
    montos_objetivo = montos_fraccionados(pesos_objetivo, valor_usd, config.decimales_usd)
    montos_actuales = montos_fraccionados(pesos_actuales, valor_usd, config.decimales_usd)
    decisiones = []
    for a in activos:
        desviacion = pesos_actuales[a] - pesos_objetivo[a]
        banda = banda_de(a, config)
        dentro = abs(desviacion) <= banda + TOLERANCIA_NUMERICA
        decisiones.append(
            DecisionInercia(
                activo=a,
                peso_objetivo=pesos_objetivo[a],
                peso_actual=pesos_actuales[a],
                desviacion=desviacion,
                banda=banda,
                orden=OrdenInercia.HOLD if dentro else OrdenInercia.FUERA_DE_BANDA,
                monto_objetivo_usd=montos_objetivo[a],
                monto_actual_usd=montos_actuales[a],
            )
        )
    todo_hold = all(d.orden is OrdenInercia.HOLD for d in decisiones)
    return PlanInercia(
        universe_version=universe_version,
        validado=validado,
        origen_objetivo=origen_objetivo,
        valor_cartera_usd=round(valor_usd, config.decimales_usd),
        decisiones=tuple(decisiones),
        orden_global=OrdenInercia.HOLD if todo_hold else OrdenInercia.FUERA_DE_BANDA,
    )
