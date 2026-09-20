"""``convocar_comite``: la única puerta del Director al comité formal, en DOS FASES (ADR-014).

- ``solicitar`` verifica las condiciones objetivas del gate en el estado de sesión (universo
  con diagnósticos completos, prior resuelto) y devuelve el RESUMEN de lo que se correría más
  un token de un solo uso.
- ``ejecutar`` exige ese token, en un turno POSTERIOR al de la solicitud, y corre
  ``crear_pipeline`` sin modificarlo en una sesión anidada. El acta registra el resumen
  presentado y la confirmación (``RunState.aprobacion``).

La custodia es la secuencia: no existe un ``confirmacion_usuario: bool`` que el propio LLM
pueda rellenar. El token muere con cualquier cambio de ``universe_version`` o de lo resumido, y
(S9) solo vale en el turno del usuario INMEDIATAMENTE posterior al que presentó la orden: un
"sí" confirma lo que el usuario acaba de leer, no algo de hace cinco mensajes. Toda falta a la
secuencia es una ``ViolacionGateError`` controlada (``tests/test_gate_security.py``).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google.adk.models.base_llm import BaseLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types
from pydantic import ValidationError

from investmentsys.agents.market_analyst import ViewsInvalidasError
from investmentsys.config import Config
from investmentsys.contracts import (
    AprobacionComite,
    EstadoPrior,
    HitoComite,
    MarketViews,
    PriorProvenance,
    ResumenComite,
    RunState,
    SessionConstraints,
    SolicitudComite,
    Universe,
)
from investmentsys.data import PriceProvider
from investmentsys.orchestrator.bitacora import (
    CLAVE_HITOS,
    linea_con_tiempo,
    renderizar_cronologia,
)
from investmentsys.orchestrator.corrida import (
    CLAVE_APROBACION,
    CLAVE_DIRECTORIO,
    CLAVE_REPORTE,
    CLAVE_RUN_STATE,
)
from investmentsys.orchestrator.memorandum import renderizar_memorandum
from investmentsys.orchestrator.pipeline import EtapaFallidaError, crear_pipeline
from investmentsys.portfolio import mensaje_estado_prior, sesion_por_defecto
from investmentsys.tools.estado import (
    CLAVE_FECHA_DECISION,
    CLAVE_MARKET_VIEWS,
    CLAVE_RESTRICCIONES_SESION,
    CLAVE_SOLICITUD_COMITE,
    CLAVE_UNIVERSO,
    Estado,
    FaltaEnEstadoError,
    ResultadoObsoletoError,
    exigir_sello,
    leer,
    leer_fecha,
    leer_lista,
    volcar,
)
from investmentsys.tools.ficha import CLAVE_ANEXO
from investmentsys.tools.hitos_en_vivo import transmitir

CLAVE_SOLICITUD = CLAVE_SOLICITUD_COMITE
FASE_SOLICITAR = "solicitar"
FASE_EJECUTAR = "ejecutar"
ETIQUETA_COMITE = "comite_formal"
MENSAJE_SIN_MATERIAL = "Sin material del usuario: emite tus views desde tu conocimiento general."
NOTA_VIEWS_DEL_COMITE = (
    "Las views de la corrida las emite el Analista del comité DURANTE la corrida, a partir del "
    "material_usuario y las views_de_partida del resumen (que recibe citados, sin verificar); "
    "si ambos están vacíos, opina desde su conocimiento general con confianza topada. No es "
    "una corrida sin views salvo que él no emita ninguna."
)
CLAVES_DEL_ACTA = (CLAVE_RUN_STATE, CLAVE_REPORTE, CLAVE_DIRECTORIO)


class GateComiteError(ValueError):
    """El comité no se puede convocar (todavía): el mensaje dice qué falta y cómo resolverlo."""


class ViolacionGateError(GateComiteError):
    """Se intentó ``ejecutar`` fuera de la secuencia del gate: sin token vigente, en el mismo
    turno de la solicitud, con turnos de por medio o tras un cambio de lo aprobado."""


def _turno_anterior(ctx: ToolContext) -> str | None:
    """``invocation_id`` del turno inmediatamente anterior al actual, según los eventos.

    Cada mensaje del usuario abre una invocación de ADK y todos los eventos del turno (el del
    usuario incluido) la llevan: el último id distinto del actual es el turno anterior.
    """
    previos = [
        e.invocation_id
        for e in ctx.session.events
        if e.invocation_id and e.invocation_id != ctx.invocation_id
    ]
    return previos[-1] if previos else None


def _rechazo(exc: Exception) -> dict[str, Any]:
    return {"status": "rechazado", "tipo": type(exc).__name__, "motivo": str(exc)}


def _material_para_el_analista(resumen: ResumenComite) -> str:
    """Lo aprobado, como material CITADO: el Analista lo trata como evidencia, no como órdenes."""
    partes = []
    if resumen.material_usuario:
        partes.append(resumen.material_usuario)
    if resumen.views_de_partida is not None and resumen.views_de_partida.views:
        lineas = [
            f"- {v.tipo.value} {dict(v.coeficientes)}: q_anual={v.q_anual}, "
            f"confianza={v.confianza}. {v.justificacion}"
            for v in resumen.views_de_partida.views
        ]
        partes.append(
            "Views exploratorias conversadas antes con el usuario (no verificadas):\n"
            + "\n".join(lineas)
        )
    return "\n\n".join(partes) or MENSAJE_SIN_MATERIAL


@dataclass(frozen=True)
class ComiteTools:
    config: Config
    provider: PriceProvider
    modelo: str | BaseLlm | None = None
    directorio_runs: Path | None = None
    reloj: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    nuevo_token: Callable[[], str] = field(default=lambda: uuid.uuid4().hex)

    async def convocar_comite(
        self,
        fase: str,
        tool_context: ToolContext,
        token: str = "",
        material: str = "",
    ) -> dict[str, Any]:
        """Convoca al COMITÉ FORMAL (corrida completa con veto y acta). Dos fases obligatorias.

        1. fase="solicitar": comprueba que el universo y el prior estén resueltos y devuelve
           el RESUMEN de la corrida y un token. Presenta ese resumen al usuario tal cual y
           espera su respuesta: no llames a "ejecutar" en el mismo turno (se rechaza).
        2. fase="ejecutar": solo si el usuario confirmó tras ver el resumen, con el token de
           la solicitud. Corre el comité y devuelve la recomendación y la ruta del acta. El
           token vale una vez y muere si cambia el universo o las restricciones.

        Args:
            fase: "solicitar" o "ejecutar".
            token: el devuelto por "solicitar"; obligatorio en "ejecutar".
            material: solo en "solicitar". Texto del usuario (noticias, tesis) que el Analista
                recibirá CITADO y sin verificar; vacío si no aportó nada.
        """
        try:
            if fase == FASE_SOLICITAR:
                return self._solicitar(tool_context, material)
            if fase == FASE_EJECUTAR:
                return await self._ejecutar(tool_context, token)
            raise GateComiteError(f"fase desconocida '{fase}': usa 'solicitar' o 'ejecutar'")
        except (GateComiteError, FaltaEnEstadoError, ResultadoObsoletoError) as exc:
            return _rechazo(exc)
        except ValidationError as exc:
            return _rechazo(exc)

    # ---------------------------------------------------------------- solicitar
    def _solicitar(self, ctx: ToolContext, material: str) -> dict[str, Any]:
        resumen = self._resumir(ctx.state, material.strip() or None)
        solicitud = SolicitudComite(
            token=self.nuevo_token(),
            resumen=resumen,
            solicitado_en=self.reloj(),
            invocacion=ctx.invocation_id,
        )
        ctx.state[CLAVE_SOLICITUD] = volcar(solicitud)  # reemplaza a cualquier solicitud previa
        return {
            "status": "pendiente_de_confirmacion",
            "token": solicitud.token,
            "resumen": volcar(resumen),
            "que_hara_el_comite": NOTA_VIEWS_DEL_COMITE,
            CLAVE_ANEXO: renderizar_memorandum(
                resumen, self.config.validacion.max_iteraciones_constructor
            ),
            "siguiente_paso": (
                "Presenta la Orden Preparatoria al usuario y espera su confirmación explícita. "
                "Solo entonces, en su siguiente turno, llama a fase='ejecutar' con este token."
            ),
        }

    def _resumir(self, estado: Estado, material: str | None) -> ResumenComite:
        universo = leer(estado, CLAVE_UNIVERSO, Universe)
        if universo.estado_prior is EstadoPrior.PENDIENTE:
            raise GateComiteError(f"prior sin resolver. {mensaje_estado_prior(universo)}")
        if estado.get(CLAVE_RESTRICCIONES_SESION) is None:
            sesion = sesion_por_defecto(universo, self.config.optimizacion)
        else:
            sesion = leer(estado, CLAVE_RESTRICCIONES_SESION, SessionConstraints)
            exigir_sello(sesion.universe_version, universo.version, "restricciones de la sesión")
        views = estado.get(CLAVE_MARKET_VIEWS)
        de_partida = MarketViews.model_validate(views) if views else None
        if de_partida is not None and de_partida.activos != universo.activos:
            de_partida = None  # de otro universo: no son punto de partida de esta corrida
        neutral = universo.estado_prior is EstadoPrior.NEUTRAL
        procedencias = {
            d.ticker: PriorProvenance.NEUTRAL if neutral else d.prior_provenance
            for d in universo.diagnosticos
        }
        return ResumenComite.model_validate(
            {
                "universe_version": universo.version,
                "activos": universo.activos,
                "inicio_datos": {d.ticker: d.fecha_inicio_datos for d in universo.diagnosticos},
                "estado_prior": universo.estado_prior,
                "procedencias_prior": procedencias,
                "restricciones": sesion,
                "fecha_decision": leer_fecha(estado),
                "views_de_partida": de_partida,
                "material_usuario": material,
            }
        )

    # ----------------------------------------------------------------- ejecutar
    async def _ejecutar(self, ctx: ToolContext, token: str) -> dict[str, Any]:
        cruda = ctx.state.get(CLAVE_SOLICITUD)
        if not token or cruda is None:
            raise ViolacionGateError(
                "no hay una solicitud vigente: llama primero a fase='solicitar', presenta el "
                "resumen al usuario y espera su confirmación"
            )
        solicitud = SolicitudComite.model_validate(cruda)
        if token != solicitud.token:
            raise ViolacionGateError("token desconocido o ya usado: vuelve a fase='solicitar'")
        if ctx.invocation_id == solicitud.invocacion:
            raise ViolacionGateError(
                "el resumen se pidió en este mismo turno: el usuario aún no lo ha visto. "
                "Preséntaselo y espera su respuesta; el token sigue vigente"
            )
        if _turno_anterior(ctx) != solicitud.invocacion:
            ctx.state[CLAVE_SOLICITUD] = None
            raise ViolacionGateError(
                "token invalidado: la orden se presentó hace más de un turno y la confirmación "
                "debe seguir inmediatamente a la orden. Vuelve a fase='solicitar', presenta la "
                "orden vigente y espera la respuesta del usuario"
            )
        vigente = leer(ctx.state, CLAVE_UNIVERSO, Universe)
        aprobado = solicitud.resumen
        if vigente.version != aprobado.universe_version:
            ctx.state[CLAVE_SOLICITUD] = None
            raise ViolacionGateError(
                f"token invalidado: el universo cambió desde la solicitud (se aprobó "
                f"{aprobado.universe_version[:12]}… y el vigente es {vigente.version[:12]}…). Lo "
                "que el usuario aprobó ya no es lo que se correría: vuelve a fase='solicitar'"
            )
        if self._resumir(ctx.state, aprobado.material_usuario) != aprobado:
            ctx.state[CLAVE_SOLICITUD] = None
            raise ViolacionGateError(
                "token invalidado: las restricciones, la fecha o las views de partida cambiaron "
                "desde la solicitud: vuelve a fase='solicitar' y presenta el resumen nuevo"
            )
        ctx.state[CLAVE_SOLICITUD] = None  # un solo uso, pase lo que pase con la corrida
        aprobacion = AprobacionComite(
            resumen=aprobado,
            solicitado_en=solicitud.solicitado_en,
            confirmado_en=self.reloj(),
            invocacion_solicitud=solicitud.invocacion,
            invocacion_confirmacion=ctx.invocation_id,
        )
        ctx.state[CLAVE_HITOS] = []  # la cronología es la de ESTA corrida
        try:
            final = await self._correr_pipeline(ctx, aprobacion)
        except (EtapaFallidaError, ViewsInvalidasError) as exc:
            return {
                "status": "error",
                "tipo": type(exc).__name__,
                "mensaje": str(exc),
                CLAVE_ANEXO: self._cronologia(ctx.state),
            }
        for clave in CLAVES_DEL_ACTA:
            ctx.state[clave] = final.get(clave)
        salida = self._salida(RunState.model_validate(final[CLAVE_RUN_STATE]), final)
        return {**salida, CLAVE_ANEXO: self._cronologia(ctx.state)}

    @staticmethod
    def _cronologia(estado: Estado) -> str:
        return renderizar_cronologia(leer_lista(estado, CLAVE_HITOS, HitoComite))

    async def _correr_pipeline(
        self, ctx: ToolContext, aprobacion: AprobacionComite
    ) -> dict[str, Any]:
        """Sesión anidada y aislada: lo exploratorio del Director no entra al comité ni al revés.

        Entra solo lo aprobado (universo, restricciones, fecha) y la aprobación misma.
        """
        resumen = aprobacion.resumen
        inicial: dict[str, Any] = {
            CLAVE_UNIVERSO: ctx.state.get(CLAVE_UNIVERSO),
            CLAVE_RESTRICCIONES_SESION: volcar(resumen.restricciones),
            CLAVE_APROBACION: volcar(aprobacion),
        }
        if resumen.fecha_decision is not None:
            inicial[CLAVE_FECHA_DECISION] = resumen.fecha_decision.isoformat()
        pipeline = crear_pipeline(self.config, self.provider, self.modelo, self.directorio_runs)
        sesiones = InMemorySessionService()
        runner = Runner(node=pipeline, app_name=ctx.session.app_name, session_service=sesiones)
        sesion = await sesiones.create_session(
            app_name=ctx.session.app_name, user_id=ctx.user_id, state=inicial
        )
        mensaje = types.Content(
            role="user", parts=[types.Part(text=_material_para_el_analista(resumen))]
        )
        en_vivo, enviados = self.config.corridas.transmitir_hitos_en_vivo, 0
        try:
            async for evento in runner.run_async(
                user_id=ctx.user_id, session_id=sesion.id, new_message=mensaje
            ):
                # Los hitos suben a la sesión del Director A MEDIDA que ocurren (el delta de
                # cada nodo trae la lista completa): si la corrida revienta, lo ya deliberado
                # no se pierde con la sesión anidada. Y, si se puede, al chat EN VIVO (ADR-021).
                crudos = (evento.actions.state_delta or {}).get(CLAVE_HITOS)
                if not crudos:
                    continue
                ctx.state[CLAVE_HITOS] = crudos
                hitos = [HitoComite.model_validate(c) for c in crudos]
                for hito in hitos[enviados:]:
                    en_vivo = en_vivo and await transmitir(
                        ctx, linea_con_tiempo(hito, hitos[0].timestamp)
                    )
                enviados = len(hitos)
        finally:
            await runner.close()
        final = await sesiones.get_session(
            app_name=ctx.session.app_name, user_id=ctx.user_id, session_id=sesion.id
        )
        if final is None or final.state.get(CLAVE_RUN_STATE) is None:
            raise EtapaFallidaError("el comité terminó sin dejar un RunState")
        return dict(final.state)

    @staticmethod
    def _salida(corrida: RunState, final: dict[str, Any]) -> dict[str, Any]:
        ultima = corrida.ultima_validacion
        cartera = corrida.portafolio_final
        assert corrida.aprobacion is not None
        return {
            "status": "success",
            "etiqueta": ETIQUETA_COMITE,
            "validado": corrida.aprobado,
            "run_id": corrida.run_id,
            "etapa": corrida.etapa.value,
            "universe_version": corrida.universo.version,
            "fecha_decision": corrida.fecha_decision.isoformat(),
            "iteraciones": len(corrida.candidatos),
            "veredicto": ultima.veredicto.value if ultima else None,
            "recomendacion": None
            if cartera is None
            else {"candidato": cartera.nombre, "pesos": dict(cartera.pesos)},
            "metricas_oos": None
            if ultima is None
            else {
                "sharpe_oos": ultima.metricas_oos.sharpe_oos,
                "retorno_anualizado": ultima.metricas_oos.retorno_anualizado,
                "volatilidad_anualizada": ultima.metricas_oos.volatilidad_anualizada,
                "max_drawdown": ultima.metricas_oos.max_drawdown,
            },
            "razones_rechazo": list(ultima.razones_rechazo) if ultima else [],
            "errores": list(corrida.errores),
            "acta": final.get(CLAVE_DIRECTORIO),
            "aprobacion_registrada_en_el_acta": {
                "solicitado_en": corrida.aprobacion.solicitado_en.isoformat(),
                "confirmado_en": corrida.aprobacion.confirmado_en.isoformat(),
            },
            "disclaimer": corrida.disclaimer,
        }

    def function_tools(self) -> list[FunctionTool]:
        return [FunctionTool(self.convocar_comite)]
