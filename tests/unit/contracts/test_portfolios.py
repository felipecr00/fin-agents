from __future__ import annotations

import pytest
from pydantic import ValidationError

from investmentsys.contracts import (
    CandidatePortfolio,
    CandidatePortfolios,
    PortfolioConstraints,
    Sensibilidad,
)


def test_pesos_ordenados_y_recomendado(
    candidatos: CandidatePortfolios, activos: tuple[str, ...]
) -> None:
    assert candidatos.portafolio_recomendado.pesos_ordenados(activos) == [0.70, 0.07, 0.02, 0.21]
    assert candidatos.candidato("bl_base") is candidatos.candidatos[0]
    with pytest.raises(KeyError):
        candidatos.candidato("no_existe")


def test_round_trip_json(candidatos: CandidatePortfolios) -> None:
    assert CandidatePortfolios.model_validate_json(candidatos.model_dump_json()) == candidatos


def test_pesos_deben_sumar_uno(candidato_bl: CandidatePortfolio) -> None:
    with pytest.raises(ValidationError, match="suman"):
        CandidatePortfolio(**{**candidato_bl.model_dump(), "pesos": {"VOOG": 0.5, "VB": 0.4}})


def test_sin_violaciones_dentro_de_limites(
    candidato_bl: CandidatePortfolio, restricciones: PortfolioConstraints
) -> None:
    assert candidato_bl.violaciones(restricciones) == []


def test_detecta_violacion_de_limites(
    candidato_bl: CandidatePortfolio, activos: tuple[str, ...]
) -> None:
    estrictas = PortfolioConstraints(activos=activos, peso_min=0.05, peso_max=0.60)
    problemas = candidato_bl.violaciones(estrictas)
    assert any(p.startswith("VOOG=0.7000") for p in problemas)
    assert any(p.startswith("IBIT=0.0200") for p in problemas)
    assert len(problemas) == 2


def test_sensibilidad_debe_cubrir_el_universo(candidato_bl: CandidatePortfolio) -> None:
    with pytest.raises(ValidationError, match="sensibilidad tau"):
        CandidatePortfolio(
            **{
                **candidato_bl.model_dump(),
                "sensibilidad": (
                    Sensibilidad(
                        parametro="tau",
                        perturbacion=0.01,
                        pesos_perturbados={"VOOG": 1.0},
                        cambio_max_pp=30.0,
                    ),
                ),
            }
        )


def test_recomendado_debe_existir(candidatos: CandidatePortfolios) -> None:
    with pytest.raises(ValidationError, match="no está entre"):
        CandidatePortfolios(**{**candidatos.model_dump(), "recomendado": "otro"})


def test_nombres_unicos(candidatos: CandidatePortfolios, candidato_bl: CandidatePortfolio) -> None:
    with pytest.raises(ValidationError, match="repetidos"):
        CandidatePortfolios(
            **{**candidatos.model_dump(), "candidatos": (candidato_bl, candidato_bl)}
        )


def test_candidato_con_universo_distinto(
    candidatos: CandidatePortfolios, candidato_bl: CandidatePortfolio
) -> None:
    otro = CandidatePortfolio(**{**candidato_bl.model_dump(), "pesos": {"VOOG": 0.5, "BNS": 0.5}})
    with pytest.raises(ValidationError, match="no coincide con el universo"):
        CandidatePortfolios(**{**candidatos.model_dump(), "candidatos": (otro,)})
