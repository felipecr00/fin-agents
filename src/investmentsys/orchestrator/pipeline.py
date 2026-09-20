"""Orquestador: ``Workflow`` de ADK (ADR-005) con la topología del spec de S3.

    iniciar → [market_analyst ∥ quant] → constructor ⇄ validador (máx. N) → reporter → cerrar

- Los pasos deterministas (quant, validador) son nodos-función que llaman a los mismos
  FunctionTools que usan los agentes; los que deciden o redactan son agentes LLM.
- El bucle lo corta el veredicto APROBADA o ``validacion.max_iteraciones_constructor``.
- ``cerrar`` arma ``RunState`` (revalidando todos los contratos), renderiza el informe, lo deja
  en el estado de sesión (ADR-009) y escribe ``runs/<run_id>/`` si el disco lo permite.
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
from investmentsys.contracts import EtapaCorrida, RunState, Universe, Veredicto
from investmentsys.data import PriceProvider
from investmentsys.data_manager import GestorDatos
from investmentsys.orchestrator.corrida import (
    CLAVE_CREADO_EN,
    CLAVE_DIRECTORIO,
    CLAVE_NARRATIVA,
    CLAVE_NOTAS,
    CLAVE_REPORTE,
    CLAVE_RUN_ID,
    CLAVE_RUN_STATE,
    armar_run_state,
    nuevo_run_id,
    persistir,
)
from investmentsys.portfolio import sesion_por_defecto
from investmentsys.tools import (
    CLAVE_CANDIDATOS,
    CLAVE_FECHA_DECISION,
    CLAVE_PRIOR,
    CLAVE_RESTRICCIONES_SESION,
    CLAVE_UNIVERSO,
    CLAVE_VALIDACIONES,
    NucleoTools,
)
from investmentsys.tools.estado import volcar

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
    universo: Universe | None = None,
) -> Workflow:
    """``universo``: el de la corrida. Por defecto, el vigente del Gestor de Datos, leído al
    INICIAR cada corrida (un alta entre dos corridas se ve sin reiniciar el servidor). Si la
    sesión ya trae un universo en su estado (S8), manda ese."""
    tools = NucleoTools(config, provider)
    destino = directorio_runs or RAIZ_PROYECTO / config.corridas.directorio
    maximo = config.validacion.max_iteraciones_constructor
    nombre_modelo = (
        modelo.model
        if isinstance(modelo, BaseLlm)
        else (modelo or config.inferencia.nivel_1.modelo)
    )

    def iniciar(ctx: Context) -> str:
        """Identidad de la corrida y fecha de decisión, antes de abrir ramas paralelas."""
        run_id, creado_en = nuevo_run_id()
        ctx.state[CLAVE_RUN_ID] = ctx.state.get(CLAVE_RUN_ID) or run_id
        ctx.state[CLAVE_CREADO_EN] = ctx.state.get(CLAVE_CREADO_EN) or creado_en.isoformat()
        if ctx.state.get(CLAVE_UNIVERSO) is None:
            ctx.state[CLAVE_UNIVERSO] = volcar(universo or GestorDatos(config).universo())
        vigente = Universe.model_validate(ctx.state[CLAVE_UNIVERSO])
        sesion = ctx.state.get(CLAVE_RESTRICCIONES_SESION)
        if sesion is None or sesion.get("universe_version") != vigente.version:
            # Sin restricciones de sesión, o de otro universo: las de config sobre el vigente.
            ctx.state[CLAVE_RESTRICCIONES_SESION] = volcar(
                sesion_por_defecto(vigente, config.optimizacion)
            )
        if not ctx.state.get(CLAVE_FECHA_DECISION):
            ultimo = provider.precios(vigente.activos).index[-1].date()
            ctx.state[CLAVE_FECHA_DECISION] = ultimo.isoformat()
        for clave in (CLAVE_CANDIDATOS, CLAVE_VALIDACIONES, CLAVE_NOTAS):
            ctx.state[clave] = []
        ctx.state[CLAVE_PRIOR] = None
        return (
            f"Corrida {ctx.state[CLAVE_RUN_ID]}, decisión al {ctx.state[CLAVE_FECHA_DECISION]}, "
            f"universo {vigente.version[:12]} ({', '.join(vigente.activos)})."
        )

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
        ctx.state[CLAVE_NOTAS] = [*ctx.state[CLAVE_NOTAS], *salida["avisos"]]
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
        ctx.state[CLAVE_REPORTE] = final.reporte_markdown
        ctx.state[CLAVE_RUN_STATE] = final.model_dump(mode="json")
        try:
            carpeta = persistir(final, destino)
        except OSError as exc:  # disco de solo lectura o efímero (contenedor): no es un fallo
            ctx.state[CLAVE_NOTAS] = [*notas, f"RunState solo en la sesión: {exc}"]
            return f"{final.reporte_markdown}\n\n_RunState en el estado de sesión._"
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
