"""Orquestador: ``Workflow`` de ADK (ADR-005) con la topología del spec de S3.

    iniciar → [market_analyst ∥ quant] → constructor ⇄ validador (máx. N) → reporter → cerrar

- Los pasos deterministas (quant, validador) son nodos-función que llaman a los mismos
  FunctionTools que usan los agentes; los que deciden o redactan son agentes LLM.
- El bucle lo corta el veredicto APROBADA o ``validacion.max_iteraciones_constructor``.
- ``cerrar`` arma ``RunState`` (revalidando todos los contratos), renderiza el informe, lo deja
  en el estado de sesión (ADR-009) y escribe ``runs/<run_id>/`` si el disco lo permite.
- S11: cada paso deja un HITO (``bitacora.emitir``) en ``pipeline_milestones`` y en
  ``runs/<run_id>/bitacora.jsonl`` mientras corre. Los emiten solo nodos SECUENCIALES: las ramas
  paralelas (analista ∥ quant) no escriben la lista —el delta de estado de ADK es por clave y
  una rama pisaría a la otra—; sus dos hitos los deja ``registrar_analisis`` tras la unión.
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
from investmentsys.contracts import (
    CandidatePortfolios,
    EtapaCorrida,
    EventoComite,
    FaseComite,
    MarketViews,
    QuantEstimates,
    RunState,
    Universe,
    ValidationReport,
    Veredicto,
)
from investmentsys.data import PriceProvider
from investmentsys.data_manager import GestorDatos
from investmentsys.orchestrator.bitacora import (
    CLAVE_HITOS,
    Reloj,
    detalle_estimacion,
    detalle_propuesta,
    detalle_veredicto,
    detalle_views,
    emitir,
    reloj_utc,
)
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
    CLAVE_MARKET_VIEWS,
    CLAVE_PRIOR,
    CLAVE_QUANT_ESTIMATES,
    CLAVE_RESTRICCIONES_SESION,
    CLAVE_UNIVERSO,
    CLAVE_VALIDACIONES,
    NucleoTools,
)
from investmentsys.tools.estado import Estado, leer, leer_lista, volcar

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
    reloj: Reloj = reloj_utc,
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

    def hito(
        estado: Estado, fase: FaseComite, iteracion: int, evento: EventoComite, detalle: str
    ) -> None:
        emitir(
            estado, destino / str(estado.get(CLAVE_RUN_ID)), reloj, fase, iteracion, evento, detalle
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
        ctx.state[CLAVE_HITOS] = []
        hito(
            ctx.state,
            FaseComite.COMITE,
            0,
            EventoComite.SESION_ABIERTA,
            f"sesión abierta. Corrida {ctx.state[CLAVE_RUN_ID]}, decisión al "
            f"{ctx.state[CLAVE_FECHA_DECISION]}, universo {', '.join(vigente.activos)} "
            f"(sello {vigente.version[:12]}), máximo {maximo} rondas.",
        )
        return (
            f"Corrida {ctx.state[CLAVE_RUN_ID]}, decisión al {ctx.state[CLAVE_FECHA_DECISION]}, "
            f"universo {vigente.version[:12]} ({', '.join(vigente.activos)})."
        )

    def quant(ctx: Context) -> dict[str, Any]:
        return _exigir(tools.estimar_mercado(ctx), "quant")

    def registrar_analisis(ctx: Context) -> str:
        """Los dos hitos de las ramas paralelas, ya unidas (ver la nota del módulo)."""
        crudas = ctx.state.get(CLAVE_MARKET_VIEWS)
        views = MarketViews.model_validate(crudas) if crudas else None
        hito(ctx.state, FaseComite.ANALISTA, 0, EventoComite.VIEWS_EMITIDAS, detalle_views(views))
        estimaciones = leer(ctx.state, CLAVE_QUANT_ESTIMATES, QuantEstimates)
        hito(
            ctx.state,
            FaseComite.ESTADISTICO,
            0,
            EventoComite.MERCADO_ESTIMADO,
            detalle_estimacion(estimaciones),
        )
        return "Análisis y estimación registrados."

    def _hito_propuesta(estado: Estado, evento: EventoComite, prefijo: str = "") -> None:
        ronda = leer_lista(estado, CLAVE_CANDIDATOS, CandidatePortfolios)[-1]
        detalle = f"{prefijo}{detalle_propuesta(ronda)}"
        hito(estado, FaseComite.CONSTRUCTOR, ronda.iteracion, evento, detalle)

    def asegurar_candidatos(ctx: Context) -> dict[str, Any]:
        """Si el constructor no dejó una ronda nueva, se construye la propuesta por defecto."""
        rondas = ctx.state.get(CLAVE_CANDIDATOS) or []
        validadas = ctx.state.get(CLAVE_VALIDACIONES) or []
        if len(rondas) > len(validadas):
            _hito_propuesta(ctx.state, EventoComite.PROPUESTA)
            return {"iteracion": len(rondas), "origen": "constructor"}
        nota = (
            f"iteración {len(rondas) + 1}: el constructor no dejó candidatos; se usó la "
            "propuesta por defecto (black_litterman, límites de config.yaml)"
        )
        ctx.state[CLAVE_NOTAS] = [*(ctx.state.get(CLAVE_NOTAS) or []), nota]
        salida = _exigir(tools.construir_candidatos(ctx), "constructor (por defecto)")
        ctx.state[CLAVE_NOTAS] = [*ctx.state[CLAVE_NOTAS], *salida["avisos"]]
        _hito_propuesta(
            ctx.state,
            EventoComite.PROPUESTA_POR_DEFECTO,
            "el constructor no dejó candidatos; por defecto, ",
        )
        return {"iteracion": salida["iteracion"], "origen": "por_defecto"}

    def validador(ctx: Context) -> Event:
        salida = _exigir(tools.validar_candidato(ctx), "validador")
        rechazada = salida["veredicto"] != Veredicto.APROBADA.value
        reintentar = rechazada and salida["iteracion"] < maximo
        reporte = leer_lista(ctx.state, CLAVE_VALIDACIONES, ValidationReport)[-1]
        hito(
            ctx.state,
            FaseComite.VALIDADOR,
            reporte.iteracion,
            EventoComite.VETO if rechazada else EventoComite.APROBADA,
            detalle_veredicto(reporte),
        )
        if rechazada and not reintentar:
            hito(
                ctx.state,
                FaseComite.COMITE,
                reporte.iteracion,
                EventoComite.ITERACIONES_AGOTADAS,
                f"agotadas las {maximo} rondas sin cartera aprobada: se informa sin recomendación.",
            )
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
        hito(
            ctx.state,
            FaseComite.REPORTER,
            0,
            EventoComite.ACTA_CONSOLIDADA,
            f"acta final consolidada ({final.etapa.value}).",
        )
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
            (union, registrar_analisis, constructor, asegurar_candidatos, validador),
            (validador, {RUTA_REPORTAR: reporter, RUTA_REINTENTAR: constructor}),
            (reporter, cerrar),
        ],
    )
