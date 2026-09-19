"""La cartera del usuario: se valida antes de medir y no se le toca ni un peso."""

from __future__ import annotations

import pytest

from investmentsys.portfolio import CarteraInvalidaError, validar_pesos_usuario
from tests.conftest import ACTIVOS


def test_completa_con_cero_los_activos_omitidos_y_respeta_el_orden_canonico() -> None:
    pesos = validar_pesos_usuario({"vb": 0.4, " VOOG ": 0.6}, ACTIVOS)
    assert pesos == {"VOOG": 0.6, "BNS": 0.0, "IBIT": 0.0, "VB": 0.4}
    assert tuple(pesos) == ACTIVOS


@pytest.mark.parametrize(
    ("pesos", "fragmento"),
    [
        ({}, "cartera vacía"),
        ({"VOOG": 0.5, "NVDA": 0.5}, "fuera del universo vigente: ['NVDA']"),
        ({"VOOG": 1.2, "IBIT": -0.2}, "posiciones cortas"),
        ({"VOOG": 70.0, "VB": 30.0}, "son fracciones"),
        ({"VOOG": 0.5, "VB": 0.49}, "suman 0.990000"),
        ({"VOOG": float("nan"), "VB": 1.0}, "no numéricos"),
    ],
)
def test_rechaza_con_un_mensaje_que_dice_que_corregir(
    pesos: dict[str, float], fragmento: str
) -> None:
    with pytest.raises(CarteraInvalidaError) as error:
        validar_pesos_usuario(pesos, ACTIVOS)
    assert fragmento in str(error.value)
