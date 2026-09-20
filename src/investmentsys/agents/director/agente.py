"""Director de Análisis (S8): un ``LlmAgent`` que conversa, clasifica la intención y rutea.

Ruteo jerárquico desde S10 (ADR-020): personas con voz propia (Analista, Estadístico,
Escéptico), Gestor-Fintual transaccional de una sola tool, Constructor y comité.

No calcula nada. Su instrucción es el spec aprobado (``instruccion.py``, literal) más el
CABLEADO de abajo, que solo dice qué herramienta atiende qué y en qué orden. Las custodias no
viven en el prompt sino en las herramientas: sellado por ``universe_version`` (ADR-012), gate
del comité en dos fases y ``validado: false`` en todo resultado exploratorio (ADR-014).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.base_llm import BaseLlm
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from investmentsys.agents.anexos import (
    anexar_al_cierre,
    ocultar_anexos_al_modelo,
    recoger_anexos,
)
from investmentsys.agents.director.instruccion import INSTRUCCION
from investmentsys.agents.esceptico import crear_esceptico, entregar_pesos
from investmentsys.agents.estadistico import crear_estadistico
from investmentsys.agents.fintual_data import CABLEADO as CABLEADO_GESTOR
from investmentsys.agents.fintual_data import crear_gestor_fintual
from investmentsys.agents.market_analyst import crear_market_analyst
from investmentsys.agents.modelo import resolver_modelo
from investmentsys.agents.persona import resultado_para_el_director
from investmentsys.config import Config
from investmentsys.contracts import DISCLAIMER
from investmentsys.data import PriceProvider
from investmentsys.data_manager import GestorDatos, GestorError
from investmentsys.orchestrator.comite import ComiteTools
from investmentsys.tools import (
    CLAVE_CANDIDATOS,
    CLAVE_UNIVERSO,
    CLAVE_VALIDACIONES,
    NucleoTools,
)
from investmentsys.tools.estado import volcar
from investmentsys.tools.exploratorio import exploratorio
from investmentsys.tools.ficha import ATIENDE
from investmentsys.tools.mesa import NOMBRE_TOOL as TOOL_MESA
from investmentsys.tools.mesa import MesaTools, componer_sala
from investmentsys.tools.nucleo import ERRORES_DE_DOMINIO

NOMBRE = "director"

CABLEADO = """\
Cableado de herramientas
Este bloque solo dice qué herramienta atiende a cada especialista y en qué orden usarlas. Los
modos y las reglas son los de arriba.

Estado de la sesión: {estado_sesion}

- MESA DE TRABAJO (tuya): `consultar_mesa_trabajo` muestra qué hay sobre la mesa (universo,
  vistas, estimaciones, carteras, diagnósticos, restricciones), quién lo puso y si sigue
  vigente; con vista="sala", quién está en la sala. No calcula nada. Presentar el universo
  aplica al INICIO de la sesión, no a cada consulta: llámala para esa presentación inicial y
  cuando pregunten «¿qué tenemos?», «muestra la mesa» o «¿quién está en la sala?»; para lo
  demás, ve directo a la herramienta que atiende la consulta. No describas la mesa ni el
  equipo de memoria.
{cableado_gestor}\
- PERSONAS (tienen voz propia: le responden ELLAS al usuario, que lee su respuesta completa
  antes que la tuya). Se consultan como una herramienta, con `pregunta`: lo que dijo el usuario,
  citado. La persona no ve esta conversación: todo lo que necesite va en `pregunta`.
  · `estadistico(pregunta)`: volatilidades, retornos históricos con su intervalo y
    correlaciones por par del universo vigente.
  · `esceptico(pregunta, pesos?)`: diagnóstico de una cartera fuera del comité, nunca un
    veredicto. Si el usuario TRAE una cartera, sus pesos van en `pesos` como fracciones, tal
    como los dio: no los completes ni los renormalices. Si pregunta por «esta cartera» o «la
    propuesta», omite `pesos`: el Escéptico mide la cartera vigente sobre la mesa.
  · `market_analyst(request)`: el Analista de Mercado. En `request` va lo que dijo el usuario,
    citado; el material externo que haya pegado va citado y marcado como no verificado.
  NUNCA hables por una persona. Si el usuario pregunta qué opina, qué estima o qué le preocupa a
  una de ellas, consúltala EN ESTE TURNO, aunque creas saber la respuesta o ya haya hablado
  antes: lo que dijo sobre otra cartera u otro universo no vale para esta. Decir «al Escéptico
  le preocupa…» sin haberlo consultado en el turno es inventarle una opinión.
  Cuando una persona ya respondió, NO repitas ni resumas sus cifras: el usuario ya las leyó, de
  su fuente. Tu cierre es breve y solo coordina: qué sigue, a quién más conviene oír, o en qué
  discrepan dos especialistas (señálalo, no lo suavices). Si la persona no pudo responder
  (error o rechazo), explica tú qué falta.
- CONSTRUCTOR DE CARTERAS: `construir_candidatos` (necesita views vigentes del Analista; si
  la sesión no tiene estimaciones, la herramienta del Estadístico las calcula sola y la salida
  lo avisa: dilo). Las restricciones de la sesión se cambian con `ajustar_restricciones`, solo
  con lo que pida el usuario; si el pedido es infactible la herramienta lo rechaza: explica su
  motivo, no busques tú otro valor que "funcione".
- COMITÉ FORMAL: solo con `convocar_comite`, en dos fases. `fase="solicitar"` devuelve el
  resumen de la corrida y un token, y la Orden Preparatoria de Sesión queda anexada a tu
  respuesta: di que es la orden a revisar, pide la confirmación y espera (sin ponerle un
  encabezado tuyo ni reescribirla por secciones: el resumen completo va debajo). Solo si el
  usuario confirma en su siguiente mensaje, `fase="ejecutar"` con ese token. La orden vale solo
  para ese mensaje: si el usuario habla de otra cosa entremedio, vuelve a `fase="solicitar"`.
  El token es interno: no lo muestres ni lo menciones al usuario.
- ATRIBUCIÓN: toda cifra que digas TÚ (del Constructor, del Gestor, del comité, del Analista)
  va con su fuente, en la misma frase: "el Constructor propone…", "según el Gestor de Datos…",
  "el Analista opina…", "el comité aprobó…". Las del Estadístico y el Escéptico las dicen
  ellos. Las fichas de origen, la tabla de la mesa y la orden del comité las anexa el código al
  final de tu respuesta: no las copies ni las rehagas.
- Ofrece solo lo que una herramienta de esta lista puede hacer. No hay herramientas para
  ejecutar órdenes, predecir precios, vigilar el mercado o avisar de cambios, buscar noticias,
  ni leer cuentas de un broker: no las ofrezcas ni las insinúes.
- Una respuesta con `validado: false` es exploratoria: dilo al presentarla. Solo una corrida
  de `convocar_comite` con `validado: true` es una recomendación.
- Toda cifra que cites debe aparecer, idéntica, en la salida de una herramienta de esta
  conversación. Si no tienes la cifra, llama a la herramienta o di que no la tienes.
  Tampoco hagas aritmética propia con cifras (sumar pesos, restar retornos, promediar): una
  cifra derivada que ninguna herramienta devolvió es una cifra tuya, y no las das.
- Si una herramienta responde `status` "error" o "rechazado", explica al usuario el motivo que
  trae (qué quedó obsoleto o qué falta, y por qué) y propón el siguiente paso. No reintentes
  en silencio.
- Cuando presentes cifras o una recomendación, cierra con: "{disclaimer}"
"""

SIN_UNIVERSO = "no hay universo cargado ({motivo}). Dilo antes de cualquier análisis."


def _estado_sesion(estado: Any) -> str:
    universo = estado.get(CLAVE_UNIVERSO)
    if not universo:
        return SIN_UNIVERSO.format(motivo=estado.get(CLAVE_ERROR_UNIVERSO) or "sesión nueva")
    activos = ", ".join(d["ticker"] for d in universo["diagnosticos"])
    return f"universo vigente `{universo['version'][:12]}` con {activos}."


CLAVE_ERROR_UNIVERSO = "director_error_universo"


AVISO_ESTIMACIONES = (
    "no había estimaciones en la sesión: el Estadístico (su herramienta, sin conversación) las "
    "calculó ahora sobre el universo vigente; están en la mesa y son exploratorias"
)


def crear_director(
    config: Config,
    provider: PriceProvider,
    gestor: GestorDatos,
    modelo: str | BaseLlm | None = None,
    directorio_runs: Path | None = None,
) -> LlmAgent:
    """``modelo`` permite inyectar un LLM falso en tests; por defecto, ``config.agentes``."""
    nucleo = NucleoTools(config, provider)
    comite = ComiteTools(config, provider, modelo, directorio_runs)
    # Ruteo jerárquico (S10, ADR-020): personas, Gestor-Fintual, Constructor y comité.
    recien_estimado: list[bool] = []

    def nueva_propuesta(ctx: ToolContext) -> None:
        """Fuera del comité no hay bucle Constructor ⇄ Validador: cada propuesta es la ronda 1.

        Y no obliga a pasar por la persona del Estadístico solo para tener insumos: si la sesión
        no tiene estimaciones, las calcula su herramienta (S10). Si eso falla, lo dirá
        ``construir_candidatos`` con su propio error.
        """
        ctx.state[CLAVE_CANDIDATOS] = []
        ctx.state[CLAVE_VALIDACIONES] = []
        recien_estimado.clear()
        try:
            recien_estimado.append(nucleo.asegurar_estimaciones(ctx.state))
        except ERRORES_DE_DOMINIO:
            recien_estimado.append(False)

    def aviso_estimaciones(ctx: ToolContext) -> dict[str, Any]:
        return {"estimaciones": AVISO_ESTIMACIONES} if any(recien_estimado) else {}

    construir = exploratorio(
        nucleo.construir_candidatos, antes=nueva_propuesta, anexo=aviso_estimaciones
    )
    especialistas = [
        *crear_gestor_fintual(config, gestor),
        FunctionTool(construir),
        FunctionTool(nucleo.ajustar_restricciones),
        *comite.function_tools(),
    ]
    sub_agentes: list[BaseAgent] = [
        crear_market_analyst(config, provider, modelo, mode="single_turn"),
        crear_estadistico(config, nucleo, modelo),
        crear_esceptico(config, nucleo, modelo),
    ]
    # El roster sale de lo que de verdad se cablea aquí, no de una lista escrita aparte.
    # Las personas traen su propia herramienta: también tiene silla en la sala.
    de_personas = [t.name for a in sub_agentes for t in getattr(a, "tools", [])]
    sala = componer_sala(
        [TOOL_MESA, *(t.name for t in especialistas), *de_personas],
        [a.name for a in sub_agentes],
    )

    voces = {a.name: ATIENDE[a.name].value for a in sub_agentes if isinstance(a, LlmAgent)}

    def despues_de_herramienta(
        tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, tool_response: Any
    ) -> dict[str, Any] | None:
        """De una persona llega su TEXTO (con la regla de no re-narrarlo); del resto, anexos."""
        if tool.name in voces:
            return resultado_para_el_director(voces[tool.name], tool_response)
        return recoger_anexos(tool, args, tool_context, tool_response)

    def instruccion(contexto: ReadonlyContext) -> str:
        cableado = CABLEADO.format(
            estado_sesion=_estado_sesion(contexto.state),
            disclaimer=DISCLAIMER,
            cableado_gestor=CABLEADO_GESTOR,
        )
        return f"{INSTRUCCION}\n\n{cableado}"

    def cargar_universo(callback_context: CallbackContext) -> None:
        """El universo es estado de la SESIÓN: al primer turno se adopta el vigente del Gestor."""
        if callback_context.state.get(CLAVE_UNIVERSO) is not None:
            return
        try:
            callback_context.state[CLAVE_UNIVERSO] = volcar(gestor.universo())
            callback_context.state[CLAVE_ERROR_UNIVERSO] = None
        except GestorError as exc:
            callback_context.state[CLAVE_ERROR_UNIVERSO] = str(exc)

    return LlmAgent(
        name=NOMBRE,
        description="Director de Análisis: conversa, clasifica la intención y rutea.",
        model=resolver_modelo(config, NOMBRE, modelo),
        instruction=instruccion,
        before_agent_callback=cargar_universo,
        before_tool_callback=entregar_pesos,
        after_tool_callback=despues_de_herramienta,
        after_model_callback=anexar_al_cierre,
        before_model_callback=ocultar_anexos_al_modelo,
        tools=[*MesaTools(gestor, config, sala).function_tools(), *especialistas],
        sub_agents=sub_agentes,
        generate_content_config=types.GenerateContentConfig(
            temperature=config.agentes.temperatura,
            seed=config.reproducibilidad.semilla,
        ),
    )
