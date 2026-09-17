"""Informe Markdown desde ``RunState``. Las cifras las escribe este módulo, no el LLM.

El reporter (LLM) solo aporta la narrativa. Todo número del informe sale de los contratos:
las tablas se renderizan aquí y las cifras que el LLM mencione se cotejan con la hoja de
hechos; las que no aparezcan en ella se listan en el propio informe como no verificadas.
"""

from __future__ import annotations

import re
from typing import Any

from investmentsys.contracts import DISCLAIMER, RunState, ValidationReport

_CIFRA = re.compile(r"(?<![\w.,])[-+−]?\d+(?:[.,]\d+)?\s?%")


def _pct(x: float, decimales: int = 1) -> str:
    return f"{x * 100:.{decimales}f} %"


def hoja_de_hechos(corrida: RunState) -> dict[str, Any]:
    """Lo único que el reporter puede citar: cifras ya formateadas como irán en el informe."""
    hechos: dict[str, Any] = {
        "fecha_decision": corrida.fecha_decision.isoformat(),
        "activos": list(corrida.activos),
        "aprobado": corrida.aprobado,
        "iteraciones": len(corrida.validaciones),
    }
    if corrida.market_views:
        hechos["views"] = [
            {
                "tipo": v.tipo.value,
                "coeficientes": dict(v.coeficientes),
                "q_anual": _pct(v.q_anual),
                "confianza": _pct(v.confianza, 0),
                "justificacion": v.justificacion,
            }
            for v in corrida.market_views.views
        ]
        hechos["lectura_de_mercado"] = corrida.market_views.resumen
    hechos["rondas"] = [
        {
            "iteracion": r.iteracion,
            "recomendado": r.recomendado,
            "pesos": {a: _pct(p) for a, p in r.portafolio_recomendado.pesos.items()},
            "veredicto": v.veredicto.value,
            "sharpe_oos": f"{v.metricas_oos.sharpe_oos:.2f}",
            "max_drawdown": _pct(v.metricas_oos.max_drawdown),
            "razones_rechazo": list(v.razones_rechazo),
            "sugerencias": list(v.sugerencias),
        }
        for r, v in zip(corrida.candidatos, corrida.validaciones, strict=False)
    ]
    return hechos


def cifras_no_verificadas(narrativa: str, corrida: RunState) -> list[str]:
    """Porcentajes de la narrativa que no figuran, tal cual, en la hoja de hechos."""

    def normal(s: str) -> str:
        return s.replace("−", "-").replace(",", ".").replace(" ", "").lstrip("+")

    permitidas = {normal(m) for m in _CIFRA.findall(str(hoja_de_hechos(corrida)))}
    vistas = dict.fromkeys(m.strip() for m in _CIFRA.findall(narrativa))
    return [
        c for c in vistas if normal(c) not in permitidas and normal(c).lstrip("-") not in permitidas
    ]


def _tabla_candidatos(corrida: RunState, iteracion: int) -> list[str]:
    ronda = corrida.candidatos[iteracion]
    activos = corrida.activos
    lineas = [
        "| Candidato | " + " | ".join(activos) + " | Ret. esp. | Vol. | Sharpe | HHI |",
        "|---|" + "---:|" * (len(activos) + 4),
    ]
    for c in ronda.candidatos:
        marca = " **(recomendado)**" if c.nombre == ronda.recomendado else ""
        m = c.metricas
        lineas.append(
            f"| {c.nombre}{marca} | "
            + " | ".join(_pct(c.pesos[a]) for a in activos)
            + f" | {_pct(m.retorno_esperado_anual)} | {_pct(m.volatilidad_anual)} | "
            f"{m.sharpe:.2f} | {m.concentracion_hhi:.3f} |"
        )
    return lineas


def _seccion_validacion(v: ValidationReport) -> list[str]:
    m = v.metricas_oos
    lineas = [
        f"**Veredicto: {v.veredicto.value.upper()}** — candidato `{v.candidato_evaluado}`. "
        f"Backtest walk-forward {m.fecha_inicio} → {m.fecha_fin} ({m.n_periodos} períodos): "
        f"retorno {_pct(m.retorno_anualizado)}, volatilidad {_pct(m.volatilidad_anualizada)}, "
        f"Sharpe OOS {m.sharpe_oos:.2f}, caída máxima {_pct(m.max_drawdown)}, turnover "
        f"{m.turnover_anual:.2f}/año, costos {m.costo_transaccion_total * 1e4:.1f} p.b. "
        f"Look-ahead verificado: {'sí' if v.look_ahead_verificado else 'NO'}.",
        "",
        "| Criterio | Valor | Umbral | Cumple |",
        "|---|---:|---:|:---:|",
        *(
            f"| {c.nombre} | {c.valor:.4f} | {c.umbral} | {'sí' if c.cumple else '**no**'} |"
            for c in v.criterios
        ),
    ]
    if v.stress:
        lineas += [
            "",
            "| Stress | Período | Retorno | Caída máx. | Superado |",
            "|---|---|---:|---:|:---:|",
            *(
                f"| {s.escenario} | {s.fecha_inicio} → {s.fecha_fin} | {_pct(s.retorno_periodo)} "
                f"| {_pct(s.max_drawdown)} | {'sí' if s.superado else '**no**'} |"
                for s in v.stress
            ),
        ]
    if v.razones_rechazo or v.sugerencias:
        lineas += ["", *(f"- Razón de rechazo: {r}" for r in v.razones_rechazo)]
        lineas += [f"- Sugerencia al constructor: {s}" for s in v.sugerencias]
    return lineas


def renderizar(corrida: RunState, narrativa: str, modelo: str, notas: tuple[str, ...] = ()) -> str:
    final = corrida.portafolio_final
    titulo = "cartera aprobada" if final else "SIN cartera aprobada"
    lineas = [
        f"# Informe de portafolio — {corrida.fecha_decision} ({titulo})",
        "",
        f"> {DISCLAIMER}",
        "",
        f"Corrida `{corrida.run_id}` · semilla {corrida.semilla} · config "
        f"`{corrida.config_hash[:12]}` · narrativa redactada por `{modelo}`; todas las tablas "
        "y cifras provienen de las herramientas cuantitativas.",
        "",
        "## Resumen",
        "",
        narrativa.strip(),
        "",
    ]
    sospechosas = cifras_no_verificadas(narrativa, corrida)
    if sospechosas:
        lineas += [
            "> **Aviso:** la narrativa menciona cifras que no figuran en los resultados de las "
            f"herramientas y no deben tomarse como datos: {', '.join(sospechosas)}.",
            "",
        ]
    if final:
        lineas += [
            "## Cartera aprobada",
            "",
            "| Activo | Peso |",
            "|---|---:|",
            *(f"| {a} | {_pct(final.pesos[a])} |" for a in corrida.activos),
            "",
        ]
    if corrida.market_views:
        lineas += ["## Views del analista", "", corrida.market_views.resumen, ""]
        lineas += [
            f"- **{v.tipo.value}** {dict(v.coeficientes)}: q = {_pct(v.q_anual)}, confianza "
            f"{_pct(v.confianza, 0)}. {v.justificacion} _(fuente: {v.fuente})_"
            for v in corrida.market_views.views
        ] or ["- Sin views: el posterior es el equilibrio de mercado."]
        lineas.append("")
    for i, validacion in enumerate(corrida.validaciones):
        lineas += [f"## Iteración {i + 1}", "", *_tabla_candidatos(corrida, i), ""]
        lineas += [*_seccion_validacion(validacion), ""]
    if notas or corrida.errores:
        lineas += [
            "## Notas de la corrida",
            "",
            *(f"- {n}" for n in (*notas, *corrida.errores)),
            "",
        ]
    lineas += ["---", "", DISCLAIMER, ""]
    return "\n".join(lineas)
