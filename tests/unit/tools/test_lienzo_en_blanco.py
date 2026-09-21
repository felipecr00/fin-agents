"""Lienzo en blanco en la capa de tools (ADR-023): mesa limpia, universo de sesión y custodias.

Enmienda 4 del brief: con el universo vacío, TODA herramienta de análisis y el gate del comité
responden un error de dominio claro —"no hay universo configurado en la sesión"—, nunca una
excepción cruda.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from google.adk.agents import LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.sessions import InMemorySessionService
from google.adk.tools import ToolContext

from investmentsys.config import Config
from investmentsys.data_manager import GestorDatos
from investmentsys.orchestrator import ComiteTools
from investmentsys.tools import CLAVE_UNIVERSO, NucleoTools
from investmentsys.tools.estado import CLAVE_ORIGEN_UNIVERSO, ORIGEN_GUARDADO, ORIGEN_SESION
from investmentsys.tools.ficha import CLAVE_ANEXO
from investmentsys.tools.fintual import GestorFintualTools
from investmentsys.tools.mesa import TITULO_MESA_LIMPIA, MesaTools, componer_sala
from tests.almacen import fuente_de_eval, sembrar_gestor
from tests.conftest import ACTIVOS
from tests.integration.conftest import LlmPorAgente

SIN_UNIVERSO = "no hay universo configurado en la sesión"
Turnos = Callable[[str], ToolContext]


@pytest.fixture
def gestor(tmp_path: Path, config: Config) -> GestorDatos:
    return sembrar_gestor(tmp_path / "almacen", config, fuente_de_eval())  # conoce AAPL y QQQ


@pytest.fixture
def gf(gestor: GestorDatos, config: Config) -> GestorFintualTools:
    return GestorFintualTools(gestor, config)


@pytest.fixture
def limpia() -> Turnos:
    """Como ``turnos``, pero la sesión arranca como la de ``apps/equipo``: SIN universo."""
    servicio = InMemorySessionService()
    inicial = {CLAVE_ORIGEN_UNIVERSO: ORIGEN_SESION}
    sesion = asyncio.run(servicio.create_session(app_name="t", user_id="t", state=inicial))

    def turno(invocation_id: str) -> ToolContext:
        if invocation_id not in {e.invocation_id for e in sesion.events}:
            sesion.events.append(Event(invocation_id=invocation_id, author="user"))
        invocacion = InvocationContext(
            session_service=servicio,
            invocation_id=invocation_id,
            agent=LlmAgent(name="relleno"),
            session=sesion,
        )
        return ToolContext(invocacion)

    return turno


def _op(gf: GestorFintualTools, ctx: ToolContext, operacion: str, **args: Any) -> dict[str, Any]:
    return gf.gestionar_datos_y_fricciones(operacion, ctx, **args)  # type: ignore[arg-type]


def _mesa(gestor: GestorDatos, config: Config, ctx: ToolContext) -> dict[str, Any]:
    sala = componer_sala(["consultar_mesa_trabajo"], [])
    return MesaTools(gestor, config, sala).consultar_mesa_trabajo(ctx)


# ------------------------------------------------------------------------- la mesa limpia
def test_la_mesa_arranca_vacia_y_solo_menciona_el_guardado(
    gestor: GestorDatos, config: Config, limpia: Turnos
) -> None:
    ctx = limpia("inv-1")
    salida = _mesa(gestor, config, ctx)
    assert salida["status"] == "success" and salida["mesa_limpia"] is True
    assert salida["universe_version"] is None and salida["activos"] == []
    assert salida["items"] == [], "ningún ítem prefabricado"
    assert salida["universo_guardado_no_cargado"]["activos"] == list(ACTIVOS)
    bloque = salida[CLAVE_ANEXO]
    assert bloque.startswith(TITULO_MESA_LIMPIA)
    assert f"NO cargado: {', '.join(ACTIVOS)}" in bloque and "solo si lo pides" in bloque
    assert ctx.state.get(CLAVE_UNIVERSO) is None, "mencionar no es cargar"


# --------------------------------------------------- enmienda 4: sin universo, error de dominio
def test_sin_universo_toda_herramienta_de_analisis_responde_un_error_de_dominio(
    gf: GestorFintualTools, config: Config, gestor: GestorDatos, limpia: Turnos, tmp_path: Path
) -> None:
    ctx = limpia("inv-1")
    nucleo = NucleoTools(config, gestor.provider())
    comite = ComiteTools(config, gestor.provider(), LlmPorAgente(), tmp_path / "runs")
    salidas = {
        "estimar_mercado": nucleo.estimar_mercado(ctx),
        "construir_candidatos": nucleo.construir_candidatos(ctx),
        "validar_candidato": nucleo.validar_candidato(ctx),
        "diagnosticar_cartera": nucleo.diagnosticar_cartera(ctx),
        "ajustar_restricciones": nucleo.ajustar_restricciones(ctx, peso_max=0.5),
        "comite:solicitar": asyncio.run(comite.convocar_comite("solicitar", ctx)),
        "comite:ejecutar": asyncio.run(comite.convocar_comite("ejecutar", ctx, token="x")),
        **{
            op: _op(gf, ctx, op)
            for op in ("diagnosticar", "dividendos", "cierres", "montos", "aceptar_prior_neutral")
        },
        "plan_compra": _op(gf, ctx, "plan_compra", aporte_usd=500.0),
        "retirar": _op(gf, ctx, "retirar", ticker="VOOG"),
        "refrescar_cap": _op(gf, ctx, "refrescar_cap", ticker="VOOG"),
    }
    for nombre, salida in salidas.items():
        assert salida["status"] in ("error", "rechazado"), nombre
        texto = str(salida.get("mensaje") or salida.get("motivo"))
        if nombre != "comite:ejecutar":  # sin solicitud previa, el gate rechaza antes (ADR-014)
            assert SIN_UNIVERSO in texto, f"{nombre}: {texto}"
    assert ctx.state.get(CLAVE_UNIVERSO) is None
    assert not (tmp_path / "runs").exists()


# ------------------------------------------------------------ "usa el guardado" / lista nueva
def test_cargar_guardado_trae_el_universo_con_diagnosticos_y_desde_ahi_se_persiste(
    gf: GestorFintualTools, gestor: GestorDatos, limpia: Turnos
) -> None:
    ctx = limpia("inv-1")
    salida = _op(gf, ctx, "cargar_guardado")
    assert salida["status"] == "success"
    assert [a["ticker"] for a in salida["activos"]] == list(ACTIVOS)
    assert salida["universo"]["activo_mas_corto"] == "IBIT"
    assert ctx.state[CLAVE_ORIGEN_UNIVERSO] == ORIGEN_GUARDADO
    assert ctx.state[CLAVE_UNIVERSO]["version"] == gestor.universo().version
    # Como en S8-S11: un alta sobre el guardado SÍ se persiste.
    assert _op(gf, ctx, "incorporar", ticker="AAPL")["status"] == "success"
    assert gestor.universo().activos == (*ACTIVOS, "AAPL")


def test_lista_en_el_primer_turno_crea_el_universo_de_la_sesion_con_la_cascada_de_siempre(
    gf: GestorFintualTools, gestor: GestorDatos, config: Config, limpia: Turnos
) -> None:
    guardado = gestor.universo().version
    ctx = limpia("inv-1")
    vistos = _op(gf, ctx, "resolver", tickers=["AAPL", "QQQ", "NOEXISTE"])
    assert [a["ticker"] for a in vistos["activos"]] == ["AAPL", "QQQ"]
    assert vistos["sin_cap_en_la_fuente"] == ["QQQ"] and set(vistos["no_resueltos"]) == {"NOEXISTE"}
    assert vistos["si_entran_todos"]["ventana_comun"]["meses"] == 80
    assert ctx.state.get(CLAVE_UNIVERSO) is None, "resolver no modifica nada"

    alta = _op(gf, ctx, "incorporar", tickers=["AAPL", "QQQ", "NOEXISTE"])
    assert alta["status"] == "success" and alta["incorporados"] == ["AAPL"]
    assert alta["universo_completo"] is False
    (pendiente,) = alta["pendientes_de_prior"]
    assert (
        pendiente["activo"]["ticker"] == "QQQ" and "(a) [recomendada]" in pendiente["que_preguntar"]
    )
    assert set(alta["rechazados"]) == {"NOEXISTE"}
    assert [d["ticker"] for d in ctx.state[CLAVE_UNIVERSO]["diagnosticos"]] == ["AAPL"]
    assert alta["universe_version"] == ctx.state[CLAVE_UNIVERSO]["version"] != guardado
    assert gestor.universo().version == guardado, "el guardado no se toca"

    # La respuesta del usuario para el ETF entra por la vía de siempre, en otro turno.
    etf = _op(
        gf,
        limpia("inv-2"),
        "incorporar",
        ticker="QQQ",
        prior_cap=22.0,
        prior_metodologia="capitalización del Nasdaq-100",
    )
    assert [a["ticker"] for a in etf["activos"]] == ["AAPL", "QQQ"]
    assert etf["estado_prior"] == "capitalizacion"

    # La mesa proyecta ESE universo: su primer ítem es el universo con la advertencia de
    # ventana de los tickers recién ingresados (no la de IBIT, que no está en la sesión).
    mesa = _mesa(gestor, config, limpia("inv-3"))
    primero = mesa["mesa"]["items"][0]
    assert primero["categoria"] == "Universo" and "AAPL" in primero["contenido"]
    assert "IBIT" not in primero["contenido"] and "80 meses; la limita" in primero["contenido"]
    assert gestor.universo().version == guardado


def test_en_lote_no_caben_caps_y_la_lista_no_se_mezcla_con_un_ticker(
    gf: GestorFintualTools, limpia: Turnos
) -> None:
    ctx = limpia("inv-1")
    con_cap = _op(gf, ctx, "incorporar", tickers=["QQQ"], prior_cap=22.0, prior_metodologia="x")
    assert con_cap["status"] == "rechazado" and "prior_cap" in con_cap["motivo"]
    mezcla = _op(gf, ctx, "resolver", ticker="AAPL", tickers=["QQQ"])
    assert mezcla["status"] == "rechazado" and "ticker" in mezcla["motivo"]
    assert ctx.state.get(CLAVE_UNIVERSO) is None


def test_el_prior_neutral_no_se_relaja_por_venir_en_lote(
    gf: GestorFintualTools, gestor: GestorDatos, limpia: Turnos
) -> None:
    """Todo-o-nada y en un turno POSTERIOR, también sobre un universo de sesión."""
    guardado = gestor.ruta_universo.read_bytes()
    primero = limpia("inv-1")
    _op(gf, primero, "incorporar", tickers=["AAPL", "QQQ"])
    assert _op(gf, primero, "incorporar", ticker="QQQ")["estado_prior"] == "pendiente"
    for _ in range(2):  # insistir en el mismo turno no degrada
        salida = _op(gf, primero, "aceptar_prior_neutral")
        assert salida["status"] == "rechazado" and salida["tipo"] == "ConfirmacionPendiente"
        assert "AAPL, QQQ" in salida["motivo"] and "VOOG" not in salida["motivo"]
    salida = _op(gf, limpia("inv-2"), "aceptar_prior_neutral")
    assert salida["status"] == "success" and salida["estado_prior"] == "neutral"
    assert gestor.ruta_universo.read_bytes() == guardado


def test_un_universo_de_un_solo_activo_no_revienta_a_nadie(
    gf: GestorFintualTools, config: Config, gestor: GestorDatos, limpia: Turnos, tmp_path: Path
) -> None:
    """El lienzo en blanco hace alcanzable lo que antes no lo era: empezar por UN ticker. Los
    límites por defecto (techo 70 %) son infactibles ahí: se dice, como error de dominio."""
    ctx = limpia("inv-1")
    assert _op(gf, ctx, "incorporar", ticker="AAPL")["status"] == "success"
    mesa = _mesa(gestor, config, ctx)
    restricciones = mesa["mesa"]["items"][-1]
    assert (
        restricciones["categoria"] == "Restricción"
        and "no son factibles" in restricciones["contenido"]
    )
    nucleo = NucleoTools(config, gestor.provider())
    comite = ComiteTools(config, gestor.provider(), LlmPorAgente(), tmp_path / "runs")
    for salida in (
        nucleo.construir_candidatos(ctx),
        asyncio.run(comite.convocar_comite("solicitar", ctx)),
    ):
        assert salida["status"] in ("error", "rechazado")
        assert "infactible" in str(salida.get("mensaje") or salida.get("motivo"))
