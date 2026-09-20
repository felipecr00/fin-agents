"""No-Trade Zones (S10, ADR-020): dentro de banda la orden es HOLD obligatorio.

Incluye el criterio 5 de la matriz de verificación de la arquitectura v2: si las desviaciones
están dentro de [-5 %, +5 %], la orden generada es explícitamente HOLD.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from investmentsys.config import Config, FintualConfig, cargar_config
from investmentsys.contracts import DecisionInercia, OrdenInercia, PlanInercia
from investmentsys.fintual import banda_de, plan_inercia

SELLO = "a" * 64
OBJETIVO = {"VOOG": 0.55, "VB": 0.25, "BNS": 0.20}


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config()


@pytest.fixture(scope="module")
def fintual(config: Config) -> FintualConfig:
    return config.fintual


def _plan(actual: dict[str, float], fintual: FintualConfig, valor: float = 10_000.0) -> PlanInercia:
    return plan_inercia(
        OBJETIVO,
        actual,
        valor,
        fintual,
        universe_version=SELLO,
        validado=False,
        origen_objetivo="cartera de prueba",
    )


def test_la_banda_por_defecto_es_cinco_puntos_y_vive_en_config(fintual: FintualConfig) -> None:
    assert fintual.banda_inercia == 0.05 and banda_de("VOOG", fintual) == 0.05


def test_todo_dentro_de_banda_es_hold_explicito(fintual: FintualConfig) -> None:
    plan = _plan({"VOOG": 0.59, "VB": 0.22, "BNS": 0.19}, fintual)
    assert plan.orden_global is OrdenInercia.HOLD
    assert [d.orden for d in plan.decisiones] == [OrdenInercia.HOLD] * 3


def test_el_ejemplo_de_la_arquitectura_55_por_ciento_admite_50_a_60(fintual: FintualConfig) -> None:
    """El borde ES banda: 60 % con objetivo 55 % sigue en HOLD; 60.1 %, ya no."""
    en_el_borde = _plan({"VOOG": 0.60, "VB": 0.20, "BNS": 0.20}, fintual)
    assert en_el_borde.orden_global is OrdenInercia.HOLD
    fuera = _plan({"VOOG": 0.601, "VB": 0.199, "BNS": 0.20}, fintual)
    por_activo = {d.activo: d for d in fuera.decisiones}
    assert por_activo["VOOG"].orden is OrdenInercia.FUERA_DE_BANDA
    assert por_activo["VOOG"].desviacion == pytest.approx(0.051)
    assert por_activo["BNS"].orden is OrdenInercia.HOLD
    assert fuera.orden_global is OrdenInercia.FUERA_DE_BANDA


def test_la_banda_es_absoluta_no_relativa_al_peso(fintual: FintualConfig) -> None:
    """BNS 20 % → 14 %: son 6 p.p. (fuera), aunque sea "solo" un activo chico."""
    plan = _plan({"VOOG": 0.58, "VB": 0.28, "BNS": 0.14}, fintual)
    assert {d.activo: d.orden.value for d in plan.decisiones}["BNS"] == "FUERA_DE_BANDA"


def test_banda_por_activo_sobrescribe_la_general(fintual: FintualConfig) -> None:
    estrecha = fintual.model_copy(update={"bandas_por_activo": {"VOOG": 0.02}})
    plan = _plan({"VOOG": 0.58, "VB": 0.23, "BNS": 0.19}, estrecha)
    por_activo = {d.activo: d for d in plan.decisiones}
    assert por_activo["VOOG"].banda == 0.02 and por_activo["VOOG"].orden.value == "FUERA_DE_BANDA"
    assert por_activo["VB"].banda == 0.05 and por_activo["VB"].orden is OrdenInercia.HOLD


def test_un_activo_que_esta_en_una_sola_cartera_pesa_cero_en_la_otra(
    fintual: FintualConfig,
) -> None:
    plan = _plan({"VOOG": 0.55, "VB": 0.25, "IBIT": 0.20}, fintual)
    por_activo = {d.activo: d for d in plan.decisiones}
    assert [d.activo for d in plan.decisiones] == ["VOOG", "VB", "BNS", "IBIT"]
    assert por_activo["BNS"].peso_actual == 0.0 and por_activo["IBIT"].peso_objetivo == 0.0
    assert por_activo["IBIT"].orden is OrdenInercia.FUERA_DE_BANDA


def test_montos_al_centavo_que_suman_el_valor_de_la_cartera(fintual: FintualConfig) -> None:
    plan = _plan({"VOOG": 0.7944, "VB": 0.1164, "BNS": 0.0892}, fintual, valor=9739.94)
    assert plan.valor_cartera_usd == 9739.94
    assert round(sum(d.monto_objetivo_usd for d in plan.decisiones), 2) == 9739.94
    assert round(sum(d.monto_actual_usd for d in plan.decisiones), 2) == 9739.94
    assert "no asesoría tributaria" in plan.disclaimer


def test_es_determinista(fintual: FintualConfig) -> None:
    actual = {"VOOG": 0.7944, "VB": 0.1164, "BNS": 0.0892}
    assert _plan(actual, fintual) == _plan(actual, fintual)


def test_carteras_que_no_suman_uno_se_rechazan(fintual: FintualConfig) -> None:
    with pytest.raises(ValueError, match="cartera actual"):
        _plan({"VOOG": 0.5}, fintual)


# ------------------------------------------------------------------ el contrato custodia
def _decision(**cambios: object) -> dict[str, object]:
    base: dict[str, object] = {
        "activo": "VOOG",
        "peso_objetivo": 0.55,
        "peso_actual": 0.58,
        "desviacion": 0.03,
        "banda": 0.05,
        "orden": "HOLD",
        "monto_objetivo_usd": 55.0,
        "monto_actual_usd": 58.0,
    }
    return {**base, **cambios}


def test_el_contrato_rechaza_una_orden_fuera_de_banda_dentro_de_la_banda() -> None:
    with pytest.raises(ValidationError, match="incoherente"):
        DecisionInercia.model_validate(_decision(orden="FUERA_DE_BANDA"))


def test_el_contrato_rechaza_un_hold_con_la_desviacion_fuera_de_banda() -> None:
    with pytest.raises(ValidationError, match="incoherente"):
        DecisionInercia.model_validate(_decision(peso_actual=0.65, desviacion=0.10))


def test_el_contrato_rechaza_una_desviacion_que_no_es_la_resta() -> None:
    with pytest.raises(ValidationError, match="desviacion"):
        DecisionInercia.model_validate(_decision(desviacion=0.01))


def test_el_plan_exige_sello_y_orden_global_coherente() -> None:
    decision = _decision(monto_objetivo_usd=100.0, monto_actual_usd=100.0)
    plan = {
        "universe_version": SELLO,
        "validado": False,
        "origen_objetivo": "x",
        "valor_cartera_usd": 100.0,
        "decisiones": [decision],
        "orden_global": "FUERA_DE_BANDA",
    }
    with pytest.raises(ValidationError, match="orden_global"):
        PlanInercia.model_validate(plan)
    with pytest.raises(ValidationError, match="universe_version"):
        PlanInercia.model_validate({**plan, "orden_global": "HOLD", "universe_version": None})
    assert PlanInercia.model_validate({**plan, "orden_global": "HOLD"}).orden_global.value == "HOLD"
