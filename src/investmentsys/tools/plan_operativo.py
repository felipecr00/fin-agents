"""Plan de Compra Neta y override fiscal del Gestor-Fintual (S11, ADR-022).

Dos operaciones de ``gestionar_datos_y_fricciones``:

- ``plan_compra`` (aporte_usd, dividendos_usd?): flujo nuevo → compras fraccionadas en US$ a los
  activos bajo objetivo, con las No-Trade Zones antes y después y el filtro tributario
  CONSULTIVO. El monto del flujo es lo único que llega por un argumento del LLM, y solo vale si
  el usuario lo ESCRIBIÓ (``procedencia``); la cartera objetivo sale de la mesa y la actual de
  ``config.yaml``. El bloque para el usuario —tabla, escenarios etiquetados, supuestos y
  disclaimer— lo redacta el código (ADR-017): el disclaimer no depende de la narración.
- ``forzar_orden`` (escenario, token): el Override. Custodia por turnos como el gate del comité
  (ADR-014): solo en un turno POSTERIOR al que presentó la advertencia, con el token de ese
  plan, una sola vez, y si nada de lo presentado cambió. El LLM pasa el ID del escenario, nunca
  un monto. Queda en el acta operativa con la advertencia que cruzó, literal.

El sistema nunca ejecuta: todo lo que sale de aquí es un plan que el usuario ejecuta en la app.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google.adk.tools.tool_context import ToolContext

from investmentsys.config import RAIZ_PROYECTO, Config
from investmentsys.contracts import (
    ActaOperativa,
    AsesoriaFiscal,
    BaseCosto,
    EscenarioFiscal,
    OrdenInercia,
    OverrideFiscal,
    PlanCompraNeta,
    RunState,
)
from investmentsys.fintual import (
    asesorar,
    montos_fraccionados,
    plan_compra_neta,
    plan_tras_override,
)
from investmentsys.tools.estado import CLAVE_RUN_STATE, volcar
from investmentsys.tools.ficha import CLAVE_ANEXO
from investmentsys.tools.objetivo import CarteraObjetivo, cartera_objetivo
from investmentsys.tools.procedencia import lo_escribio_el_usuario

CLAVE_PLAN_OPERATIVO = "plan_operativo"
CARPETA_OPERACIONES = "operaciones"
ETIQUETA_OPERATIVA = "estimacion_operativa"
NO_EJECUTA = (
    "El sistema no ejecuta órdenes: este plan lo ejecutas tú en la app de Fintual, si así lo "
    "decides."
)
NOTA_PLAN = (
    "El bloque del plan (tabla, escenarios, supuestos y disclaimer) se anexa solo: no lo copies. "
    "Las compras son la asignación del flujo nuevo; NO propongas ventas: el plan por defecto no "
    "vende. Los escenarios con venta son INFORMACIÓN con su costo fiscal estimado, no "
    "recomendaciones ni prohibiciones; una venta con pérdida es tax-loss harvesting, estrategia "
    "legítima. Solo si el usuario pide EXPLÍCITAMENTE forzar un escenario pese a su advertencia, "
    "y en un turno posterior a este, llama a operacion='forzar_orden' con el id del escenario y "
    "este token. No es asesoría tributaria ni financiera."
)


class OverrideRechazadoError(ValueError):
    """``forzar_orden`` fuera de la secuencia: nada se registró."""


class FlujoSinProcedenciaError(ValueError):
    """El monto del flujo no lo escribió el usuario."""


# ----------------------------------------------------------------------------- redacción
def _usd(monto: float) -> str:
    return f"US$ {monto:.2f}"


def _clp(monto: float) -> str:
    return f"${round(monto):,} CLP".replace(",", ".")


def _pp(fraccion: float) -> str:
    return f"{fraccion * 100:.1f} %"


def _zona(plan: PlanCompraNeta, activo: str) -> str:
    d = next(x for x in plan.inercia_despues.decisiones if x.activo == activo)
    if d.orden is OrdenInercia.HOLD:
        return "en banda · HOLD"
    if d.desviacion > 0:
        return "sobreponderado, fuera de banda · no se vende"
    return "subponderado, fuera de banda · se corrige con flujos"


def _linea_escenario(n: int, e: EscenarioFiscal) -> str:
    if e.por_defecto:
        efecto = e.efecto[0].upper() + e.efecto[1:]  # no ``capitalize``: baja los tickers
        return f"{n}. **Por defecto — sin ventas.** {e.etiqueta}. {efecto}"
    cota = " (cota superior)" if e.base_costo is BaseCosto.COTA_SIN_COSTO else ""
    if e.cosecha_de_perdidas:
        fiscal = (
            f"**{e.etiqueta}** · pérdida realizable estimada {_clp(e.perdida_realizable_clp)} "
            "— tax-loss harvesting, estrategia legítima"
        )
    else:
        fiscal = f"**{e.etiqueta}**{cota} sobre una ganancia estimada de {_usd(e.resultado_usd)}"
    return f"{n}. `{e.id}` — vender {_usd(e.venta_usd)}: {fiscal}. {e.efecto}"


def renderizar_plan(plan: PlanCompraNeta, asesoria: AsesoriaFiscal) -> str:
    flujo = f"aporte {_usd(plan.aporte_usd)} + dividendos {_usd(plan.dividendos_usd)}"
    if plan.reinversion_usd:
        flujo += f" + producto de la venta forzada {_usd(plan.reinversion_usd)}"
    filas = [
        f"| {c.activo} | {f'**{c.monto_usd:.2f}**' if c.monto_usd else '—'} | "
        f"{_pp(c.peso_antes)} | {_pp(c.peso_despues)} | {_pp(c.peso_objetivo)} | "
        f"{_zona(plan, c.activo)} |"
        for c in plan.compras
    ]
    s = asesoria.supuestos
    declarados = ", ".join(s.costo_base_usd) or "ninguno (los costos fiscales son cotas)"
    lineas = [
        f"### Plan de Compra Neta — flujo de {_usd(plan.flujo_usd)}",
        "",
        f"Cartera objetivo: {plan.origen_objetivo} · universo `{plan.universe_version[:12]}` · "
        f"cartera antes del flujo {_usd(plan.valor_cartera_usd)}.",
        f"Flujo a asignar: {flujo}. Ventas del plan: {_usd(plan.ventas_usd)}. No-Trade Zones "
        "activas: nada dentro de su banda se rota, y lo sobreponderado no se vende.",
        "",
        "| Activo | Comprar (US$) | Peso antes | Peso después | Objetivo | Zona tras el flujo |",
        "|---|---:|---:|---:|---:|---|",
        *filas,
        "",
        "#### Filtro tributario consultivo (informa, no prohíbe)",
        *(_linea_escenario(n, e) for n, e in enumerate(asesoria.escenarios, start=1)),
    ]
    if asesoria.perdidas_latentes:
        latentes = "; ".join(
            f"{p.activo} {_usd(p.perdida_latente_usd)} ({_clp(p.perdida_latente_clp)})"
            for p in asesoria.perdidas_latentes
        )
        lineas += [
            "",
            f"Pérdidas latentes: {latentes}. Realizarlas para compensar ganancias (tax-loss "
            "harvesting) es una estrategia legítima; evalúala con tu contador.",
        ]
    lineas += [
        "",
        f"Supuestos TUYOS (`config.yaml`): tramo marginal {_pp(s.tasa_marginal)}, USD/CLP "
        f"{s.usd_clp:.0f}, costo de adquisición declarado: {declarados}.",
        "Para forzar un escenario con venta pese a su advertencia, pídelo explícitamente: queda "
        "registrado en el acta operativa junto con la advertencia que cruzas.",
        NO_EJECUTA,
        "",
        f"> {plan.disclaimer}",
    ]
    return "\n".join(lineas)


def renderizar_override(override: OverrideFiscal, archivo: Path | None) -> str:
    e = override.escenario
    donde = f"`{archivo}`" if archivo else "el estado de la sesión (disco no escribible)"
    resultante = override.plan_resultante
    compras = ", ".join(
        f"{c.activo} {_usd(c.monto_usd)}" for c in resultante.compras if c.monto_usd
    )
    return "\n".join(
        [
            f"### Override registrado — `{e.id}`",
            "",
            f"Orden forzada por el usuario: vender {_usd(e.venta_usd)} de {e.activo}. "
            f"**{e.etiqueta}**.",
            f"Reasignación del flujo total ({_usd(resultante.flujo_usd)}): {compras}.",
            "",
            "Advertencia que cruzaste (consta literal en el acta):",
            f"> {override.advertencia_cruzada}",
            "",
            f"Acta operativa: {donde}. {NO_EJECUTA}",
            "",
            f"> {resultante.disclaimer}",
        ]
    )


# -------------------------------------------------------------------------- operaciones
@dataclass(frozen=True)
class PlanOperativoTools:
    config: Config
    directorio_runs: Path | None = None
    reloj: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    nuevo_token: Callable[[], str] = field(default=lambda: uuid.uuid4().hex)

    def _plan(
        self, objetivo: CarteraObjetivo, aporte: float, dividendos: float
    ) -> tuple[PlanCompraNeta, AsesoriaFiscal]:
        cartera, fintual = self.config.portafolio, self.config.fintual
        tenencias = montos_fraccionados(
            cartera.pesos_actuales, cartera.valor_usd, fintual.decimales_usd
        )
        plan = plan_compra_neta(
            objetivo.pesos,
            tenencias,
            fintual,
            aporte_usd=aporte,
            dividendos_usd=dividendos,
            universe_version=objetivo.universe_version,
            validado=objetivo.validado,
            origen_objetivo=objetivo.origen,
        )
        return plan, asesorar(plan, fintual)

    def _archivo(self, acta: ActaOperativa) -> Path:
        runs = self.directorio_runs or RAIZ_PROYECTO / self.config.corridas.directorio
        carpeta = runs / acta.run_id_comite if acta.run_id_comite else runs / CARPETA_OPERACIONES
        return carpeta / f"acta_operativa_{acta.id}.json"

    def _persistir(self, acta: ActaOperativa) -> Path | None:
        archivo = self._archivo(acta)
        try:
            archivo.parent.mkdir(parents=True, exist_ok=True)
            archivo.write_text(acta.model_dump_json(indent=2), encoding="utf-8")
        except OSError:  # contenedor de solo lectura: el acta queda en la sesión
            return None
        return archivo

    def plan_compra(
        self, ctx: ToolContext, aporte_usd: float, dividendos_usd: float | None
    ) -> dict[str, Any]:
        for nombre, monto in (("aporte_usd", aporte_usd), ("dividendos_usd", dividendos_usd)):
            if monto and not lo_escribio_el_usuario(monto, ctx):
                raise FlujoSinProcedenciaError(
                    f"{nombre}={monto}: ese monto no lo escribió el usuario. Pídele el monto del "
                    "flujo en números y pásalo tal cual; nunca lo estimes ni lo completes"
                )
        objetivo = cartera_objetivo(ctx.state)
        plan, asesoria = self._plan(objetivo, aporte_usd, dividendos_usd or 0.0)
        ahora = self.reloj()
        crudo = ctx.state.get(CLAVE_RUN_STATE)
        acta = ActaOperativa(
            id=ahora.strftime("%Y%m%dT%H%M%S_%fZ"),
            creado_en=ahora,
            run_id_comite=RunState.model_validate(crudo).run_id if objetivo.validado else None,
            plan=plan,
            asesoria=asesoria,
        )
        archivo = self._persistir(acta)
        token = self.nuevo_token()
        ctx.state[CLAVE_PLAN_OPERATIVO] = {
            "acta": volcar(acta),
            "token": token,
            "invocacion": ctx.invocation_id,
            "objetivo": dict(objetivo.pesos),
        }
        return {
            "status": "success",
            "etiqueta": ETIQUETA_OPERATIVA,
            "validado": plan.validado,
            "universe_version": plan.universe_version,
            "cartera_objetivo": plan.origen_objetivo,
            "flujo_usd": plan.flujo_usd,
            "ventas_usd": plan.ventas_usd,
            "compras_usd": {c.activo: c.monto_usd for c in plan.compras if c.monto_usd},
            "sin_compra": [c.activo for c in plan.compras if not c.monto_usd],
            "fuera_de_banda_tras_el_flujo": [
                d.activo
                for d in plan.inercia_despues.decisiones
                if d.orden is not OrdenInercia.HOLD
            ],
            "escenarios_fiscales": [
                {
                    "id": e.id,
                    "por_defecto": e.por_defecto,
                    "venta_usd": e.venta_usd,
                    "etiqueta": e.etiqueta,
                    "tax_loss_harvesting": e.cosecha_de_perdidas,
                    "advertencia": e.advertencia,
                }
                for e in asesoria.escenarios
            ],
            "perdidas_latentes_usd": {
                p.activo: p.perdida_latente_usd for p in asesoria.perdidas_latentes
            },
            "token": token,
            "acta_operativa": str(archivo) if archivo else None,
            "nota": NOTA_PLAN,
            "disclaimer": plan.disclaimer,
            CLAVE_ANEXO: renderizar_plan(plan, asesoria),
        }

    def forzar_orden(self, ctx: ToolContext, escenario: str, token: str) -> dict[str, Any]:
        guardado = ctx.state.get(CLAVE_PLAN_OPERATIVO)
        if not guardado or token != guardado["token"]:
            raise OverrideRechazadoError(
                "no hay un plan vigente con ese token (o ya se usó): genera el plan con "
                "operacion='plan_compra', preséntalo con sus advertencias y espera al usuario"
            )
        if ctx.invocation_id == guardado["invocacion"]:
            raise OverrideRechazadoError(
                "la advertencia se presentó en este mismo turno: el usuario aún no la ha visto. "
                "Preséntale el plan y espera su respuesta; el token sigue vigente"
            )
        acta = ActaOperativa.model_validate(guardado["acta"])
        try:
            elegido = acta.asesoria.escenario(escenario)
        except KeyError:
            ids = [e.id for e in acta.asesoria.escenarios if not e.por_defecto]
            raise OverrideRechazadoError(
                f"'{escenario}' no es un escenario de este plan: {ids}"
            ) from None
        if elegido.advertencia is None:
            raise OverrideRechazadoError(
                "'sin ventas' ya es el plan por defecto: no hay advertencia que cruzar"
            )
        vigente = cartera_objetivo(ctx.state)
        if (
            vigente.universe_version != acta.plan.universe_version
            or dict(vigente.pesos) != guardado["objetivo"]
        ):
            ctx.state[CLAVE_PLAN_OPERATIVO] = None
            raise OverrideRechazadoError(
                "la cartera objetivo o el universo cambiaron desde que se presentó el plan: lo "
                "que el usuario vio ya no es lo que se forzaría. Vuelve a operacion='plan_compra'"
            )
        ctx.state[CLAVE_PLAN_OPERATIVO] = None  # un solo uso
        override = OverrideFiscal(
            escenario=elegido,
            advertencia_cruzada=elegido.advertencia,
            plan_resultante=plan_tras_override(acta.plan, elegido, self.config.fintual),
            presentado_en=acta.creado_en,
            forzado_en=self.reloj(),
            invocacion_presentacion=guardado["invocacion"],
            invocacion_override=ctx.invocation_id,
        )
        archivo = self._persistir(acta.con_override(override))
        resultante = override.plan_resultante
        return {
            "status": "success",
            "etiqueta": ETIQUETA_OPERATIVA,
            "validado": resultante.validado,
            "universe_version": resultante.universe_version,
            "override_registrado": True,
            "escenario": elegido.id,
            "venta_forzada_usd": elegido.venta_usd,
            "costo_fiscal": elegido.etiqueta,
            "advertencia_cruzada": override.advertencia_cruzada,
            "flujo_usd": resultante.flujo_usd,
            "compras_usd": {c.activo: c.monto_usd for c in resultante.compras if c.monto_usd},
            "acta_operativa": str(archivo) if archivo else None,
            "nota": (
                "El override y la advertencia cruzada quedaron en el acta operativa; el bloque se "
                "anexa solo. " + NO_EJECUTA
            ),
            "disclaimer": resultante.disclaimer,
            CLAVE_ANEXO: renderizar_override(override, archivo),
        }
