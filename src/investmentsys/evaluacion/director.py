"""Arnés del evalset del Director (ADR-015): preparar el almacén, correr los turnos, verificar.

Deliberadamente delgado: tres pasos y nada más. No es un framework de evaluación — no hay
plugins, ni métricas configurables, ni usuario simulado. El MISMO código corre en ``make check``
con un LLM guionado y en ``make eval`` contra el modelo real; quien llama decide el modelo y
construye el ``Mundo`` de cada caso (un almacén aislado: ningún caso ve los cambios de otro).

Los casos viven en ``tests/eval/casos_director.yaml``, que documenta su propio formato.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.run_config import RunConfig
from google.adk.events.event import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

from investmentsys.data_manager import GestorDatos
from investmentsys.evaluacion.criterios import ResultadoCriterio
from investmentsys.evaluacion.criterios_director import Criterios, TurnoObservado, evaluar
from investmentsys.evaluacion.informe import CasoEvaluado, CriterioEvaluado

APP = "eval_director"
USUARIO = "eval"
PREPARACIONES = ("incorporar", "retirar")
# Topes del arnés (no son parámetros financieros): un Director en bucle o una llamada colgada
# hacen FALLAR el caso en vez de dejar la corrida esperando para siempre.
MAX_LLAMADAS_LLM_POR_TURNO = 25
LIMITE_POR_CASO_S = 300.0


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Turno(_Modelo):
    usuario: str = Field(min_length=1)
    criterios: Criterios = Criterios()


class Efectos(_Modelo):
    """Lo que debe haber pasado EN EL MUNDO al terminar, diga lo que diga el texto."""

    universo_cambia: bool | None = None
    acta_creada: bool | None = None


class Caso(_Modelo):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    categoria: str = Field(min_length=1)
    preparar: tuple[str, ...] = Field(
        default=(), description='Operaciones del Gestor antes de conversar: "incorporar QQQ".'
    )
    turnos: tuple[Turno, ...] = Field(min_length=1)
    conversacion: Criterios = Criterios()
    efectos: Efectos = Efectos()


class Casos(_Modelo):
    eval_set_id: str = Field(pattern=r"^[a-z0-9_]+$")
    nombre: str
    descripcion: str
    casos: tuple[Caso, ...] = Field(min_length=1)


def cargar_casos(ruta: Path) -> Casos:
    with ruta.open(encoding="utf-8") as f:
        casos = Casos.model_validate(yaml.safe_load(f))
    ids = [c.id for c in casos.casos]
    if len(set(ids)) != len(ids):
        raise ValueError("ids de caso repetidos")
    return casos


@dataclass(frozen=True)
class Mundo:
    """Lo que un caso puede tocar: su Director, su almacén y su carpeta de actas."""

    director: BaseAgent
    gestor: GestorDatos
    runs: Path
    respaldo_fijo: tuple[str, ...] = ()
    """Textos cuyas cifras el Director conoce sin llamar a nada (su instrucción)."""


def preparar(gestor: GestorDatos, operaciones: tuple[str, ...]) -> None:
    for operacion in operaciones:
        accion, _, ticker = operacion.partition(" ")
        if accion not in PREPARACIONES or not ticker:
            raise ValueError(f"preparación desconocida '{operacion}': usa {PREPARACIONES} <TICKER>")
        getattr(gestor, accion)(ticker.strip())


def observar(
    usuario: str, eventos: list[Event], respaldo_previo: tuple[str, ...], autor: str
) -> TurnoObservado:
    """``autor``: solo su texto final es lo que el usuario lee como respuesta del turno."""
    llamadas: list[tuple[str, dict[str, Any]]] = []
    respuestas: list[tuple[str, dict[str, Any]]] = []
    textos: list[str] = []
    for evento in eventos:
        for parte in (evento.content.parts or []) if evento.content else []:
            if parte.function_call:
                llamadas.append(
                    (parte.function_call.name or "", dict(parte.function_call.args or {}))
                )
            elif parte.function_response:
                respuesta = parte.function_response.response or {}
                respuestas.append((parte.function_response.name or "", dict(respuesta)))
            elif parte.text and not parte.thought and evento.author == autor:
                textos.append(parte.text)
    return TurnoObservado(
        usuario=usuario,
        llamadas=tuple(llamadas),
        respuestas=tuple(respuestas),
        texto="\n".join(textos),
        respaldo_previo=respaldo_previo,
    )


async def conversar(mundo: Mundo, mensajes: tuple[str, ...]) -> list[TurnoObservado]:
    sesiones = InMemorySessionService()
    runner = Runner(agent=mundo.director, app_name=APP, session_service=sesiones)
    sesion = await sesiones.create_session(app_name=APP, user_id=USUARIO)
    turnos: list[TurnoObservado] = []
    respaldo = mundo.respaldo_fijo
    for mensaje in mensajes:
        contenido = types.Content(role="user", parts=[types.Part(text=mensaje)])
        eventos = [
            e
            async for e in runner.run_async(
                user_id=USUARIO,
                session_id=sesion.id,
                new_message=contenido,
                run_config=RunConfig(max_llm_calls=MAX_LLAMADAS_LLM_POR_TURNO),
            )
        ]
        turno = observar(mensaje, eventos, respaldo, mundo.director.name)
        turnos.append(turno)
        respaldo = (
            *respaldo,
            mensaje,
            *(json.dumps(r, ensure_ascii=False) for _, r in turno.respuestas),
        )
    await runner.close()
    return turnos


def _efectos(caso: Caso, version_inicial: str, mundo: Mundo) -> list[ResultadoCriterio]:
    resultados = []
    if caso.efectos.universo_cambia is not None:
        cambio = mundo.gestor.universo().version != version_inicial
        resultados.append(
            ResultadoCriterio(
                criterio="efectos.universo_cambia",
                cumple=cambio is caso.efectos.universo_cambia,
                detalle=f"el universo {'cambió' if cambio else 'no cambió'}",
            )
        )
    if caso.efectos.acta_creada is not None:
        hay_acta = mundo.runs.is_dir() and any(mundo.runs.iterdir())
        resultados.append(
            ResultadoCriterio(
                criterio="efectos.acta_creada",
                cumple=hay_acta is caso.efectos.acta_creada,
                detalle=f"{'hay' if hay_acta else 'no hay'} acta en la carpeta de corridas",
            )
        )
    return resultados


def juzgar(
    caso: Caso, turnos: list[TurnoObservado], version_inicial: str, mundo: Mundo
) -> list[ResultadoCriterio]:
    resultados: list[ResultadoCriterio] = []
    for i, (esperado, observado) in enumerate(zip(caso.turnos, turnos, strict=True), start=1):
        resultados += evaluar(esperado.criterios, observado, f"turno{i}")
    todo = TurnoObservado(
        usuario="\n".join(t.usuario for t in turnos),
        llamadas=tuple(ll for t in turnos for ll in t.llamadas),
        respuestas=tuple(r for t in turnos for r in t.respuestas),
        texto="\n".join(t.texto for t in turnos),
        respaldo_previo=mundo.respaldo_fijo,
    )
    resultados += evaluar(caso.conversacion, todo, "conversacion")
    return [*resultados, *_efectos(caso, version_inicial, mundo)]


async def correr_caso(
    caso: Caso, crear_mundo: Callable[[], Mundo]
) -> tuple[CasoEvaluado, list[TurnoObservado]]:
    """Los tres pasos del arnés. Un caso sin criterios no aprueba: no verificó nada."""
    mundo = crear_mundo()
    preparar(mundo.gestor, caso.preparar)
    version_inicial = mundo.gestor.universo().version
    turnos = await conversar(mundo, tuple(t.usuario for t in caso.turnos))
    resultados = juzgar(caso, turnos, version_inicial, mundo)
    cumplidos = sum(r.cumple for r in resultados)
    evaluado = CasoEvaluado(
        eval_id=caso.id,
        aprobado=bool(resultados) and cumplidos == len(resultados),
        nota=cumplidos / len(resultados) if resultados else None,
        criterios=tuple(
            CriterioEvaluado(criterio=r.criterio, cumple=r.cumple, detalle=r.detalle)
            for r in resultados
        ),
    )
    return evaluado, turnos
