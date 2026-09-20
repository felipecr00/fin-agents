"""Invariante de custodia del gate del comité (S9; ADR-014 y su enmienda).

El gate descansa en UNA propiedad de ADK que no controlamos: ``ToolContext.invocation_id`` es
el mismo en todas las llamadas de un turno del usuario y distinto entre turnos, y los eventos de
la sesión conservan el orden de los turnos. Si una versión de ADK cambia esa semántica, el gate
dejaría de distinguir "el usuario vio la orden y confirmó" de "el LLM encadenó las dos fases".
Estos tests corren sobre el ``Runner`` REAL para que ese cambio rompa en rojo, no en silencio.

Toda falta a la secuencia es una violación CONTROLADA: la herramienta no lanza ni corre nada;
responde ``status="rechazado"``, ``tipo="ViolacionGateError"``, y no queda acta.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from google.adk.models.llm_request import LlmRequest
from google.adk.tools.tool_context import ToolContext

import investmentsys.orchestrator.comite as modulo_comite
from investmentsys.agents.director import crear_director
from investmentsys.config import Config, cargar_config
from investmentsys.data_manager import GestorDatos
from investmentsys.orchestrator import CLAVE_RUN_STATE, CLAVE_SOLICITUD, ViolacionGateError
from tests.almacen import sembrar_gestor
from tests.integration.conftest import Corrida, Llamada, LlmPorAgente, conversar, gestor_op
from tests.integration.test_market_analyst import BORRADOR_GOLDEN

VIOLACION = ViolacionGateError.__name__
COMITE_COMPLETO = {
    "analista": [BORRADOR_GOLDEN],
    "constructor": [Llamada("construir_candidatos"), "Pedí Black-Litterman."],
    "reporter": ["El comité aprobó la cartera."],
}


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config()


@pytest.fixture
def gestor(tmp_path: Path, config: Config) -> GestorDatos:
    return sembrar_gestor(tmp_path / "almacen", config)


def _token(peticion: LlmRequest) -> str:
    """El token que el LLM vio en la última respuesta de ``solicitar``."""
    return next(
        str((p.function_response.response or {})["token"])
        for c in reversed(peticion.contents)
        for p in c.parts or []
        if p.function_response and "token" in (p.function_response.response or {})
    )


def _ejecutar_con_el_token(peticion: LlmRequest) -> Llamada:
    return Llamada("convocar_comite", fase="ejecutar", token=_token(peticion))


def _correr(
    config: Config,
    gestor: GestorDatos,
    runs: Path,
    director: list[Any],
    mensajes: list[str],
    **otros: list[Any],
) -> list[Corrida]:
    llm = LlmPorAgente(director=director, **otros)
    turnos = conversar(crear_director(config, gestor.provider(), gestor, llm, runs), mensajes)
    assert llm.pendientes() == {}, "el guion no se consumió entero"
    return turnos


def _rechazos(turno: Corrida) -> list[dict[str, Any]]:
    return [r for r in turno.respuestas("convocar_comite") if r["status"] == "rechazado"]


def _sin_acta(turno: Corrida, runs: Path) -> bool:
    return turno.estado.get(CLAVE_RUN_STATE) is None and not runs.exists()


# ------------------------------------------------ la semántica de ADK de la que depende
def test_adk_un_invocation_id_por_turno_del_usuario_y_eventos_en_orden(
    config: Config, gestor: GestorDatos, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vistos: list[tuple[str, list[str]]] = []
    original = modulo_comite.ComiteTools._solicitar

    def espia(self: modulo_comite.ComiteTools, ctx: ToolContext, material: str) -> dict[str, Any]:
        ids = list(dict.fromkeys(e.invocation_id for e in ctx.session.events))
        vistos.append((ctx.invocation_id, ids))
        return original(self, ctx, material)

    monkeypatch.setattr(modulo_comite.ComiteTools, "_solicitar", espia)
    solicitar = Llamada("convocar_comite", fase="solicitar")
    _correr(
        config,
        gestor,
        tmp_path / "runs",
        [solicitar, solicitar, "Orden presentada.", "Charla.", solicitar, "Orden presentada."],
        ["convoca al comité", "una pregunta aparte", "convoca de nuevo"],
    )
    (id_a, _), (id_b, _), (id_c, orden_c) = vistos
    assert id_a == id_b, "dos llamadas del MISMO turno comparten invocation_id"
    assert id_c != id_a, "otro mensaje del usuario es otra invocación"
    # Los eventos conservan los tres turnos en orden, el del medio (sin herramientas) incluido.
    assert len(orden_c) == 3 and orden_c[0] == id_a and orden_c[-1] == id_c


def test_una_persona_consultada_en_el_turno_no_abre_otra_invocacion(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    """S10 (ADR-019): un sub-agente ``single_turn`` corre DENTRO del turno del usuario.

    Si abriera otra invocación, consultar al Estadístico entre ``solicitar`` y ``ejecutar``
    haría pasar por "turno posterior" lo que el usuario nunca confirmó.
    """
    guion = [
        Llamada("convocar_comite", fase="solicitar"),
        Llamada("estadistico", pregunta="¿correlación?"),
        _ejecutar_con_el_token,
        "No puedo ejecutar sin tu confirmación.",
    ]
    persona = [Llamada("estimar_mercado"), "Exploratorio: correlación alta."]
    (turno,) = _correr(
        config, gestor, tmp_path / "runs", guion, ["convoca y ejecuta"], estadistico=persona
    )
    assert len({e.invocation_id for e in turno.eventos}) == 1
    assert turno.textos("estadistico"), "la persona sí corrió, en su rama"
    (rechazo,) = _rechazos(turno)
    assert rechazo["tipo"] == VIOLACION
    assert _sin_acta(turno, tmp_path / "runs")


# ------------------------------------------------------------- violaciones del gate
def test_ejecutar_sin_haber_solicitado_es_una_violacion_controlada(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    inventada = Llamada("convocar_comite", fase="ejecutar", token="un-token-inventado")
    (turno,) = _correr(config, gestor, tmp_path / "runs", [inventada, "No puedo."], ["ejecuta ya"])
    (rechazo,) = _rechazos(turno)
    assert rechazo["tipo"] == VIOLACION and "solicitar" in rechazo["motivo"]
    assert _sin_acta(turno, tmp_path / "runs")


def test_solicitar_y_ejecutar_en_el_mismo_turno_es_una_violacion_y_el_token_sobrevive(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    """El LLM encadena las dos fases solo: el usuario no pudo ver la orden."""
    guion = [
        Llamada("convocar_comite", fase="solicitar"),
        _ejecutar_con_el_token,
        "Revisa la orden.",
    ]
    (turno,) = _correr(config, gestor, tmp_path / "runs", guion, ["convoca y ejecuta de una vez"])
    (rechazo,) = _rechazos(turno)
    assert rechazo["tipo"] == VIOLACION and "mismo turno" in rechazo["motivo"]
    assert turno.estado[CLAVE_SOLICITUD] is not None, "el usuario aún puede confirmar"
    assert _sin_acta(turno, tmp_path / "runs")


def test_el_token_solo_vale_en_el_turno_inmediatamente_posterior_a_la_orden(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    guion = [
        Llamada("convocar_comite", fase="solicitar"),
        "Revisa la orden.",
        "El prior es el equilibrio de mercado.",  # un turno de por medio, sin herramientas
        _ejecutar_con_el_token,
        "Tengo que presentarte la orden de nuevo.",
    ]
    *_, ultimo = _correr(
        config, gestor, tmp_path / "runs", guion, ["convoca", "¿qué es el prior?", "sí, confirmo"]
    )
    (rechazo,) = _rechazos(ultimo)
    assert rechazo["tipo"] == VIOLACION and "hace más de un turno" in rechazo["motivo"]
    assert ultimo.estado[CLAVE_SOLICITUD] is None, "el token murió: hay que volver a solicitar"
    assert _sin_acta(ultimo, tmp_path / "runs")


def test_un_cambio_de_universo_invalida_el_token(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    """Retirar y confirmar en el mismo mensaje: lo aprobado ya no es lo que se correría."""
    token: list[str] = []

    def recordar(peticion: LlmRequest) -> str:
        token.append(_token(peticion))
        return "Revisa la orden."

    guion = [
        Llamada("convocar_comite", fase="solicitar"),
        recordar,
        gestor_op("retirar", ticker="BNS"),
        lambda _: Llamada("convocar_comite", fase="ejecutar", token=token[0]),
        "El universo cambió: hay que volver a solicitar.",
    ]
    _, ultimo = _correr(
        config, gestor, tmp_path / "runs", guion, ["convoca", "saca BNS y sí, confirmo"]
    )
    (retiro,) = ultimo.respuestas("retirar")
    assert "solicitud al comité (resumen y token)" in [
        o["resultado"] for o in retiro["resultados_obsoletos"]
    ]
    (rechazo,) = _rechazos(ultimo)
    assert rechazo["tipo"] == VIOLACION
    assert _sin_acta(ultimo, tmp_path / "runs")


def test_un_token_usado_no_vuelve_a_valer(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    usado: list[str] = []

    def ejecutar(peticion: LlmRequest) -> Llamada:
        usado.append(_token(peticion))
        return Llamada("convocar_comite", fase="ejecutar", token=usado[0])

    guion = [
        Llamada("convocar_comite", fase="solicitar"),
        "Revisa la orden.",
        ejecutar,
        "El comité aprobó.",
        lambda _: Llamada("convocar_comite", fase="ejecutar", token=usado[0]),
        "Ese token ya se usó.",
    ]
    _, corrida, repetida = _correr(
        config,
        gestor,
        tmp_path / "runs",
        guion,
        ["convoca", "sí, confirmo", "córrelo otra vez"],
        **COMITE_COMPLETO,
    )
    # La secuencia legítima SÍ corre: el gate custodia, no bloquea.
    (acta,) = corrida.respuestas("convocar_comite")
    assert acta["status"] == "success" and acta["validado"] is True
    assert len(list((tmp_path / "runs").iterdir())) == 1
    (rechazo,) = _rechazos(repetida)
    assert rechazo["tipo"] == VIOLACION
    assert len(list((tmp_path / "runs").iterdir())) == 1, "no hubo una segunda corrida"
