"""Informe Markdown desde ``RunState``. Las cifras las escribe este módulo, no el LLM.

El reporter (LLM) solo aporta la narrativa. Todo número del informe sale de los contratos:
las tablas se renderizan aquí y las cifras que el LLM mencione se cotejan con la hoja de
hechos; las que no aparezcan en ella se listan en el propio informe como no verificadas.
"""

from __future__ import annotations

import re
from typing import Any

from investmentsys.contracts import (
    DISCLAIMER,
    MetodoPrior,
    RunState,
    ValidationReport,
)
from investmentsys.portfolio.prior import mensaje_estado_prior

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
    hechos["universo"] = {
        "version": corrida.universo.version[:12],
        "advertencias": [
            f"{d.ticker}: {a}" for d in corrida.universo.diagnosticos for a in d.advertencias
        ],
    }
    hechos["prior"] = _hechos_prior(corrida)
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
            "advertencias": list(v.advertencias),
            "tecnicas_no_disponibles": {t.value: m for t, m in r.no_disponibles.items()},
        }
        for r, v in zip(corrida.candidatos, corrida.validaciones, strict=False)
    ]
    return hechos


def _hechos_prior(corrida: RunState) -> dict[str, Any]:
    prior = corrida.prior
    if prior is None:
        return {"disponible": False, "motivo": mensaje_estado_prior(corrida.universo)}
    return {
        "disponible": True,
        "metodo": prior.metodo.value,
        "advertencia": prior.advertencia,
        "por_activo": {
            a.activo: {
                "procedencia": a.procedencia.value,
                "peso_mercado": _pct(a.peso_mercado) if a.peso_mercado is not None else None,
                "retorno_implicito_total": _pct(a.pi_total),
            }
            for a in prior.activos
        },
    }


def _seccion_universo(corrida: RunState) -> list[str]:
    u, sesion = corrida.universo, corrida.restricciones_sesion
    lineas = [
        "## Universo y restricciones",
        "",
        f"Universo `{u.version[:12]}` · restricciones de la sesión: piso "
        f"{_pct(sesion.peso_min.valor)} ({sesion.peso_min.origen.value}), techo "
        f"{_pct(sesion.peso_max.valor)} ({sesion.peso_max.origen.value}).",
        "",
        "| Activo | Nombre | Origen | Datos | Meses | Límites |",
        "|---|---|---|---|---:|---|",
    ]
    for d in u.diagnosticos:
        lo, hi = sesion.limites(d.ticker)
        propio = sesion.limites_por_activo.get(d.ticker)
        origen_limite = f" ({propio.origen.value})" if propio else ""
        lineas.append(
            f"| {d.ticker} | {d.nombre} | {u.origenes[d.ticker].value} | {d.fecha_inicio_datos} → "
            f"{d.fecha_fin_datos} | {d.meses_disponibles} | {_pct(lo)} – {_pct(hi)}"
            f"{origen_limite} |"
        )
    avisos = [f"- **{d.ticker}**: {a}" for d in u.diagnosticos for a in d.advertencias]
    if avisos:
        lineas += ["", "Advertencias de datos:", "", *avisos]
    return [*lineas, ""]


def _seccion_aprobacion(corrida: RunState) -> list[str]:
    """Qué aprobó el usuario antes de correr (ADR-014); ausente en el modo comando."""
    a = corrida.aprobacion
    if a is None:
        return []
    r = a.resumen
    procedencias = ", ".join(f"{t} ({p.value})" for t, p in r.procedencias_prior.items())
    n_views = len(r.views_de_partida.views) if r.views_de_partida else 0
    material = "sí (citado, sin verificar)" if r.material_usuario else "no"
    lineas = [
        "## Aprobación del usuario",
        "",
        f"El Director presentó el resumen de esta corrida el {a.solicitado_en.isoformat()} y el "
        f"usuario lo confirmó el {a.confirmado_en.isoformat()}, en un turno posterior. Aprobó:",
        "",
        f"- Universo `{r.universe_version[:12]}`: {', '.join(r.activos)}.",
        f"- Prior {r.estado_prior.value}: {procedencias}.",
        f"- Restricciones: piso {_pct(r.restricciones.peso_min.valor)}, techo "
        f"{_pct(r.restricciones.peso_max.valor)}"
        + (
            f"; límites propios en {', '.join(r.restricciones.limites_por_activo)}."
            if r.restricciones.limites_por_activo
            else "."
        ),
        f"- Views de partida: {n_views}; material aportado por el usuario: {material}.",
        "",
    ]
    return lineas


def _seccion_prior(corrida: RunState) -> list[str]:
    """SIEMPRE presente (ADR-013): la tabla π con la procedencia de cada peso, o por qué no hay."""
    lineas = ["## Prior de equilibrio (Black-Litterman)", ""]
    prior = corrida.prior
    if prior is None:
        return [*lineas, f"> **{mensaje_estado_prior(corrida.universo)}.**", ""]
    if prior.advertencia:
        lineas += [f"> **Advertencia — {prior.advertencia}.**", ""]
    lineas += [
        f"Método: `{prior.metodo.value}` · δ = {prior.delta:g} · π = δ·Σ·w_mkt con covarianza "
        f"`{prior.metodo_covarianza.value}`; retorno implícito total = π + tasa libre de riesgo "
        f"({_pct(prior.tasa_libre_riesgo)}).",
        "",
        "| Activo | Procedencia | Cap (US$ bill.) | Detalle | As-of | w_mkt | π (exceso) "
        "| π (total) |",
        "|---|---|---:|---|---|---:|---:|---:|",
    ]
    for a in prior.activos:
        cap = f"{a.cap:g}" if a.cap is not None else "—"
        peso = _pct(a.peso_mercado) if a.peso_mercado is not None else "—"
        lineas.append(
            f"| {a.activo} | {a.procedencia.value} | {cap} | {a.fuente_detalle or '—'} | "
            f"{a.as_of or '—'} | {peso} | {_pct(a.pi_exceso)} | {_pct(a.pi_total)} |"
        )
    if prior.metodo is not MetodoPrior.CAPITALIZACION:
        sin_cap = ", ".join(corrida.universo.sin_cap)
        lineas += ["", f"Degradación confirmada por el usuario; sin capitalización: {sin_cap}."]
    return [*lineas, ""]


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
    if v.advertencias:
        lineas += ["", "Alcance de esta validación (historia corta):", ""]
        lineas += [f"- {a}" for a in v.advertencias]
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
    lineas += _seccion_aprobacion(corrida)
    lineas += _seccion_universo(corrida)
    lineas += _seccion_prior(corrida)
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
        lineas += [
            f"- **{t.value} no disponible**: {m}"
            for t, m in corrida.candidatos[i].no_disponibles.items()
        ]
        lineas += [""] if corrida.candidatos[i].no_disponibles else []
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
