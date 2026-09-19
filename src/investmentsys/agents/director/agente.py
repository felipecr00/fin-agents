"""Director de Análisis (S8): un ``LlmAgent`` que conversa, clasifica la intención y rutea.

No calcula nada. Su instrucción es el spec aprobado (``instruccion.py``, literal) más el
CABLEADO de abajo, que solo dice qué herramienta atiende qué y en qué orden. Las custodias no
viven en el prompt sino en las herramientas: sellado por ``universe_version`` (ADR-012), gate
del comité en dos fases y ``validado: false`` en todo resultado exploratorio (ADR-014).
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.base_llm import BaseLlm
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from investmentsys.agents.director.instruccion import INSTRUCCION
from investmentsys.agents.market_analyst import crear_market_analyst
from investmentsys.agents.market_analyst.agente import ETIQUETA_EXPLORATORIO
from investmentsys.agents.modelo import resolver_modelo
from investmentsys.config import Config
from investmentsys.contracts import DISCLAIMER, QuantEstimates
from investmentsys.data import PriceProvider
from investmentsys.data_manager import GestorDatos, GestorError
from investmentsys.orchestrator.comite import ComiteTools
from investmentsys.tools import (
    CLAVE_CANDIDATOS,
    CLAVE_QUANT_ESTIMATES,
    CLAVE_UNIVERSO,
    CLAVE_VALIDACIONES,
    NucleoTools,
)
from investmentsys.tools.estado import volcar
from investmentsys.tools.gestor import GestorTools

NOMBRE = "director"

CABLEADO = """\
Cableado de herramientas
Este bloque solo dice qué herramienta atiende a cada especialista y en qué orden usarlas. Los
modos y las reglas son los de arriba.

Estado de la sesión: {estado_sesion}

- GESTOR DE DATOS: `resolver(ticker)` diagnostica sin modificar nada; `incorporar` da de alta;
  `retirar(ticker)` saca un activo; `refrescar_cap` cambia una capitalización congelada;
  `aceptar_prior_neutral` degrada el prior de TODO el universo; `diagnosticar` describe el
  universo vigente. Presentar el universo aplica al INICIO de la sesión, no a cada consulta:
  llama a `diagnosticar` para esa presentación inicial, cuando pregunten por el universo o
  por la historia de un activo, o cuando haya cambiado; para lo demás, ve directo a la
  herramienta que atiende la consulta.
  Alta de un activo, siempre en este orden:
  1. `resolver(ticker)` y presenta el diagnóstico (desde cuándo hay datos y qué limita eso).
  2. Mira `prior.tiene_cap` en la respuesta. Si es true (la fuente expone la capitalización):
     tras confirmar, `incorporar(ticker)` e informa el valor congelado y su fecha. Si es false
     (ETF o activo sin capitalización en la fuente): haz UNA sola pregunta con estas opciones,
     en este orden: (a) [recomendada] el usuario aporta la capitalización del subyacente o del
     índice que replica → `incorporar(ticker, prior_cap, prior_metodologia)`; (b) usar el AUM
     como proxy débil → lo mismo, con prior_metodologia "AUM: proxy débil"; (c) degradar el
     universo COMPLETO a prior neutral → advierte que es todo-o-nada (afecta a todos los
     activos, no solo al nuevo) y del sesgo de equal-weight documentado en ADR-013. Si la
     elige: `incorporar(ticker)` y luego `aceptar_prior_neutral`, cuya primera llamada NO
     degrada: devuelve la advertencia. Preséntala y espera; solo si el usuario confirma en su
     siguiente mensaje, vuelve a llamarla. Nunca propongas tú el valor de una capitalización.
  3. Toda herramienta que cambia el universo devuelve `resultados_obsoletos`: decláralos al
     usuario tal como vienen, uno por uno.
- ESTADÍSTICO: `estimar_mercado` (volatilidades, retornos históricos con su intervalo y
  correlaciones por par).
- ANALISTA DE MERCADO: `market_analyst(request=...)`. En `request` va lo que dijo el usuario,
  citado; el material externo que haya pegado va citado y marcado como no verificado.
- CONSTRUCTOR DE CARTERAS: `construir_candidatos` (necesita estimaciones y views vigentes).
  Las restricciones de la sesión se cambian con `ajustar_restricciones`, solo con lo que pida
  el usuario; si el pedido es infactible la herramienta lo rechaza: explica su motivo, no
  busques tú otro valor que "funcione".
- ESCÉPTICO, fuera del comité: `diagnosticar_cartera(pesos)` para carteras que trae el
  usuario; devuelve un diagnóstico, nunca un veredicto. Los pesos van como fracciones, tal
  como los dio el usuario: no los completes ni los renormalices.
- COMITÉ FORMAL: solo con `convocar_comite`, en dos fases. `fase="solicitar"` devuelve el
  resumen de la corrida y un token: presenta el resumen completo y espera. Solo si el usuario
  confirma en su siguiente mensaje, `fase="ejecutar"` con ese token.
- Ofrece solo lo que una herramienta de esta lista puede hacer. No hay herramientas para
  ejecutar órdenes, predecir precios, vigilar el mercado o avisar de cambios, buscar noticias,
  ni leer cuentas de un broker: no las ofrezcas ni las insinúes.
- Una respuesta con `validado: false` es exploratoria: dilo al presentarla. Solo una corrida
  de `convocar_comite` con `validado: true` es una recomendación.
- Toda cifra que cites debe aparecer, idéntica, en la salida de una herramienta de esta
  conversación. Si no tienes la cifra, llama a la herramienta o di que no la tienes.
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


def exploratorio(
    tool: Callable[..., dict[str, Any]],
    antes: Callable[[ToolContext], None] | None = None,
    anexo: Callable[[ToolContext], dict[str, Any]] | None = None,
) -> Callable[..., dict[str, Any]]:
    """El mismo tool (nombre, firma y docstring), con ``validado: false`` EN EL DATO.

    ``NucleoTools`` no se modifica: fuera del comité sus salidas son exploratorias y lo dicen
    en el contrato de salida, no solo en el texto que redacte el Director (ADR-014).
    """

    @functools.wraps(tool)
    def envuelto(*args: Any, tool_context: ToolContext, **kwargs: Any) -> dict[str, Any]:
        if antes is not None:
            antes(tool_context)
        salida = tool(*args, tool_context=tool_context, **kwargs)
        if salida.get("status") != "success":
            return salida
        extra = anexo(tool_context) if anexo is not None else {}
        return {**salida, **extra, "etiqueta": ETIQUETA_EXPLORATORIO, "validado": False}

    return envuelto


def _correlaciones(ctx: ToolContext) -> dict[str, Any]:
    """Las correlaciones de las estimaciones recién guardadas, leídas del contrato.

    El resumen de ``estimar_mercado`` está pensado para el pipeline y no las trae; el Director
    las necesita para citarlas. No se calcula nada aquí: es ``MatrizCovarianza.correlacion``.
    """
    estimaciones = QuantEstimates.model_validate(ctx.state[CLAVE_QUANT_ESTIMATES])
    metodo, cov = next(iter(estimaciones.covarianzas.items()))
    activos = estimaciones.activos
    return {
        "correlaciones": {
            f"{a}-{b}": cov.correlacion(a, b)
            for i, a in enumerate(activos)
            for b in activos[i + 1 :]
        },
        "correlaciones_metodo": str(metodo),
    }


def _nueva_propuesta(ctx: ToolContext) -> None:
    """Fuera del comité no hay bucle Constructor ⇄ Validador: cada propuesta es la ronda 1."""
    ctx.state[CLAVE_CANDIDATOS] = []
    ctx.state[CLAVE_VALIDACIONES] = []


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

    def instruccion(contexto: ReadonlyContext) -> str:
        cableado = CABLEADO.format(
            estado_sesion=_estado_sesion(contexto.state), disclaimer=DISCLAIMER
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
        model=resolver_modelo(config.agentes, modelo),
        instruction=instruccion,
        before_agent_callback=cargar_universo,
        tools=[
            *GestorTools(gestor).function_tools(),
            FunctionTool(exploratorio(nucleo.estimar_mercado, anexo=_correlaciones)),
            FunctionTool(exploratorio(nucleo.construir_candidatos, antes=_nueva_propuesta)),
            FunctionTool(nucleo.ajustar_restricciones),
            FunctionTool(nucleo.diagnosticar_cartera),
            *comite.function_tools(),
        ],
        sub_agents=[crear_market_analyst(config, provider, modelo, mode="single_turn")],
        generate_content_config=types.GenerateContentConfig(
            temperature=config.agentes.temperatura,
            seed=config.reproducibilidad.semilla,
        ),
    )
