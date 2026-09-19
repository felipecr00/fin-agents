"""Chequeos de factibilidad de las restricciones (S7 §3): cada uno con su mensaje."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from investmentsys.config import cargar_config
from investmentsys.contracts import (
    LimiteActivo,
    OrigenRestriccion,
    SessionConstraints,
)
from investmentsys.portfolio import (
    RestriccionesInfactiblesError,
    restricciones_de_iteracion,
    sesion_por_defecto,
)
from tests.almacen import universo_de, universo_referencia

OPT = cargar_config().optimizacion


def _sesion(**limites: LimiteActivo) -> SessionConstraints:
    base = sesion_por_defecto(universo_referencia(), OPT)
    return SessionConstraints.model_validate({**base.model_dump(), "limites_por_activo": limites})


def test_sin_overrides_son_las_de_la_sesion() -> None:
    pc = restricciones_de_iteracion(_sesion(), {})
    assert pc.limites_ordenados() == [(0.02, 0.70)] * 4 and pc.limites_por_activo == {}


def test_endurecer_un_maximo() -> None:
    pc = restricciones_de_iteracion(_sesion(), {"VOOG": 0.5})
    assert pc.limites("VOOG") == (0.02, 0.5) and pc.limites("VB") == (0.02, 0.70)


def test_1_piso_por_n_supera_el_cien_por_cien() -> None:
    muchos = universo_de([f"A{i}" for i in range(6)])
    caro = OPT.model_copy(update={"peso_min": 0.20})
    with pytest.raises(ValidationError, match=r"pisos suman 120\.00% > 100 %"):
        sesion_por_defecto(muchos, caro)


def test_2_los_techos_no_alcanzan_el_cien_por_cien() -> None:
    with pytest.raises(RestriccionesInfactiblesError, match=r"techos suman 80\.00% < 100 %"):
        restricciones_de_iteracion(_sesion(), dict.fromkeys(("VOOG", "BNS", "IBIT", "VB"), 0.2))
    pocos = universo_de(["AA", "BB"])
    with pytest.raises(ValidationError, match=r"techos suman 80\.00% < 100 %"):
        sesion_por_defecto(pocos, OPT.model_copy(update={"peso_max": 0.40}))


def test_3_un_override_solo_endurece_respecto_a_la_sesion() -> None:
    with pytest.raises(RestriccionesInfactiblesError, match=r"VOOG: .*solo puede ENDURECER"):
        restricciones_de_iteracion(_sesion(), {"VOOG": 0.8})
    # La referencia es la SESIÓN, no config: el usuario ya había bajado IBIT al 10 %.
    propio = LimiteActivo(minimo=0.02, maximo=0.10, origen=OrigenRestriccion.AJUSTE_USUARIO)
    with pytest.raises(RestriccionesInfactiblesError, match=r"IBIT: .*vigente en la sesión es 10"):
        restricciones_de_iteracion(_sesion(IBIT=propio), {"IBIT": 0.30})
    assert restricciones_de_iteracion(_sesion(IBIT=propio), {"IBIT": 0.05}).limites("IBIT") == (
        0.02,
        0.05,
    )


def test_4_tickers_del_override_fuera_del_universo() -> None:
    with pytest.raises(RestriccionesInfactiblesError, match=r"fuera del universo.*\['TSLA'\]"):
        restricciones_de_iteracion(_sesion(), {"TSLA": 0.3})


def test_5_un_override_nunca_baja_del_piso() -> None:
    with pytest.raises(RestriccionesInfactiblesError, match=r"IBIT: máximo 1\.00% por debajo"):
        restricciones_de_iteracion(_sesion(), {"IBIT": 0.01})
    propio = LimiteActivo(minimo=0.10, maximo=0.40, origen=OrigenRestriccion.AJUSTE_USUARIO)
    with pytest.raises(RestriccionesInfactiblesError, match=r"BNS: .*piso 10\.00%"):
        restricciones_de_iteracion(_sesion(BNS=propio), {"BNS": 0.05})
