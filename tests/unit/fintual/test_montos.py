"""``montos_fraccionados``: montos al centavo que suman EXACTAMENTE el valor de la cartera."""

from __future__ import annotations

import numpy as np
import pytest

from investmentsys.fintual import montos_fraccionados


def test_suman_exactamente_el_valor_aunque_el_redondeo_independiente_no_lo_haria() -> None:
    pesos = {"A": 1 / 3, "B": 1 / 3, "C": 1 / 3}
    montos = montos_fraccionados(pesos, 100.0, 2)
    assert montos == {"A": 33.34, "B": 33.33, "C": 33.33}  # el centavo sobrante, por orden
    assert round(sum(montos.values()), 2) == 100.0
    assert round(sum(round(p * 100.0, 2) for p in pesos.values()), 2) == 99.99  # lo ingenuo pierde


def test_el_centavo_sobrante_va_al_mayor_residuo() -> None:
    assert montos_fraccionados({"A": 0.335, "B": 0.665}, 10.01, 2) == {"A": 3.35, "B": 6.66}


def test_la_cartera_de_referencia_del_proyecto() -> None:
    pesos = {"VOOG": 0.70, "BNS": 0.07, "IBIT": 0.02, "VB": 0.21}
    montos = montos_fraccionados(pesos, 9739.94, 2)
    assert montos == {"VOOG": 6817.96, "BNS": 681.79, "IBIT": 194.80, "VB": 2045.39}
    assert round(sum(montos.values()), 2) == 9739.94


def test_es_determinista_y_cuadra_con_pesos_arbitrarios() -> None:
    rng = np.random.default_rng(42)
    for _ in range(200):
        crudos = rng.random(int(rng.integers(2, 12)))
        pesos = {f"A{i}": float(x) for i, x in enumerate(crudos / crudos.sum())}
        valor = float(rng.uniform(10.0, 1e6))
        montos = montos_fraccionados(pesos, valor, 2)
        assert montos == montos_fraccionados(pesos, valor, 2)
        assert round(sum(montos.values()) * 100) == round(valor * 100)
        assert all(abs(montos[a] - pesos[a] * valor) < 0.01 + 1e-9 for a in pesos)


@pytest.mark.parametrize(
    ("pesos", "valor", "mensaje"),
    [
        ({"A": 0.6, "B": 0.3}, 100.0, "suman"),
        ({"A": 1.2, "B": -0.2}, 100.0, "negativos"),
        ({"A": 1.0}, 0.0, "positivo"),
    ],
)
def test_entradas_invalidas(pesos: dict[str, float], valor: float, mensaje: str) -> None:
    with pytest.raises(ValueError, match=mensaje):
        montos_fraccionados(pesos, valor, 2)
