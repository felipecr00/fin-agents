from __future__ import annotations

import pytest
from pydantic import ValidationError

from investmentsys.contracts import PortfolioConstraints


def test_limites_del_ejercicio(restricciones: PortfolioConstraints) -> None:
    assert restricciones.limites_ordenados() == [(0.02, 0.70)] * 4
    assert restricciones.limites("IBIT") == (0.02, 0.70)


def test_excepcion_por_activo(activos: tuple[str, ...]) -> None:
    r = PortfolioConstraints(
        activos=activos, peso_min=0.02, peso_max=0.70, limites_por_activo={"IBIT": (0.0, 0.10)}
    )
    assert r.limites("IBIT") == (0.0, 0.10)
    assert r.limites("VOOG") == (0.02, 0.70)


@pytest.mark.parametrize(
    ("peso_min", "peso_max", "mensaje"),
    [
        (0.30, 0.70, "infactible"),  # 4 × 0.30 = 1.2 > 1
        (0.00, 0.20, "infactible"),  # 4 × 0.20 = 0.8 < 1
        (0.50, 0.40, "peso_min mayor"),
        (-0.10, 0.70, "permitir_cortos"),
    ],
)
def test_restricciones_invalidas(
    activos: tuple[str, ...], peso_min: float, peso_max: float, mensaje: str
) -> None:
    with pytest.raises(ValidationError, match=mensaje):
        PortfolioConstraints(activos=activos, peso_min=peso_min, peso_max=peso_max)


def test_cortos_permiten_minimo_negativo(activos: tuple[str, ...]) -> None:
    r = PortfolioConstraints(activos=activos, peso_min=-0.2, peso_max=0.7, permitir_cortos=True)
    assert r.limites("VB") == (-0.2, 0.7)


def test_round_trip_json(restricciones: PortfolioConstraints) -> None:
    assert (
        PortfolioConstraints.model_validate_json(restricciones.model_dump_json()) == restricciones
    )
