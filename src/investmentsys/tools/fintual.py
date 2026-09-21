"""``gestionar_datos_y_fricciones``: la ÚNICA tool del Gestor de Datos y Fintual (S10, ADR-020).

El Gestor es transaccional y no tiene persona: no hay un LLM entre el Director y esta tool. Las
operaciones heredadas son las de ``GestorTools`` (mismo código, mismas custodias: sello,
obsoletos, prior neutral en dos turnos); las nuevas son de solo lectura. Un argumento que no
corresponde a la operación se RECHAZA: una firma única no puede tipar por operación, así que lo
custodia el código. ``montos`` no recibe cifras: la cartera objetivo sale de la mesa y la
cartera actual de ``config.yaml``. S11 añade ``plan_compra`` y ``forzar_orden``
(``tools/plan_operativo.py``, ADR-022).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, get_args

from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

from investmentsys.config import Config
from investmentsys.contracts import DISCLAIMER_OPERATIVO, OrdenInercia, PlanInercia, Universe
from investmentsys.data_manager import GestorDatos, GestorError
from investmentsys.fintual import plan_inercia
from investmentsys.tools.estado import (
    CLAVE_UNIVERSO,
    FaltaEnEstadoError,
    ResultadoObsoletoError,
    leer,
)
from investmentsys.tools.gestor import ERRORES_DEL_GESTOR, GestorTools, _error
from investmentsys.tools.objetivo import cartera_objetivo
from investmentsys.tools.plan_operativo import (
    FlujoSinProcedenciaError,
    OverrideRechazadoError,
    PlanOperativoTools,
)

ERRORES_DE_LECTURA = (*ERRORES_DEL_GESTOR, FaltaEnEstadoError, ResultadoObsoletoError, LookupError)
NOMBRE_TOOL = "gestionar_datos_y_fricciones"
ETIQUETA_OPERATIVA = "estimacion_operativa"

Operacion = Literal[
    "resolver",
    "incorporar",
    "retirar",
    "refrescar_cap",
    "aceptar_prior_neutral",
    "cargar_guardado",
    "diagnosticar",
    "dividendos",
    "cierres",
    "montos",
    "plan_compra",
    "forzar_orden",
]
OPERACIONES: tuple[str, ...] = get_args(Operacion)

# operación → (argumentos obligatorios, argumentos opcionales). Lo demás se rechaza.
ARGUMENTOS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # S-lienzo (ADR-023): `ticker` O `tickers` (una lista); se exige exactamente uno.
    "resolver": ((), ("ticker", "tickers")),
    "incorporar": ((), ("ticker", "tickers", "prior_cap", "prior_metodologia")),
    "retirar": (("ticker",), ()),
    "refrescar_cap": (("ticker",), ("prior_cap", "prior_metodologia")),
    "aceptar_prior_neutral": ((), ()),
    "cargar_guardado": ((), ()),
    "diagnosticar": ((), ()),
    "dividendos": ((), ("ticker",)),
    "cierres": ((), ("ticker",)),
    "montos": ((), ()),
    "plan_compra": (("aporte_usd",), ("dividendos_usd",)),
    "forzar_orden": (("escenario", "token"), ()),
}

NOTA_DIVIDENDOS = (
    "Solo HISTORIA: la fuente no publica el calendario futuro de dividendos. No proyectes la "
    "próxima fecha ex-dividendo ni su monto."
)
NOTA_CIERRES = (
    "El cierre ajustado descuenta splits y dividendos hacia atrás: es el que usan las "
    "estimaciones. La diferencia con el cierre crudo no es un error."
)
NOTA_MONTOS = (
    "Dentro de su banda de inercia la orden de un activo es HOLD obligatorio. FUERA_DE_BANDA "
    "solo SEÑALA que el peso actual se alejó del objetivo más que la banda (sobreponderado o "
    "subponderado): NO es una orden. No le digas al usuario que compre ni que venda nada, ni "
    "cuánto, a partir de esta comparación: una desviación se corrige con flujos nuevos, sin "
    "ventas, y eso lo calcula operacion='plan_compra' cuando el usuario trae un aporte. Los montos "
    "objetivo son la cartera objetivo expresada en US$ sobre el valor de cartera de config.yaml."
)
SIN_ORDEN = "ninguna: solo se señala la desviación; no indiques comprar ni vender"
HOLD_OBLIGATORIO = "HOLD obligatorio: dentro de banda no se opera"


def _situacion(desviacion: float, en_banda: bool) -> str:
    if en_banda:
        return "en banda"
    return "sobreponderado" if desviacion > 0 else "subponderado"


def _activos_pedidos(universo: Universe, ticker: str | None) -> tuple[str, ...]:
    """Todo el universo o solo ``ticker``: ningún dato de un activo que el Gestor no validó."""
    if not ticker:
        return universo.activos
    pedido = ticker.strip().upper()
    if pedido not in universo.activos:
        raise GestorError(
            f"{pedido} no está en el universo vigente ({', '.join(universo.activos)}): "
            "incorpóralo antes de pedir sus datos"
        )
    return (pedido,)


def _rechazo(tipo: str, motivo: str) -> dict[str, Any]:
    return {"status": "rechazado", "tipo": tipo, "motivo": motivo}


def resumir_plan(plan: PlanInercia) -> dict[str, Any]:
    return {
        "validado": plan.validado,
        "etiqueta": ETIQUETA_OPERATIVA,
        "universe_version": plan.universe_version,
        "cartera_objetivo": plan.origen_objetivo,
        "valor_cartera_usd": plan.valor_cartera_usd,
        "orden_global": plan.orden_global.value,
        "fuera_de_banda": [d.activo for d in plan.decisiones if d.orden is not OrdenInercia.HOLD],
        "por_activo": {
            d.activo: {
                "orden": d.orden.value,
                "situacion": _situacion(d.desviacion, d.orden is OrdenInercia.HOLD),
                "accion": HOLD_OBLIGATORIO if d.orden is OrdenInercia.HOLD else SIN_ORDEN,
                "peso_objetivo": d.peso_objetivo,
                "peso_actual": d.peso_actual,
                "desviacion": d.desviacion,
                "banda": d.banda,
                "monto_objetivo_usd": d.monto_objetivo_usd,
                "monto_actual_usd": d.monto_actual_usd,
            }
            for d in plan.decisiones
        },
        "nota": NOTA_MONTOS,
        "disclaimer": DISCLAIMER_OPERATIVO,
    }


@dataclass(frozen=True)
class GestorFintualTools:
    gestor: GestorDatos
    config: Config
    operativo: PlanOperativoTools | None = None  # por defecto, el de ``config``

    def gestionar_datos_y_fricciones(
        self,
        operacion: Operacion,
        tool_context: ToolContext,
        ticker: str | None = None,
        tickers: list[str] | None = None,
        prior_cap: float | None = None,
        prior_metodologia: str | None = None,
        aporte_usd: float | None = None,
        dividendos_usd: float | None = None,
        escenario: str | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        """Gestor de Datos y Fintual: universo de trabajo, datos de mercado y fricciones.

        Operaciones que NO modifican nada:
        - "resolver" (ticker | tickers): diagnostica un ticker contra la fuente: desde cuándo hay
          datos, qué limita una historia corta, si es apto y el bloque ``prior`` (``tiene_cap``).
          Con ``tickers`` (una lista) diagnostica todos y añade ``si_entran_todos``: la ventana
          común que tendría el universo y quién la limita.
        - "diagnosticar": detalle del universo vigente (capitalizaciones, ventana común,
          cobertura de los stress, advertencias por activo).
        - "dividendos" (ticker?): fechas ex-dividendo recientes y monto por acción; de todo el
          universo o, con ticker, solo de ese activo del universo.
        - "cierres" (ticker?): último cierre y cierre ajustado, con su fecha; ídem.
        - "montos": la cartera objetivo que está sobre la mesa traducida a montos en US$ (2
          decimales) y comparada con la cartera actual bajo las bandas de inercia (No-Trade
          Zones): HOLD obligatorio dentro de banda. No lleva argumentos: los pesos NO se pasan.
        - "plan_compra" (aporte_usd, dividendos_usd?): el usuario trae dinero nuevo (un aporte,
          dividendos acreditados). Devuelve el Plan de Compra Neta: el flujo va 100 % a los
          activos bajo su objetivo, en US$ fraccionados, CERO ventas, con las bandas de inercia
          antes y después y el filtro tributario CONSULTIVO (escenarios con su «Costo fiscal
          estimado» en CLP). No ejecuta nada: es el plan que el usuario ejecuta en la app.
        Operación que REGISTRA una decisión del usuario:
        - "forzar_orden" (escenario, token): el Override. Solo si el usuario, tras VER el plan
          y la advertencia del escenario, pide explícitamente forzarlo. En un turno posterior
          al del plan, con el id del escenario y el token de ese plan. Queda en el acta
          operativa con la advertencia que cruzó. Nunca la llames por iniciativa propia.
        Operaciones que CAMBIAN el universo (otra ``universe_version``; la respuesta lista en
        ``resultados_obsoletos`` lo que dejó de valer):
        - "cargar_guardado": carga en la sesión el universo GUARDADO del Gestor, con sus
          diagnósticos. SOLO si el usuario lo pide («usa el guardado», «partamos de mi lista
          guardada»). Con la mesa limpia es la única vía para trabajar sobre él.
        - "incorporar" (ticker | tickers, prior_cap?, prior_metodologia?): alta de un activo. Con
          ``tickers`` (una lista), alta en lote: entran los que no requieren una decisión del
          usuario; los que no tienen capitalización en la fuente quedan en
          ``pendientes_de_prior`` con la pregunta que debes hacer. Con la mesa limpia, la primera
          alta crea el universo de ESTA sesión solo con esos activos (no toca el guardado).
        - "retirar" (ticker): saca un activo; su serie se conserva en disco.
        - "refrescar_cap" (ticker, prior_cap?, prior_metodologia?): única vía para cambiar una
          capitalización congelada; sin prior_cap la toma de la fuente.
        - "aceptar_prior_neutral": degrada el prior de TODO el universo a equal-weight. Custodia
          por turnos: la primera llamada NO degrada, devuelve la advertencia; solo una llamada
          en un turno POSTERIOR del usuario ejecuta.

        Args:
            operacion: una de las de arriba.
            ticker: símbolo del activo, p. ej. "NVDA". Solo en las operaciones que lo indican.
            tickers: lista de símbolos que ESCRIBIÓ el usuario, para resolver o incorporar varios
                a la vez. Nunca la completes ni añadas activos que él no nombró.
            prior_cap: capitalización que APORTA EL USUARIO, en US$ billones (10^12). Nunca la
                estimes tú.
            prior_metodologia: obligatoria con prior_cap: de dónde sale, en palabras del usuario.
            aporte_usd: monto en US$ que el usuario ESCRIBIÓ como aporte nuevo. Nunca lo estimes.
            dividendos_usd: ídem, dividendos en US$ ya acreditados que el usuario informa.
            escenario: id de un escenario fiscal del plan, p. ej. "VOOG:vender_hasta_banda".
            token: el que devolvió "plan_compra".
        """
        if operacion not in ARGUMENTOS:
            return _rechazo(
                "OperacionDesconocida", f"operacion '{operacion}' no existe: {list(OPERACIONES)}"
            )
        dados = {
            "ticker": ticker,
            "tickers": tickers or None,
            "prior_cap": prior_cap,
            "prior_metodologia": prior_metodologia,
            "aporte_usd": aporte_usd,
            "dividendos_usd": dividendos_usd,
            "escenario": escenario,
            "token": token,
        }
        obligatorios, opcionales = ARGUMENTOS[operacion]
        faltan = [a for a in obligatorios if dados[a] in (None, "")]
        if "tickers" in opcionales and not dados["ticker"] and not dados["tickers"]:
            faltan = ["ticker"]  # o `tickers`, para una lista
        sobran = [
            a for a, v in dados.items() if v is not None and a not in (*obligatorios, *opcionales)
        ]
        if dados["tickers"] and "tickers" in opcionales:
            # La cap es de UN activo: en lote cada pendiente se resuelve después, por separado.
            sobran += [a for a in ("ticker", "prior_cap", "prior_metodologia") if dados[a]]
        if faltan or sobran:
            return {
                "operacion": operacion,
                **_rechazo(
                    "ArgumentosNoCorresponden",
                    f"operacion '{operacion}': faltan {faltan}, no admite {sobran}. No se "
                    "ejecutó nada",
                ),
            }
        return {"operacion": operacion, **self._despachar(operacion, tool_context, dados)}

    def _despachar(self, operacion: str, ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        heredadas = GestorTools(self.gestor)
        ticker = args["ticker"]
        cap, metodologia = args["prior_cap"], args["prior_metodologia"]
        lista = args["tickers"]
        if operacion == "resolver":
            return heredadas.resolver_lista(lista) if lista else heredadas.resolver(ticker)
        if operacion == "incorporar" and lista:
            return heredadas.incorporar_lista(lista, ctx)
        if operacion == "incorporar":
            return heredadas.incorporar(ticker, ctx, cap, metodologia)
        if operacion == "cargar_guardado":
            return heredadas.cargar_guardado(ctx)
        if operacion == "retirar":
            return heredadas.retirar(ticker, ctx)
        if operacion == "refrescar_cap":
            return heredadas.refrescar_cap(ticker, ctx, cap, metodologia)
        if operacion == "aceptar_prior_neutral":
            return heredadas.aceptar_prior_neutral(ctx)
        if operacion == "diagnosticar":
            return heredadas.diagnosticar(ctx)
        try:
            universo = leer(ctx.state, CLAVE_UNIVERSO, Universe)
            if operacion in ("dividendos", "cierres"):
                activos = _activos_pedidos(universo, ticker)
                lectura = self._dividendos if operacion == "dividendos" else self._cierres
                return lectura(universo, activos)
            if operacion == "montos":
                return self._montos(ctx)
            operativo = self.operativo or PlanOperativoTools(self.config)
            if operacion == "plan_compra":
                return operativo.plan_compra(ctx, args["aporte_usd"], args["dividendos_usd"])
            return operativo.forzar_orden(ctx, args["escenario"], args["token"])
        except (OverrideRechazadoError, FlujoSinProcedenciaError) as exc:
            return _rechazo(type(exc).__name__, str(exc))
        except (
            *ERRORES_DEL_GESTOR,
            FaltaEnEstadoError,
            ResultadoObsoletoError,
            LookupError,
            ValueError,
        ) as exc:
            return _error(exc)

    def _dividendos(self, universo: Universe, activos: tuple[str, ...]) -> dict[str, Any]:
        pagos = self.gestor.dividendos(universo, activos)
        return {
            "status": "success",
            "universe_version": universo.version,
            "dias_de_historia": self.config.fintual.dias_historia_dividendos,
            "ex_dividendos": {
                a: [
                    {
                        "fecha_ex": d.fecha_ex.isoformat(),
                        "monto_usd_por_accion": d.monto_usd_por_accion,
                    }
                    for d in lista
                ]
                for a, lista in pagos.items()
            },
            "sin_dividendos_en_el_periodo": [a for a, lista in pagos.items() if not lista],
            "nota": NOTA_DIVIDENDOS,
            "disclaimer": DISCLAIMER_OPERATIVO,
        }

    def _cierres(self, universo: Universe, activos: tuple[str, ...]) -> dict[str, Any]:
        cierres = self.gestor.cierres(universo, activos)
        return {
            "status": "success",
            "universe_version": universo.version,
            "cierres": {
                a: None
                if c is None
                else {
                    "fecha": c.fecha.isoformat(),
                    "cierre": c.cierre,
                    "cierre_ajustado": c.cierre_ajustado,
                }
                for a, c in cierres.items()
            },
            "sin_cierre_reciente": [a for a, c in cierres.items() if c is None],
            "nota": NOTA_CIERRES,
        }

    def _montos(self, ctx: ToolContext) -> dict[str, Any]:
        objetivo = cartera_objetivo(ctx.state)
        cartera = self.config.portafolio
        plan = plan_inercia(
            objetivo.pesos,
            cartera.pesos_actuales,
            cartera.valor_usd,
            self.config.fintual,
            universe_version=objetivo.universe_version,
            validado=objetivo.validado,
            origen_objetivo=objetivo.origen,
        )
        return {"status": "success", **resumir_plan(plan)}

    def function_tools(self) -> list[FunctionTool]:
        return [FunctionTool(self.gestionar_datos_y_fricciones)]
