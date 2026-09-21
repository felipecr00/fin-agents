"""Filtro tributario CONSULTIVO (S11, enmienda v2 §2, ADR-022). Nivel 3, puro.

No prohíbe nada: ETIQUETA. Para cada activo que el flujo nuevo no logra devolver a su banda por
arriba (sobreponderado), estima qué costaría corregirlo vendiendo —hasta el borde de la banda o
hasta el objetivo— y lo dice con la etiqueta «Costo fiscal estimado: $X CLP». El escenario por
defecto es siempre NO vender. Una venta que realizaría una PÉRDIDA se reconoce como lo que es
(tax-loss harvesting, una estrategia legítima), no como algo a evitar; y los activos con
pérdida latente se listan aunque nadie proponga venderlos.

Los supuestos (tramo marginal, tipo de cambio, costo de adquisición) son DEL USUARIO
(``config.yaml: fintual.tributario``) y viajan en la salida. Sin costo de adquisición declarado,
el costo fiscal es una COTA: se asume que toda la venta es ganancia.
"""

from __future__ import annotations

from investmentsys.config import FintualConfig
from investmentsys.contracts import (
    AsesoriaFiscal,
    BaseCosto,
    DecisionInercia,
    EscenarioFiscal,
    OrdenInercia,
    PerdidaLatente,
    PlanCompraNeta,
    SupuestosFiscales,
    TipoEscenario,
    etiqueta_costo,
)
from investmentsys.fintual.cash_flow_alloc import plan_compra_neta

ID_SIN_VENTAS = "sin_ventas"
ADVERTENCIA_GANANCIA = (
    "Vender US$ {venta:.2f} de {activo} realiza una ganancia estimada de US$ {ganancia:.2f}: "
    "{etiqueta}{cota}. El plan por defecto no vende: corrige la desviación solo con flujos "
    "nuevos. Si tu estrategia lo requiere puedes forzar esta orden; quedará registrada en el "
    "acta junto con esta advertencia."
)
ADVERTENCIA_PERDIDA = (
    "Vender US$ {venta:.2f} de {activo} realiza una PÉRDIDA estimada de US$ {perdida:.2f} "
    "(${perdida_clp} CLP): {etiqueta}. Realizar pérdidas para compensar ganancias (tax-loss "
    "harvesting) es una estrategia legítima; su tratamiento concreto valídalo con tu contador. "
    "Es una venta fuera del plan por defecto: si la fuerzas, quedará registrada en el acta junto "
    "con esta advertencia."
)
NOTA_COTA = " (COTA: sin costo de adquisición declarado se asume que toda la venta es ganancia)"


def _miles(clp: float) -> str:
    return f"{round(clp):,}".replace(",", ".")


def _escenario_de_venta(
    d: DecisionInercia,
    tipo: TipoEscenario,
    peso_destino: float,
    valor_usd: float,
    supuestos: SupuestosFiscales,
    decimales: int,
) -> EscenarioFiscal:
    venta = round(d.monto_actual_usd - peso_destino * valor_usd, decimales)
    costo_base = supuestos.costo_base_usd.get(d.activo)
    if costo_base is None:
        base, fraccion_ganancia = BaseCosto.COTA_SIN_COSTO, 1.0
    else:
        base, fraccion_ganancia = BaseCosto.DECLARADA, 1.0 - costo_base / d.monto_actual_usd
    resultado = round(venta * fraccion_ganancia, decimales)
    costo_clp = max(resultado, 0.0) * supuestos.tasa_marginal * supuestos.usd_clp
    perdida_clp = max(-resultado, 0.0) * supuestos.usd_clp
    etiqueta = etiqueta_costo(costo_clp)
    if resultado < 0.0:
        advertencia = ADVERTENCIA_PERDIDA.format(
            venta=venta,
            activo=d.activo,
            perdida=-resultado,
            perdida_clp=_miles(perdida_clp),
            etiqueta=etiqueta,
        )
    else:
        advertencia = ADVERTENCIA_GANANCIA.format(
            venta=venta,
            activo=d.activo,
            ganancia=resultado,
            etiqueta=etiqueta,
            cota=NOTA_COTA if base is BaseCosto.COTA_SIN_COSTO else "",
        )
    destino = "el borde de su banda" if tipo is TipoEscenario.VENDER_HASTA_BANDA else "su objetivo"
    return EscenarioFiscal(
        id=f"{d.activo}:{tipo.value}",
        tipo=tipo,
        por_defecto=False,
        activo=d.activo,
        venta_usd=venta,
        resultado_usd=resultado,
        base_costo=base,
        costo_fiscal_clp=costo_clp,
        perdida_realizable_clp=perdida_clp,
        cosecha_de_perdidas=resultado < 0.0,
        etiqueta=etiqueta,
        efecto=(
            f"{d.activo} bajaría de {d.peso_actual * 100:.1f} % a {peso_destino * 100:.1f} % "
            f"({destino}); el producto de la venta se reasigna a los activos bajo objetivo."
        ),
        advertencia=advertencia,
    )


def asesorar(plan: PlanCompraNeta, config: FintualConfig) -> AsesoriaFiscal:
    """Escenarios sobre la cartera DESPUÉS del flujo: lo que el plan de compra no pudo corregir."""
    tributario = config.tributario
    supuestos = SupuestosFiscales(
        tasa_marginal=tributario.tasa_marginal,
        usd_clp=tributario.usd_clp,
        costo_base_usd=dict(tributario.costo_base_usd),
    )
    despues = plan.inercia_despues
    sobreponderados = [
        d
        for d in despues.decisiones
        if d.orden is OrdenInercia.FUERA_DE_BANDA and d.desviacion > 0.0
    ]
    fuera = ", ".join(d.activo for d in despues.decisiones if d.orden is not OrdenInercia.HOLD)
    sin_ventas = EscenarioFiscal(
        id=ID_SIN_VENTAS,
        tipo=TipoEscenario.SIN_VENTAS,
        por_defecto=True,
        venta_usd=0.0,
        resultado_usd=0.0,
        base_costo=BaseCosto.NO_APLICA,
        costo_fiscal_clp=0.0,
        perdida_realizable_clp=0.0,
        cosecha_de_perdidas=False,
        etiqueta=etiqueta_costo(0.0),
        efecto=(
            f"no se vende nada; siguen fuera de banda: {fuera}. Se corrigen con los próximos "
            "flujos."
            if fuera
            else "no se vende nada; toda la cartera queda dentro de sus bandas."
        ),
    )
    ventas = [
        _escenario_de_venta(
            d, tipo, destino, despues.valor_cartera_usd, supuestos, config.decimales_usd
        )
        for d in sobreponderados
        for tipo, destino in (
            (TipoEscenario.VENDER_HASTA_BANDA, d.peso_objetivo + d.banda),
            (TipoEscenario.VENDER_HASTA_OBJETIVO, d.peso_objetivo),
        )
    ]
    latentes = []
    for d in despues.decisiones:
        costo_base = supuestos.costo_base_usd.get(d.activo)
        if costo_base is not None and costo_base > d.monto_actual_usd:
            perdida = round(costo_base - d.monto_actual_usd, config.decimales_usd)
            latentes.append(
                PerdidaLatente(
                    activo=d.activo,
                    perdida_latente_usd=perdida,
                    perdida_latente_clp=perdida * supuestos.usd_clp,
                )
            )
    return AsesoriaFiscal(
        universe_version=plan.universe_version,
        supuestos=supuestos,
        escenarios=(sin_ventas, *ventas),
        perdidas_latentes=tuple(latentes),
    )


def plan_tras_override(
    plan: PlanCompraNeta, escenario: EscenarioFiscal, config: FintualConfig
) -> PlanCompraNeta:
    """El usuario forzó ``escenario``: la venta sale del activo y su producto se reasigna con la
    MISMA regla de flujos. Sigue siendo un plan: el sistema nunca ejecuta."""
    if escenario.activo is None or escenario.venta_usd <= 0.0:
        raise ValueError("el escenario sin ventas no se fuerza: ya es el plan por defecto")
    tenencias = {d.activo: d.monto_actual_usd for d in plan.inercia_antes.decisiones}
    if escenario.venta_usd > tenencias.get(escenario.activo, 0.0):
        raise ValueError(f"no hay US$ {escenario.venta_usd:.2f} de {escenario.activo} que vender")
    tenencias[escenario.activo] -= escenario.venta_usd
    objetivo = {d.activo: d.peso_objetivo for d in plan.inercia_antes.decisiones}
    return plan_compra_neta(
        objetivo,
        tenencias,
        config,
        aporte_usd=plan.aporte_usd,
        dividendos_usd=plan.dividendos_usd,
        reinversion_usd=escenario.venta_usd,
        universe_version=plan.universe_version,
        validado=plan.validado,
        origen_objetivo=plan.origen_objetivo,
    )
