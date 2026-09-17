"""Analista de Mercados: un ``LlmAgent`` que opina y un envoltorio que exige el contrato.

El LLM emite un ``MarketViewsBorrador``; el envoltorio lo convierte a ``MarketViews`` con la
fecha de decisión y el universo de la corrida. Si algo no valida (JSON, esquema o contrato)
guarda el error en el estado y vuelve a ejecutar el LLM, que lo recibe en su instrucción.
Agotados los intentos lanza ``ViewsInvalidasError``: sin views válidas no hay corrida.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date
from typing import Any

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.models.base_llm import BaseLlm
from google.genai import types
from pydantic import ValidationError

from investmentsys.agents.market_analyst.borrador import MarketViewsBorrador
from investmentsys.config import Config
from investmentsys.contracts import DISCLAIMER, MarketViews
from investmentsys.data import PriceProvider
from investmentsys.tools.estado import CLAVE_FECHA_DECISION, CLAVE_MARKET_VIEWS, volcar

CLAVE_BORRADOR = "market_views_borrador"
CLAVE_ERROR_VIEWS = "market_views_error"
NOMBRE = "market_analyst"

INSTRUCCION = """\
Eres el Analista de Mercados de un sistema de construcción de portafolios.
Tu salida alimenta un modelo Black-Litterman: cada view es una fila de la matriz P con su Q.

Universo (usa exactamente estos tickers): {activos}
Fecha de decisión: {fecha_decision}. Horizonte de las views: {horizonte_meses} meses.

Reglas:
- Emite entre 0 y 4 views. Si no tienes convicción sobre un activo, no opines sobre él.
- View absoluta: un solo activo con coeficiente 1.0; q_anual es su retorno TOTAL anual.
- View relativa: al menos dos activos, coeficientes que suman 0 (largo positivo, corto
  negativo); q_anual es el diferencial anual esperado.
- q_anual y confianza son fracciones (0.03 = 3 %). Sé sobrio: retornos plausibles.
- No uses información posterior a la fecha de decisión; fecha_fuente nunca la supera.
- No tienes herramientas de búsqueda: en `fuente` no inventes URLs. Cita un dato público
  que recuerdes con su emisor, o escribe "conocimiento general del modelo, sin verificar".
- No calcules pesos ni métricas de cartera: eso lo hacen otras etapas.
{correccion}"""

CORRECCION = """
Tu intento anterior NO validó contra el contrato MarketViews. Error:
{error}
Corrige exactamente eso y responde de nuevo con el JSON completo."""


class ViewsInvalidasError(RuntimeError):
    """El analista agotó sus intentos sin producir un ``MarketViews`` válido."""


def _instruccion(config: Config, fecha: date, error: str | None) -> str:
    return INSTRUCCION.format(
        activos=", ".join(config.portafolio.activos),
        fecha_decision=fecha.isoformat(),
        horizonte_meses=config.agentes.horizonte_views_meses,
        correccion=CORRECCION.format(error=error) if error else "",
    )


def _evento(ctx: InvocationContext, autor: str, texto: str, delta: dict[str, Any]) -> Event:
    return Event(
        author=autor,
        invocation_id=ctx.invocation_id,
        branch=ctx.branch,
        content=types.Content(role="model", parts=[types.Part(text=texto)]),
        actions=EventActions(state_delta=delta),
    )


def _resumen(views: MarketViews, intento: int) -> str:
    lineas = [
        f"MarketViews válido en el intento {intento} (fecha de decisión {views.fecha_decision}, "
        f"horizonte {views.horizonte_meses} meses).",
        "",
        views.resumen,
        "",
    ]
    for v in views.views:
        lineas.append(
            f"- {v.tipo.value} {v.coeficientes}: q={v.q_anual:+.1%}, "
            f"confianza {v.confianza:.0%}. {v.justificacion} (fuente: {v.fuente})"
        )
    if not views.views:
        lineas.append("- Sin views: el posterior será el equilibrio de mercado.")
    return "\n".join([*lineas, "", DISCLAIMER])


class MarketAnalyst(BaseAgent):
    """Ejecuta ``llm`` hasta que su salida valide contra ``MarketViews``."""

    llm: LlmAgent
    activos: tuple[str, ...]
    horizonte_meses: int
    max_intentos: int
    fecha_por_defecto: date

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        estado = ctx.session.state
        fecha_cruda = estado.get(CLAVE_FECHA_DECISION)
        fecha = date.fromisoformat(fecha_cruda) if fecha_cruda else self.fecha_por_defecto
        yield _evento(
            ctx,
            self.name,
            f"Analizando {', '.join(self.activos)} con fecha de decisión {fecha}.",
            {CLAVE_FECHA_DECISION: fecha.isoformat(), CLAVE_ERROR_VIEWS: None},
        )
        error = ""
        for intento in range(1, self.max_intentos + 1):
            views: MarketViews | None = None
            try:
                # Del LLM solo se reintenta lo que ADK lanza al validar su JSON contra el
                # borrador; un fallo de credenciales, cuota o red no es una salida inválida.
                async for evento in self.llm.run_async(ctx):
                    yield evento
            except ValidationError as exc:
                error = str(exc)
            else:
                try:
                    borrador = MarketViewsBorrador.model_validate(estado.get(CLAVE_BORRADOR))
                    views = borrador.a_contrato(fecha, self.activos, self.horizonte_meses)
                except ValueError as exc:  # ValidationError del contrato incluido
                    error = str(exc)
            if views is None:
                yield _evento(
                    ctx,
                    self.name,
                    f"Intento {intento}/{self.max_intentos}: la salida no valida contra "
                    f"MarketViews.\n{error}",
                    {CLAVE_ERROR_VIEWS: error, CLAVE_BORRADOR: None},
                )
                continue
            yield _evento(
                ctx,
                self.name,
                _resumen(views, intento),
                {CLAVE_MARKET_VIEWS: volcar(views), CLAVE_ERROR_VIEWS: None},
            )
            return
        raise ViewsInvalidasError(
            f"{self.max_intentos} intentos sin un MarketViews válido; último error: {error}"
        )


def crear_market_analyst(
    config: Config, provider: PriceProvider, modelo: str | BaseLlm | None = None
) -> MarketAnalyst:
    """``modelo`` permite inyectar un LLM falso en tests; por defecto, ``config.agentes``."""
    fecha_por_defecto: date = provider.precios(config.portafolio.activos).index[-1].date()

    def instruccion(contexto: ReadonlyContext) -> str:
        fecha_cruda = contexto.state.get(CLAVE_FECHA_DECISION)
        fecha = date.fromisoformat(fecha_cruda) if fecha_cruda else fecha_por_defecto
        return _instruccion(config, fecha, contexto.state.get(CLAVE_ERROR_VIEWS))

    llm = LlmAgent(
        name=f"{NOMBRE}_llm",
        description="Redacta views de mercado en formato Black-Litterman.",
        model=modelo if modelo is not None else config.agentes.modelo,
        instruction=instruccion,
        output_schema=MarketViewsBorrador,
        output_key=CLAVE_BORRADOR,
        generate_content_config=types.GenerateContentConfig(
            temperature=config.agentes.temperatura,
            seed=config.reproducibilidad.semilla,
        ),
    )
    return MarketAnalyst(
        name=NOMBRE,
        description="Analista de Mercados: produce MarketViews validadas contra el contrato.",
        llm=llm,
        sub_agents=[llm],
        activos=config.portafolio.activos,
        horizonte_meses=config.agentes.horizonte_views_meses,
        max_intentos=config.agentes.max_intentos_analista,
        fecha_por_defecto=fecha_por_defecto,
    )
