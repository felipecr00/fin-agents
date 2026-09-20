"""Gobernanza operativa real (Fintual Acciones). Nivel 3: código puro, sin ADK ni LLM."""

from investmentsys.fintual.cash_flow_alloc import plan_compra_neta
from investmentsys.fintual.montos import montos_fraccionados
from investmentsys.fintual.no_trade_zones import banda_de, plan_inercia
from investmentsys.fintual.tax_filter import ID_SIN_VENTAS, asesorar, plan_tras_override

__all__ = [
    "ID_SIN_VENTAS",
    "asesorar",
    "banda_de",
    "montos_fraccionados",
    "plan_compra_neta",
    "plan_inercia",
    "plan_tras_override",
]
