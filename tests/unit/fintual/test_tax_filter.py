"""Filtro tributario CONSULTIVO (S11, enmienda §2): etiqueta escenarios, no prohíbe nada."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from investmentsys.config import FintualConfig, cargar_config
from investmentsys.contracts import (
    DISCLAIMER_OPERATIVO,
    AsesoriaFiscal,
    BaseCosto,
    PlanCompraNeta,
    TipoEscenario,
    etiqueta_costo,
)
from investmentsys.fintual import ID_SIN_VENTAS, asesorar, plan_compra_neta, plan_tras_override

SELLO = "a" * 64
OBJETIVO = {"VOOG": 0.70, "BNS": 0.05, "IBIT": 0.02, "VB": 0.23}
TENENCIAS = {"VOOG": 7737.41, "BNS": 868.80, "IBIT": 658.42, "VB": 475.31}


def _fintual(tasa: float = 0.10, usd_clp: float = 1000.0, **costo_base: float) -> FintualConfig:
    base = cargar_config().fintual
    tributario = base.tributario.model_copy(
        update={"tasa_marginal": tasa, "usd_clp": usd_clp, "costo_base_usd": costo_base}
    )
    return base.model_copy(update={"tributario": tributario})


def _plan(fintual: FintualConfig, objetivo: dict[str, float] = OBJETIVO) -> PlanCompraNeta:
    return plan_compra_neta(
        objetivo,
        TENENCIAS,
        fintual,
        aporte_usd=500.0,
        universe_version=SELLO,
        validado=True,
        origen_objetivo="cartera de prueba",
    )


def _asesoria(fintual: FintualConfig, objetivo: dict[str, float] = OBJETIVO) -> AsesoriaFiscal:
    return asesorar(_plan(fintual, objetivo), fintual)


def test_el_escenario_por_defecto_es_no_vender_y_cuesta_cero() -> None:
    asesoria = _asesoria(_fintual())
    (defecto,) = [e for e in asesoria.escenarios if e.por_defecto]
    assert defecto.id == ID_SIN_VENTAS and defecto.tipo is TipoEscenario.SIN_VENTAS
    assert defecto.etiqueta == "Costo fiscal estimado: $0 CLP" and defecto.advertencia is None
    assert "VOOG" in defecto.efecto  # dice lo que queda sin corregir


def test_sin_costo_de_adquisicion_el_costo_es_una_cota_y_lo_dice() -> None:
    e = _asesoria(_fintual()).escenario("VOOG:vender_hasta_banda")
    # VOOG 7737.41 sobre 10239.94; borde de banda 75 % → vender 57.45; todo ganancia (cota).
    assert e.venta_usd == pytest.approx(57.45, abs=0.01)
    assert e.base_costo is BaseCosto.COTA_SIN_COSTO and e.resultado_usd == e.venta_usd
    assert e.costo_fiscal_clp == pytest.approx(e.venta_usd * 0.10 * 1000.0)
    assert e.etiqueta == etiqueta_costo(e.costo_fiscal_clp) == "Costo fiscal estimado: $5.745 CLP"
    assert e.advertencia is not None and "COTA" in e.advertencia and e.etiqueta in e.advertencia


def test_con_costo_declarado_solo_tributa_la_ganancia() -> None:
    asesoria = _asesoria(_fintual(VOOG=7737.41 / 2))  # la mitad del valor actual es ganancia
    banda = asesoria.escenario("VOOG:vender_hasta_banda")
    objetivo = asesoria.escenario("VOOG:vender_hasta_objetivo")
    assert banda.base_costo is BaseCosto.DECLARADA
    assert banda.resultado_usd == pytest.approx(banda.venta_usd / 2, abs=0.01)
    assert objetivo.venta_usd == pytest.approx(7737.41 - 0.70 * 10239.94, abs=0.01)
    assert objetivo.costo_fiscal_clp > banda.costo_fiscal_clp > 0.0
    assert asesoria.supuestos.tasa_marginal == 0.10 and asesoria.supuestos.usd_clp == 1000.0


def test_una_venta_con_perdida_se_reconoce_como_tax_loss_harvesting() -> None:
    """Enmienda §2: la heurística 'evitar ventas' no aplica a realizar pérdidas."""
    asesoria = _asesoria(_fintual(VOOG=9000.0))  # VOOG vale menos de lo que costó
    e = asesoria.escenario("VOOG:vender_hasta_objetivo")
    assert e.cosecha_de_perdidas and e.resultado_usd < 0.0
    assert e.costo_fiscal_clp == 0.0 and e.etiqueta == "Costo fiscal estimado: $0 CLP"
    assert e.perdida_realizable_clp == pytest.approx(-e.resultado_usd * 1000.0)
    assert e.advertencia is not None
    assert "tax-loss harvesting" in e.advertencia and "estrategia legítima" in e.advertencia


def test_las_perdidas_latentes_se_listan_aunque_nadie_proponga_vender() -> None:
    asesoria = _asesoria(_fintual(IBIT=900.0, BNS=500.0))
    (latente,) = asesoria.perdidas_latentes  # BNS tiene ganancia: no aparece
    assert latente.activo == "IBIT"
    assert latente.perdida_latente_usd == pytest.approx(900.0 - 658.42, abs=0.01)
    assert not any(e.activo == "IBIT" for e in asesoria.escenarios)  # en banda: nadie lo vende


def test_con_todo_en_banda_solo_queda_el_escenario_por_defecto() -> None:
    en_banda = {"VOOG": 0.78, "BNS": 0.08, "IBIT": 0.06, "VB": 0.08}
    asesoria = _asesoria(_fintual(), en_banda)
    assert [e.id for e in asesoria.escenarios] == [ID_SIN_VENTAS]
    assert "dentro de sus bandas" in asesoria.escenarios[0].efecto


def test_el_disclaimer_viaja_inyectado_y_no_se_puede_reescribir() -> None:
    asesoria = _asesoria(_fintual())
    assert asesoria.disclaimer == DISCLAIMER_OPERATIVO
    assert "no asesoría tributaria o financiera" in asesoria.disclaimer
    assert "contador" in asesoria.disclaimer
    for texto in ("", "Esto sí es asesoría."):
        with pytest.raises(ValidationError, match="disclaimer"):
            AsesoriaFiscal.model_validate({**asesoria.model_dump(), "disclaimer": texto})


def test_forzar_un_escenario_reasigna_el_producto_de_la_venta_con_la_misma_regla() -> None:
    fintual = _fintual()
    plan = _plan(fintual)
    escenario = asesorar(plan, fintual).escenario("VOOG:vender_hasta_objetivo")
    forzado = plan_tras_override(plan, escenario, fintual)
    assert forzado.reinversion_usd == escenario.venta_usd and forzado.ventas_usd == 0.0
    assert forzado.flujo_usd == pytest.approx(500.0 + escenario.venta_usd)
    voog = next(c for c in forzado.compras if c.activo == "VOOG")
    assert voog.monto_usd == 0.0 and voog.peso_despues == pytest.approx(0.70, abs=1e-4)
    with pytest.raises(ValueError, match="sin ventas"):
        plan_tras_override(plan, asesorar(plan, fintual).escenario(ID_SIN_VENTAS), fintual)
