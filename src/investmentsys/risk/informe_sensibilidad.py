"""Informe en Markdown de un análisis de sensibilidad. Código puro: solo da formato a cifras
que ya calculó ``risk.sensibilidad``; la conclusión se deriva de ellas, no se redacta a mano."""

from __future__ import annotations

from dataclasses import dataclass

from investmentsys.contracts import DISCLAIMER, MarketViews
from investmentsys.risk.sensibilidad import (
    PP,
    AnalisisSensibilidad,
    Familia,
    Perturbacion,
    Supuesto,
)

DESCRIPCION_FAMILIA: dict[Familia, str] = {
    Familia.VIEWS_Q: "q de cada view (± p.p.)",
    Familia.MU_POSTERIOR: "μ posterior de cada activo (± p.p.), con Σ_BL fija",
    Familia.VOLATILIDAD: "volatilidad de cada activo (± %)",
    Familia.CORRELACION: "correlación de cada par (± %)",
    Familia.COVARIANZA_GLOBAL: "toda Σ (± %)",
    Familia.PARAMETROS: "δ y τ (± %)",
}
PEORES_A_MOSTRAR = 10  # filas de una tabla del informe, no un parámetro financiero


@dataclass(frozen=True)
class Escenario:
    """Un análisis con su nombre y los límites de peso con que se corrió."""

    nombre: str
    limites: str
    analisis: AnalisisSensibilidad


def _magnitud(p: Perturbacion) -> str:
    if p.supuesto is Supuesto.RETORNOS:
        return f"{p.magnitud * PP:+.0f} p.p."
    return f"{p.magnitud:+.0%}"


def _pesos(pesos: dict[str, float]) -> str:
    return " / ".join(f"{a} {w:.1%}" for a, w in pesos.items())


def _tabla_supuestos(analisis: AnalisisSensibilidad) -> list[str]:
    lineas = ["| Supuesto | Desplazamiento medio (p.p.) |", "|---|---|"]
    lineas += [f"| {s.value} | {media:.2f} |" for s, media in analisis.por_supuesto().items()]
    return lineas


def _tabla_familias(analisis: AnalisisSensibilidad) -> list[str]:
    lineas = [
        "| Familia | Qué se perturba | n | Medio (p.p.) | Peor (p.p.) | Peor caso |",
        "|---|---|---|---|---|---|",
    ]
    for f in analisis.por_familia():
        peor = f"{f.peor.parametro} {_magnitud(f.peor)} → {f.peor.activo_mas_afectado}"
        lineas.append(
            f"| `{f.familia.value}` | {DESCRIPCION_FAMILIA[f.familia]} | {f.n} | "
            f"{f.cambio_max_pp_medio:.2f} | {f.cambio_max_pp_peor:.2f} | {peor} |"
        )
    return lineas


def _tabla_peores(analisis: AnalisisSensibilidad) -> list[str]:
    peores = sorted(analisis.perturbaciones, key=lambda p: p.cambio_max_pp, reverse=True)
    lineas = [
        "| Familia | Parámetro | Perturbación | Cambio máx. (p.p.) | Rotación (p.p.) | Pesos |",
        "|---|---|---|---|---|---|",
    ]
    for p in peores[:PEORES_A_MOSTRAR]:
        lineas.append(
            f"| `{p.familia.value}` | {p.parametro} | {_magnitud(p)} | {p.cambio_max_pp:.2f} | "
            f"{p.rotacion_pp:.2f} | {_pesos(p.pesos)} |"
        )
    return lineas


def _tabla_rangos(analisis: AnalisisSensibilidad) -> list[str]:
    lineas = ["| Activo | Peso base | Mínimo | Máximo | Rango (p.p.) |", "|---|---|---|---|---|"]
    for activo, base in analisis.pesos_base.items():
        pesos = [p.pesos[activo] for p in analisis.perturbaciones]
        lo, hi = min(pesos), max(pesos)
        lineas.append(f"| {activo} | {base:.1%} | {lo:.1%} | {hi:.1%} | {(hi - lo) * PP:.1f} |")
    return lineas


def _conclusion(escenarios: tuple[Escenario, ...]) -> list[str]:
    lineas = []
    for e in escenarios:
        a = e.analisis
        medias = a.por_supuesto()
        fragil = a.supuesto_mas_fragil()
        peor = max(a.perturbaciones, key=lambda p: p.cambio_max_pp)
        otros = ", ".join(f"{s.value} {m:.1f}" for s, m in medias.items() if s is not fragil)
        lineas.append(
            f"- **{e.nombre}**: la cartera es más frágil a: **{fragil.value}** "
            f"({medias[fragil]:.1f} p.p. de desplazamiento medio; {otros}). Peor caso: "
            f"`{peor.familia.value}` {peor.parametro} {_magnitud(peor)} mueve "
            f"{peor.activo_mas_afectado} {peor.cambio_max_pp:.1f} p.p."
        )
        if a.limites_activos:
            lineas.append(
                f"  Pesos pegados a un límite en la cartera base: {', '.join(a.limites_activos)}. "
                "Esos pesos los fija el límite, no las estimaciones."
            )
    return lineas


def informe_markdown(
    escenarios: tuple[Escenario, ...],
    views: MarketViews,
    origen_views: str,
    config_hash: str,
    rejilla: str,
) -> str:
    lineas = [
        "# Análisis de sensibilidad de la cartera Black-Litterman",
        "",
        f"- Fecha de decisión: {views.fecha_decision}",
        f"- Views: {origen_views}",
        *(f"  - {v.tipo.value} {v.coeficientes}: q = {v.q_anual:+.1%}" for v in views.views),
        f"- Rejilla de perturbaciones (`config.yaml: sensibilidad`): {rejilla}",
        f"- `config_hash`: `{config_hash}`",
        "",
        "Se perturba un supuesto a la vez y se reoptimiza. *Cambio máx.* es el mayor cambio "
        "absoluto de un peso frente a la cartera base; *desplazamiento medio* es su promedio "
        "sobre las perturbaciones de la familia o del supuesto. *Rotación* = ½·Σ|Δw|.",
        "",
        "## Conclusión",
        "",
        *_conclusion(escenarios),
    ]
    for e in escenarios:
        a = e.analisis
        lineas += [
            "",
            f"## {e.nombre} ({e.limites})",
            "",
            f"Cartera base: {_pesos(a.pesos_base)}.",
            "",
            "### Por supuesto",
            "",
            *_tabla_supuestos(a),
            "",
            "### Por familia de perturbación",
            "",
            *_tabla_familias(a),
            "",
            f"### Las {PEORES_A_MOSTRAR} perturbaciones que más mueven la cartera",
            "",
            *_tabla_peores(a),
            "",
            "### Rango de cada peso sobre todas las perturbaciones",
            "",
            *_tabla_rangos(a),
        ]
        if a.omitidas:
            lineas += ["", "### Perturbaciones omitidas (Σ no definida positiva)", ""]
            lineas += [f"- {o}" for o in a.omitidas]
    lineas += ["", "---", "", DISCLAIMER, ""]
    return "\n".join(lineas)
