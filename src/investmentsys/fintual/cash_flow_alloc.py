"""Rebalanceo por flujos de caja (S11, ADR-022). Nivel 3, puro: sin ADK ni LLM.

El flujo nuevo —aportes y dividendos— se asigna 100 % a los activos que quedan BAJO su objetivo,
en proporción a lo que a cada uno le falta (su déficit sobre la cartera ya con el flujo). Cero
ventas: el contrato del plan no tiene dónde escribirlas. Como Σ(objetivo − actual) = flujo, la
suma de déficits es siempre ≥ flujo: el flujo se agota sin pasar a nadie de su objetivo.

Las No-Trade Zones (``no_trade_zones.py``) siguen activas: se reportan ANTES y DESPUÉS del
flujo. Un activo sobreponderado fuera de banda NO se vende; qué costaría hacerlo lo estima, solo
como consulta, ``tax_filter.py``. Montos fraccionados al centavo por mayor residuo: suman
exactamente el flujo.
"""

from __future__ import annotations

from collections.abc import Mapping

from investmentsys.config import FintualConfig
from investmentsys.contracts import CompraNeta, PlanCompraNeta, PlanInercia
from investmentsys.contracts.common import validar_suma
from investmentsys.fintual.montos import montos_fraccionados
from investmentsys.fintual.no_trade_zones import plan_inercia


def _pesos(montos: Mapping[str, float]) -> dict[str, float]:
    total = sum(montos.values())
    return {a: m / total for a, m in montos.items()}


def plan_compra_neta(
    objetivo: Mapping[str, float],
    montos_actuales: Mapping[str, float],
    config: FintualConfig,
    *,
    aporte_usd: float,
    dividendos_usd: float = 0.0,
    reinversion_usd: float = 0.0,
    universe_version: str,
    validado: bool,
    origen_objetivo: str,
) -> PlanCompraNeta:
    """``montos_actuales``: la cartera de hoy en US$ por activo (no pesos: tras una venta forzada
    la cartera ya no vale lo mismo). Un activo que está en una sola de las dos carteras pesa 0 en
    la otra."""
    validar_suma(objetivo, 1.0, "cartera objetivo")
    negativos = sorted(a for a, m in montos_actuales.items() if m < 0.0)
    if negativos or min(aporte_usd, dividendos_usd, reinversion_usd) < 0.0:
        raise ValueError(f"montos negativos (activos {negativos}): un flujo o tenencia no lo es")
    flujo = round(aporte_usd + dividendos_usd + reinversion_usd, config.decimales_usd)
    if flujo <= 0.0:
        raise ValueError("sin flujo nuevo (aporte o dividendos) no hay nada que asignar")
    valor = round(sum(montos_actuales.values()), config.decimales_usd)
    if valor <= 0.0:
        raise ValueError("la cartera actual no tiene valor")

    activos = [*objetivo, *(a for a in montos_actuales if a not in objetivo)]
    actuales = {a: montos_actuales.get(a, 0.0) for a in activos}
    deficits = {a: max(objetivo.get(a, 0.0) * (valor + flujo) - actuales[a], 0.0) for a in activos}
    total_deficit = sum(deficits.values())  # ≥ flujo > 0 (ver la nota del módulo)
    compras = montos_fraccionados(
        {a: d / total_deficit for a, d in deficits.items()}, flujo, config.decimales_usd
    )
    despues = {a: actuales[a] + compras[a] for a in activos}
    pesos_antes, pesos_despues = _pesos(actuales), _pesos(despues)

    def inercia(pesos: Mapping[str, float], valor_usd: float) -> PlanInercia:
        return plan_inercia(
            objetivo,
            pesos,
            valor_usd,
            config,
            universe_version=universe_version,
            validado=validado,
            origen_objetivo=origen_objetivo,
        )

    return PlanCompraNeta(
        universe_version=universe_version,
        validado=validado,
        origen_objetivo=origen_objetivo,
        valor_cartera_usd=valor,
        aporte_usd=aporte_usd,
        dividendos_usd=dividendos_usd,
        reinversion_usd=reinversion_usd,
        compras=tuple(
            CompraNeta(
                activo=a,
                monto_usd=compras[a],
                deficit_usd=deficits[a],  # exacto: redondearlo borraría déficits < 1 centavo
                peso_objetivo=objetivo.get(a, 0.0),
                peso_antes=pesos_antes[a],
                peso_despues=pesos_despues[a],
            )
            for a in activos
        ),
        inercia_antes=inercia(pesos_antes, valor),
        inercia_despues=inercia(pesos_despues, valor + flujo),
    )
