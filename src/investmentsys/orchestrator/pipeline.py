"""Orquestador: ``Workflow`` de ADK (ADR-005) con la topología del spec de S3.

    iniciar → [market_analyst ∥ quant] → constructor ⇄ validador (máx. N) → reporter → cerrar

- Los pasos deterministas (quant, validador) son nodos-función que llaman a los mismos
  FunctionTools que usan los agentes; los que deciden o redactan son agentes LLM.
- El bucle lo corta el veredicto APROBADA o ``validacion.max_iteraciones_constructor``.
- ``cerrar`` arma ``RunState`` (revalidando todos los contratos), renderiza el informe y
  escribe ``runs/<run_id>/``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from google.adk.agents.context import Context
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.models.base_llm import BaseLlm
from google.adk.workflow import JoinNode, Workflow

from investmentsys.agents.constructor import crear_constructor
from investmentsys.agents.market_analyst import crear_market_analyst
from investmentsys.agents.reporter import crear_reporter, renderizar
from investmentsys.config import RAIZ_PROYECTO, Config
from investmentsys.contracts import EtapaCorrida, RunState, Veredicto
from investmentsys.data import PriceProvider
from investmentsys.orchestrator.corrida import (
    CLAVE_CREADO_EN,
    CLAVE_DIRECTORIO,
    CLAVE_NARRATIVA,
    CLAVE_NOTAS,
    CLAVE_REPORTE,
    CLAVE_RUN_ID,
    armar_run_state,
    nuevo_run_id,
    persistir,
)
from investmentsys.tools import (
    CLAVE_CANDIDATOS,
    CLAVE_FECHA_DECISION,
    CLAVE_VALIDACIONES,
    NucleoTools,
)

NOMBRE = "pipeline_inversiones"
RUTA_REINTENTAR = "REINTENTAR"
RUTA_REPORTAR = "REPORTAR"  # aprobada, o rechazada con las iteraciones agotadas


class EtapaFallidaError(RuntimeError):
    """Un paso determinista devolvió ``status=error``: la corrida no puede continuar."""


def _exigir(salida: dict[str, Any], etapa: str) -> dict[str, Any]:
    if salida.get("status") != "success":
        raise EtapaFallidaError(f"{etapa}: {salida.get('tipo')}: {salida.get('mensaje')}")
    return salida


def crear_pipeline(
    config: Config,
    provider: PriceProvider,
    modelo: str | BaseLlm | None = None,
    directorio_runs: Path | None = None,
) -> Workflow:
    tools = NucleoTools(config, provider)
    destino = directorio_runs or RAIZ_PROYECTO / config.corridas.directorio
    maximo = config.validacion.max_iteraciones_constructor
    nombre_modelo = (
        modelo.model if isinstance(modelo, BaseLlm) else (modelo or config.agentes.modelo)
    )

    def iniciar(ctx: Context) -> str:
        """Identidad de la corrida y fecha de decisión, antes de abrir ramas paralelas."""
        run_id, creado_en = nuevo_run_id()
        ctx.state[CLAVE_RUN_ID] = ctx.state.get(CLAVE_RUN_ID) or run_id
        ctx.state[CLAVE_CREADO_EN] = ctx.state.get(CLAVE_CREADO_EN) or creado_en.isoformat()
        if not ctx.state.get(CLAVE_FECHA_DECISION):
            ultimo = provider.precios(config.portafolio.activos).index[-1].date()
            ctx.state[CLAVE_FECHA_DECISION] = ultimo.isoformat()
        for clave in (CLAVE_CANDIDATOS, CLAVE_VALIDACIONES, CLAVE_NOTAS):
            ctx.state[clave] = []
        return f"Corrida {ctx.state[CLAVE_RUN_ID]}, decisión al {ctx.state[CLAVE_FECHA_DECISION]}."

    def quant(ctx: Context) -> dict[str, Any]:
        return _exigir(tools.estimar_mercado(ctx), "quant")

    def asegurar_candidatos(ctx: Context) -> dict[str, Any]:
        """Si el constructor no dejó una ronda nueva, se construye la propuesta por defecto."""
        rondas = ctx.state.get(CLAVE_CANDIDATOS) or []
        validadas = ctx.state.get(CLAVE_VALIDACIONES) or []
        if len(rondas) > len(validadas):
            return {"iteracion": len(rondas), "origen": "constructor"}
        nota = (
            f"iteración {len(rondas) + 1}: el constructor no dejó candidatos; se usó la "
            "propuesta por defecto (black_litterman, límites de config.yaml)"
        )
        ctx.state[CLAVE_NOTAS] = [*(ctx.state.get(CLAVE_NOTAS) or []), nota]
        salida = _exigir(tools.construir_candidatos(ctx), "constructor (por defecto)")
        return {"iteracion": salida["iteracion"], "origen": "por_defecto"}

    def validador(ctx: Context) -> Event:
        salida = _exigir(tools.validar_candidato(ctx), "validador")
        rechazada = salida["veredicto"] != Veredicto.APROBADA.value
        reintentar = rechazada and salida["iteracion"] < maximo
        ruta = RUTA_REINTENTAR if reintentar else RUTA_REPORTAR
        return Event(output=salida, actions=EventActions(route=ruta))

    def corrida_para_reporte(contexto: ReadonlyContext) -> RunState:
        return armar_run_state(contexto.state, config, EtapaCorrida.REPORTE)

    def cerrar(ctx: Context) -> str:
        notas = tuple(ctx.state.get(CLAVE_NOTAS) or ())
        borrador = armar_run_state(ctx.state, config, EtapaCorrida.REPORTE)
        errores = () if borrador.aprobado else (f"sin cartera aprobada tras {maximo} iteraciones",)
        narrativa = str(ctx.state.get(CLAVE_NARRATIVA) or "")
        final = borrador.avanzar(
            etapa=EtapaCorrida.COMPLETADA if borrador.aprobado else EtapaCorrida.FALLIDA,
            errores=errores,
            reporte_markdown=renderizar(
                borrador.avanzar(errores=errores), narrativa, nombre_modelo, notas
            ),
        )
        carpeta = persistir(final, destino)
        ctx.state[CLAVE_REPORTE] = final.reporte_markdown
        ctx.state[CLAVE_DIRECTORIO] = str(carpeta)
        return f"{final.reporte_markdown}\n\n_Guardado en `{carpeta}`._"

    analista = crear_market_analyst(config, provider, modelo)
    constructor = crear_constructor(config, tools, modelo)
    reporter = crear_reporter(config, corrida_para_reporte, CLAVE_NARRATIVA, modelo)
    union = JoinNode(name="analisis_y_estimacion")
    return Workflow(
        name=NOMBRE,
        description="Analista ∥ Quant → Constructor ⇄ Validador → Reporter.",
        edges=[
            ("START", iniciar),
            (iniciar, analista, union),
            (iniciar, quant, union),
            (union, constructor, asegurar_candidatos, validador),
            (validador, {RUTA_REPORTAR: reporter, RUTA_REINTENTAR: constructor}),
            (reporter, cerrar),
        ],
    )
