"""Hitos del comité EN VIVO (S11, ADR-021): semántica de ADK de la que dependemos.

La transmisión usa una API PRIVADA de ADK (``InvocationContext._enqueue_event``). Estos tests
corren sobre el ``Runner`` REAL para que un cambio de versión rompa en rojo y no en silencio:

1. el hito llega al cliente ANTES de que ``convocar_comite`` retorne (si llegara después, sería
   una cronología con pasos extra, no una transmisión);
2. queda en la sesión como evento del autor ``comite``;
3. el MODELO no lo ve, ni en ese turno ni en los siguientes (lo que ve, lo imita: S9);
4. si la API falla o se apaga por config, el comité corre igual y la cronología se entrega al
   cierre: el modo degradado es la garantía mínima del spec.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event

from investmentsys.agents.anexos import MARCA_ANEXO
from investmentsys.agents.director import crear_director
from investmentsys.config import Config, cargar_config
from investmentsys.data_manager import GestorDatos
from investmentsys.orchestrator.bitacora import CLAVE_HITOS, TITULO_CRONOLOGIA
from investmentsys.tools.hitos_en_vivo import AUTOR_COMITE, MARCA_HITO, transmitir
from tests.almacen import sembrar_gestor
from tests.integration.conftest import Corrida, Llamada, LlmPorAgente, conversar
from tests.test_gate_security import COMITE_COMPLETO, _ejecutar_con_el_token
from tests.unit.tools.conftest import Turnos, turnos  # noqa: F401  (fixture)

MENSAJES = ["convoca al comité", "sí, confirmo", "gracias"]
N_HITOS = 6  # apertura, views, estimación, propuesta, aprobada, acta


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config()


@pytest.fixture
def gestor(tmp_path: Path, config: Config) -> GestorDatos:
    return sembrar_gestor(tmp_path / "almacen", config)


def _sesion(config: Config, gestor: GestorDatos, runs: Path) -> tuple[list[Corrida], LlmPorAgente]:
    llm = LlmPorAgente(
        director=[
            Llamada("convocar_comite", fase="solicitar"),
            "Revisa la orden.",
            _ejecutar_con_el_token,
            "El comité aprobó la cartera.",
            "De nada.",
        ],
        **COMITE_COMPLETO,
    )
    director = crear_director(config, gestor.provider(), gestor, llm, runs)
    corridas = conversar(director, MENSAJES)
    assert llm.pendientes() == {}
    return corridas, llm


def _posiciones(corrida: Corrida) -> tuple[int, list[int], int]:
    """Índices en el flujo del turno: la llamada al comité, sus hitos y la respuesta de la tool."""

    def con(parte: str) -> int:
        return next(
            i
            for i, e in enumerate(corrida.eventos)
            if e.content and any(getattr(p, parte) for p in e.content.parts or [])
        )

    hitos = [i for i, e in enumerate(corrida.eventos) if e.author == AUTOR_COMITE]
    return con("function_call"), hitos, con("function_response")


def test_los_hitos_llegan_mientras_la_tool_corre_y_quedan_en_la_sesion(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    (_, ejecucion, _), _ = _sesion(config, gestor, tmp_path / "runs")
    llamada, hitos, respuesta = _posiciones(ejecucion)
    assert len(hitos) == N_HITOS
    assert llamada < hitos[0] and hitos[-1] < respuesta, "en vivo = ENTRE la llamada y su retorno"

    textos = ejecucion.textos(AUTOR_COMITE)
    assert all(t.startswith(f"{MARCA_HITO}`+") for t in textos)
    assert "**Comité**: sesión abierta" in textos[0]
    assert "**Escéptico (Validador)** · ronda 1: APROBADA" in textos[4]
    assert all(not e.partial for e in ejecucion.eventos if e.author == AUTOR_COMITE)  # persisten
    assert len(ejecucion.estado[CLAVE_HITOS]) == N_HITOS


def test_el_modelo_nunca_ve_los_hitos_y_el_cierre_trae_la_cronologia(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    (_, ejecucion, despedida), llm = _sesion(config, gestor, tmp_path / "runs")
    assert len(llm.historiales("director")) == 5
    for historial in llm.historiales("director"):
        visto = " ".join(p.text or "" for c in historial for p in c.parts or [])
        assert MARCA_HITO not in visto and "sesión abierta" not in visto
        assert f"[{AUTOR_COMITE}] said" not in visto

    narracion, anexos = ejecucion.textos("director")[-1].split(MARCA_ANEXO)
    assert narracion.strip() == "El comité aprobó la cartera."
    assert TITULO_CRONOLOGIA in anexos and "1 ronda Constructor ⇄ Escéptico, 0 vetos" in anexos
    assert despedida.textos("director") == [
        "De nada."
    ]  # el turno siguiente sigue siendo del Director


@pytest.mark.parametrize("modo", ["apagado_por_config", "api_rota"])
def test_sin_transmision_el_comite_corre_igual_y_la_cronologia_se_entrega(
    config: Config, gestor: GestorDatos, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, modo: str
) -> None:
    if modo == "apagado_por_config":
        corridas_cfg = config.corridas.model_copy(update={"transmitir_hitos_en_vivo": False})
        config = config.model_copy(update={"corridas": corridas_cfg})
    else:
        original = InvocationContext._enqueue_event

        async def roto(self: InvocationContext, event: Event) -> None:
            if event.author == AUTOR_COMITE:
                raise RuntimeError("la cola cambió de forma")
            await original(self, event)

        monkeypatch.setattr(InvocationContext, "_enqueue_event", roto)

    (_, ejecucion, _), _ = _sesion(config, gestor, tmp_path / "runs")
    assert ejecucion.textos(AUTOR_COMITE) == []
    (respuesta,) = ejecucion.respuestas("convocar_comite")
    assert respuesta["status"] == "success" and respuesta["veredicto"] == "APROBADA"
    assert TITULO_CRONOLOGIA in ejecucion.textos("director")[-1]
    assert len(ejecucion.estado[CLAVE_HITOS]) == N_HITOS


def test_fuera_de_un_runner_no_hay_cola_y_transmitir_lo_dice(turnos: Turnos) -> None:  # noqa: F811
    assert asyncio.run(transmitir(turnos("inv-1"), "hito")) is False
