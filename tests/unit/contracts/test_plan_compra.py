"""Contratos operativos de S11: lo que el plan, la asesoría y el acta NO pueden decir."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from investmentsys.config import cargar_config
from investmentsys.contracts import (
    ActaOperativa,
    EscenarioFiscal,
    OverrideFiscal,
    PlanCompraNeta,
)
from investmentsys.fintual import asesorar, plan_compra_neta, plan_tras_override

FINTUAL = cargar_config().fintual
T0 = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
VENTA = "VOOG:vender_hasta_banda"


@pytest.fixture(scope="module")
def plan() -> PlanCompraNeta:
    return plan_compra_neta(
        {"VOOG": 0.70, "BNS": 0.05, "IBIT": 0.02, "VB": 0.23},
        {"VOOG": 7737.41, "BNS": 868.80, "IBIT": 658.42, "VB": 475.31},
        FINTUAL,
        aporte_usd=500.0,
        universe_version="a" * 64,
        validado=True,
        origen_objetivo="cartera de prueba",
    )


def _override(plan: PlanCompraNeta, **cambios: Any) -> dict[str, Any]:
    escenario = asesorar(plan, FINTUAL).escenario(VENTA)
    return {
        "escenario": escenario,
        "advertencia_cruzada": escenario.advertencia,
        "plan_resultante": plan_tras_override(plan, escenario, FINTUAL),
        "presentado_en": T0,
        "forzado_en": T0 + timedelta(minutes=2),
        "invocacion_presentacion": "inv-1",
        "invocacion_override": "inv-2",
        **cambios,
    }


def test_el_plan_no_tiene_donde_escribir_una_venta(plan: PlanCompraNeta) -> None:
    with pytest.raises(ValidationError, match="ventas_usd"):
        PlanCompraNeta.model_validate({**plan.model_dump(), "ventas_usd": 100.0})


def test_las_compras_deben_agotar_exactamente_el_flujo(plan: PlanCompraNeta) -> None:
    with pytest.raises(ValidationError, match="el flujo es"):
        PlanCompraNeta.model_validate({**plan.model_dump(), "aporte_usd": 600.0})


def test_no_se_compra_lo_que_no_esta_bajo_su_objetivo(plan: PlanCompraNeta) -> None:
    crudo = plan.model_dump()
    crudo["compras"][0]["monto_usd"] = 10.0  # VOOG, sobreponderado
    with pytest.raises(ValidationError, match="sin estar bajo su objetivo"):
        PlanCompraNeta.model_validate(crudo)


@pytest.mark.parametrize(
    ("cambio", "mensaje"),
    [
        ({"etiqueta": "Costo fiscal estimado: $1 CLP"}, "etiqueta"),
        ({"advertencia": None}, "toda venta lleva su advertencia"),
        ({"por_defecto": True}, "por defecto"),
        ({"cosecha_de_perdidas": True}, "cosecha_de_perdidas"),
    ],
)
def test_un_escenario_incoherente_no_valida(
    plan: PlanCompraNeta, cambio: dict[str, Any], mensaje: str
) -> None:
    escenario = asesorar(plan, FINTUAL).escenario(VENTA)
    with pytest.raises(ValidationError, match=mensaje):
        EscenarioFiscal.model_validate({**escenario.model_dump(), **cambio})


def test_el_override_guarda_literal_la_advertencia_y_exige_dos_turnos(
    plan: PlanCompraNeta,
) -> None:
    OverrideFiscal.model_validate(_override(plan))
    with pytest.raises(ValidationError, match="literal"):
        OverrideFiscal.model_validate(_override(plan, advertencia_cruzada="ok, entendido"))
    with pytest.raises(ValidationError, match="mismo turno"):
        OverrideFiscal.model_validate(_override(plan, invocacion_override="inv-1"))
    with pytest.raises(ValidationError, match="anterior"):
        OverrideFiscal.model_validate(_override(plan, forzado_en=T0 - timedelta(seconds=1)))


def test_el_acta_operativa_no_admite_overrides_ajenos_ni_decir_que_ejecuto(
    plan: PlanCompraNeta,
) -> None:
    asesoria = asesorar(plan, FINTUAL)
    acta = ActaOperativa(id="x", creado_en=T0, plan=plan, asesoria=asesoria)
    con = acta.con_override(OverrideFiscal.model_validate(_override(plan)))
    assert len(con.overrides) == 1 and acta.overrides == ()
    with pytest.raises(ValidationError, match="ejecutado_por_el_sistema"):
        ActaOperativa.model_validate({**acta.model_dump(), "ejecutado_por_el_sistema": True})
    solo_defecto = asesoria.model_copy(update={"escenarios": asesoria.escenarios[:1]})
    with pytest.raises(ValidationError, match="no son de esta acta"):
        ActaOperativa.model_validate({**con.model_dump(), "asesoria": solo_defecto.model_dump()})
