"""Informe en Markdown de un ``DiffCorridas``. Solo da formato: ninguna cifra nace aquí."""

from __future__ import annotations

from investmentsys.comparacion.corridas import (
    PP,
    Cambio,
    DiffCorridas,
    ViewNormalizada,
)
from investmentsys.contracts import DISCLAIMER

AUSENTE = "—"
LARGO_HASH = 12  # caracteres del config_hash que se muestran
# Métricas que son fracciones y se leen mejor en %; el resto (Sharpe, HHI, turnover) va tal cual.
EN_PORCENTAJE = {
    "retorno_esperado_anual",
    "volatilidad_anual",
    "retorno_anualizado",
    "volatilidad_anualizada",
    "max_drawdown",
}


def _meta(nombre: str, valor: str | None) -> str:
    if valor is None:
        return AUSENTE
    return f"`{valor[:LARGO_HASH]}…`" if nombre == "config_hash" else valor


def _pct(valor: float | None) -> str:
    return AUSENTE if valor is None else f"{valor:.1%}"


def _num(valor: float | None) -> str:
    return AUSENTE if valor is None else f"{valor:.3f}"


def _delta_pp(cambio: Cambio) -> str:
    if cambio.delta is None:
        return AUSENTE
    return f"{round(cambio.delta * PP, 1) + 0.0:+.1f} p.p."  # + 0.0: sin "-0.0"


def _tabla_pct(titulo: str, cambios: tuple[Cambio, ...]) -> list[str]:
    lineas = [f"| {titulo} | Antes | Después | Δ |", "|---|---|---|---|"]
    lineas += [
        f"| {c.nombre} | {_pct(c.antes)} | {_pct(c.despues)} | {_delta_pp(c)} |" for c in cambios
    ]
    return lineas


def _tabla_metricas(cambios: tuple[Cambio, ...]) -> list[str]:
    lineas = ["| Métrica | Antes | Después | Δ |", "|---|---|---|---|"]
    for c in cambios:
        if c.nombre in EN_PORCENTAJE:
            lineas.append(f"| {c.nombre} | {_pct(c.antes)} | {_pct(c.despues)} | {_delta_pp(c)} |")
        else:
            delta = AUSENTE if c.delta is None else f"{c.delta:+.3f}"
            lineas.append(f"| {c.nombre} | {_num(c.antes)} | {_num(c.despues)} | {delta} |")
    return lineas


def _view(v: ViewNormalizada) -> str:
    return f"{v.tipo.value} {v.describir()}: q = {v.q_anual:+.1%}, confianza {v.confianza:.0%}"


def _seccion_views(diff: DiffCorridas) -> list[str]:
    v = diff.views
    if not v.hay_cambios:
        return [f"Sin cambios ({len(v.sin_cambio)} views iguales)."]
    lineas = [f"- Añadida: {_view(x)}" for x in v.anadidas]
    lineas += [f"- Retirada: {_view(x)}" for x in v.retiradas]
    lineas += [
        f"- Modificada: {c.antes.tipo.value} {c.antes.describir()}: q {c.antes.q_anual:+.1%} → "
        f"{c.despues.q_anual:+.1%} ({c.delta_q * PP:+.1f} p.p.), confianza "
        f"{c.antes.confianza:.0%} → {c.despues.confianza:.0%}"
        for c in v.modificadas
    ]
    lineas += [f"- Sin cambio: {_view(x)}" for x in v.sin_cambio]
    return lineas


def _seccion_criterios(diff: DiffCorridas) -> list[str]:
    def marca(cumple: bool | None) -> str:
        return AUSENTE if cumple is None else ("cumple" if cumple else "NO cumple")

    lineas = ["| Criterio | Antes | Después | |", "|---|---|---|---|"]
    for c in diff.criterios:
        aviso = "**cambia de lado**" if c.cambia_de_lado else ""
        lineas.append(
            f"| {c.nombre} | {_num(c.valor.antes)} ({marca(c.cumple_antes)}) | "
            f"{_num(c.valor.despues)} ({marca(c.cumple_despues)}) | {aviso} |"
        )
    return lineas


def diff_markdown(diff: DiffCorridas, tolerancia: float) -> str:
    antes, despues = diff.metadato("run_id").antes, diff.metadato("run_id").despues
    lineas = [
        f"# Comparación de corridas: `{antes}` → `{despues}`",
        "",
        "| | Antes | Después |",
        "|---|---|---|",
        *(
            f"| {m.nombre}{' ⚠' if m.cambia and m.nombre != 'run_id' else ''} | "
            f"{_meta(m.nombre, m.antes)} | {_meta(m.nombre, m.despues)} |"
            for m in diff.metadatos
        ),
    ]
    if diff.advertencias:
        lineas += ["", *(f"> ⚠ {a}" for a in diff.advertencias)]
    rotacion = AUSENTE if diff.rotacion_pp is None else f"{diff.rotacion_pp:.1f} p.p."
    lineas += [
        "",
        "## Cartera",
        "",
        f"Rotación para pasar de una a otra (½·Σ|Δw|): **{rotacion}**.",
        "",
        *_tabla_pct("Peso", diff.pesos),
        "",
        *_tabla_metricas(diff.metricas_ex_ante),
        "",
        "## Views del analista",
        "",
        *_seccion_views(diff),
        "",
        "## Estimaciones del Quant",
        "",
    ]
    if any(c.cambia(tolerancia) for c in (*diff.volatilidades, *diff.correlaciones)):
        lineas += [
            *_tabla_pct("Volatilidad", diff.volatilidades),
            "",
            *_tabla_pct("Retorno histórico", diff.retornos_historicos),
            "",
            "| Correlación | Antes | Después | Δ |",
            "|---|---|---|---|",
            *(
                f"| {c.nombre} | {_num(c.antes)} | {_num(c.despues)} | "
                f"{AUSENTE if c.delta is None else f'{c.delta:+.3f}'} |"
                for c in diff.correlaciones
            ),
        ]
    else:
        lineas.append("Idénticas (misma muestra y mismo método).")
    lineas += ["", "## Restricciones (peso máximo por activo)", ""]
    if any(c.cambia(tolerancia) for c in diff.peso_maximo):
        lineas += _tabla_pct("Peso máximo", diff.peso_maximo)
    else:
        lineas.append("Sin cambios.")
    lineas += [
        "",
        "## Validación",
        "",
        *_tabla_metricas(diff.metricas_oos),
        "",
        *_seccion_criterios(diff),
        "",
        "---",
        "",
        DISCLAIMER,
        "",
    ]
    return "\n".join(lineas)
