"""Rebalanceo por flujos (S11): el flujo va 100 % a lo que está bajo objetivo; cero ventas."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from investmentsys.config import FintualConfig, cargar_config
from investmentsys.contracts import DISCLAIMER_OPERATIVO, OrdenInercia, PlanCompraNeta
from investmentsys.fintual import plan_compra_neta

SELLO = "a" * 64
OBJETIVO = {"VOOG": 0.70, "BNS": 0.05, "IBIT": 0.02, "VB": 0.23}
TENENCIAS = {"VOOG": 7737.41, "BNS": 868.80, "IBIT": 658.42, "VB": 475.31}  # US$ 9739.94
FINTUAL = cargar_config().fintual


def _plan(
    tenencias: dict[str, float] = TENENCIAS,
    objetivo: dict[str, float] = OBJETIVO,
    fintual: FintualConfig = FINTUAL,
    **flujos: float,
) -> PlanCompraNeta:
    flujos = flujos or {"aporte_usd": 500.0}
    return plan_compra_neta(
        objetivo,
        tenencias,
        fintual,
        universe_version=SELLO,
        validado=True,
        origen_objetivo="cartera de prueba",
        **{"aporte_usd": 0.0, **flujos},
    )


def test_aporte_de_500_va_entero_al_unico_activo_bajo_objetivo_y_no_se_vende_nada() -> None:
    plan = _plan()
    assert {c.activo: c.monto_usd for c in plan.compras} == {
        "VOOG": 0.0,
        "BNS": 0.0,
        "IBIT": 0.0,
        "VB": 500.0,
    }
    assert plan.ventas_usd == 0.0 and plan.flujo_usd == 500.0
    assert plan.disclaimer == DISCLAIMER_OPERATIVO
    vb = next(c for c in plan.compras if c.activo == "VB")
    assert vb.peso_antes == pytest.approx(0.0488, abs=1e-4)
    assert vb.peso_despues == pytest.approx(975.31 / 10239.94, abs=1e-6)


def test_las_no_trade_zones_siguen_activas_antes_y_despues_del_flujo() -> None:
    plan = _plan()
    antes = {d.activo: d.orden for d in plan.inercia_antes.decisiones}
    despues = {d.activo: d.orden for d in plan.inercia_despues.decisiones}
    hold, fuera = OrdenInercia.HOLD, OrdenInercia.FUERA_DE_BANDA
    assert antes == {"VOOG": fuera, "BNS": hold, "IBIT": hold, "VB": fuera}
    # US$ 500 no alcanzan para devolver VOOG (+5.6 p.p.) ni VB a su banda: se dice, no se vende.
    assert despues == antes
    assert plan.inercia_despues.valor_cartera_usd == pytest.approx(10239.94)


def test_el_flujo_se_reparte_en_proporcion_a_lo_que_le_falta_a_cada_uno() -> None:
    tenencias = {"A": 8000.0, "B": 1000.0, "C": 1000.0}
    plan = _plan(tenencias, {"A": 0.5, "B": 0.3, "C": 0.2}, aporte_usd=1000.0)
    compras = {c.activo: c.monto_usd for c in plan.compras}
    # Sobre 11 000: a B le faltan 2300 y a C 1200 → 1000 × 2300/3500 y 1000 × 1200/3500.
    assert compras == {"A": 0.0, "B": 657.14, "C": 342.86}
    assert sum(compras.values()) == pytest.approx(1000.0, abs=1e-9)


def test_aportes_y_dividendos_se_suman_en_un_solo_flujo() -> None:
    plan = _plan(aporte_usd=150.0, dividendos_usd=12.37)
    assert plan.flujo_usd == pytest.approx(162.37)
    assert sum(c.monto_usd for c in plan.compras) == pytest.approx(162.37)
    solo_dividendos = _plan(dividendos_usd=12.37)
    assert [c.monto_usd for c in solo_dividendos.compras if c.monto_usd] == [12.37]


def test_un_activo_que_no_esta_en_la_cartera_actual_recibe_compras() -> None:
    plan = _plan({"VOOG": 10_000.0}, {"VOOG": 0.8, "VB": 0.2}, aporte_usd=500.0)
    assert {c.activo: c.monto_usd for c in plan.compras} == {"VOOG": 0.0, "VB": 500.0}


@pytest.mark.parametrize(
    ("flujos", "mensaje"),
    [({"aporte_usd": 0.0}, "sin flujo"), ({"aporte_usd": -5.0}, "negativos")],
)
def test_sin_flujo_o_con_flujo_negativo_no_hay_plan(flujos: dict[str, float], mensaje: str) -> None:
    with pytest.raises(ValueError, match=mensaje):
        _plan(**flujos)


_pesos = st.lists(st.floats(0.01, 1.0), min_size=2, max_size=6)


@settings(max_examples=150, deadline=None)
@given(objetivo=_pesos, actual=_pesos, valor=st.floats(100.0, 1e6), flujo=st.floats(0.01, 1e5))
def test_propiedades_del_reparto(
    objetivo: list[float], actual: list[float], valor: float, flujo: float
) -> None:
    n = min(len(objetivo), len(actual))
    activos = [f"A{i}" for i in range(n)]
    w = {a: x / sum(objetivo[:n]) for a, x in zip(activos, objetivo[:n], strict=True)}
    tenencias = {a: valor * x / sum(actual[:n]) for a, x in zip(activos, actual[:n], strict=True)}
    flujo = round(flujo, 2)
    plan = _plan(tenencias, w, aporte_usd=flujo)

    assert sum(round(c.monto_usd * 100) for c in plan.compras) == round(flujo * 100)  # al centavo
    total = plan.valor_cartera_usd + flujo
    for c in plan.compras:
        assert c.monto_usd >= 0.0
        if c.monto_usd > 0.0:  # solo lo que está bajo objetivo, y sin pasarlo de su objetivo
            assert tenencias[c.activo] < w[c.activo] * total
            assert tenencias[c.activo] + c.monto_usd <= w[c.activo] * total + 0.011
    assert plan == _plan(tenencias, w, aporte_usd=flujo)  # determinista
