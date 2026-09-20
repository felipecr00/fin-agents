"""Ficha de origen (S9): quién produjo una cifra, con qué herramienta y sobre qué universo.

La redacta el CÓDIGO a partir de la salida de una herramienta; el Director no la escribe ni la
puede omitir (la anexa un callback a su respuesta, ver ``agents/director/anexos.py``). Todo dato
con ``validado: false`` lleva ``PREFIJO_NO_VALIDADO``: la advertencia sobrevive a la narración
porque no depende de ella. El especialista sale de ``ATIENDE``, la misma fuente que el roster.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from investmentsys.contracts import Especialista

PREFIJO_NO_VALIDADO = "⚠ NO VALIDADO · "
ETIQUETA_FICHA_EXPLORATORIA = "EXPLORATORIO (no pasó por el comité)"
ETIQUETA_FICHA_COMITE = "COMITÉ FORMAL (validado; consta en el acta)"
ETIQUETA_FICHA_COMITE_SIN_APROBAR = "COMITÉ FORMAL — SIN CARTERA APROBADA"
CLAVE_ANEXO = "anexo_usuario"
"""Clave de la salida de una herramienta con un bloque YA redactado para el usuario."""

# Qué silla atiende cada herramienta o sub-agente del equipo. Fuente única de la atribución:
# una herramienta sin silla no entra a la sala (``componer_sala`` falla al construir el equipo).
ATIENDE: Mapping[str, Especialista] = {
    "consultar_mesa_trabajo": Especialista.DIRECTOR,
    "resolver": Especialista.GESTOR_DATOS,
    "incorporar": Especialista.GESTOR_DATOS,
    "retirar": Especialista.GESTOR_DATOS,
    "aceptar_prior_neutral": Especialista.GESTOR_DATOS,
    "refrescar_cap": Especialista.GESTOR_DATOS,
    "diagnosticar": Especialista.GESTOR_DATOS,
    "market_analyst": Especialista.ANALISTA,
    "estimar_mercado": Especialista.ESTADISTICO,
    "construir_candidatos": Especialista.CONSTRUCTOR,
    "ajustar_restricciones": Especialista.CONSTRUCTOR,
    "diagnosticar_cartera": Especialista.ESCEPTICO,
    "convocar_comite": Especialista.COMITE,
}


def pct(valor: float, decimales: int = 2) -> str:
    return f"{valor * 100:.{decimales}f} %"


def pesos(valores: Mapping[str, float]) -> str:
    return " / ".join(f"{a} {pct(p, 1)}" for a, p in valores.items())


# ------------------------------------------------------ cifras clave, por herramienta
def _estimar_mercado(s: Mapping[str, Any]) -> list[str]:
    lineas = [
        f"{a}: volatilidad anual {pct(v['volatilidad_anual'])}, retorno histórico anual "
        f"{pct(v['retorno_historico_anual'])} ({v['observaciones']} observaciones)"
        for a, v in s["por_activo"].items()
    ]
    correlaciones = s.get("correlaciones") or {}
    if correlaciones:
        pares = ", ".join(f"{par} {c:.2f}" for par, c in correlaciones.items())
        lineas.append(f"correlaciones ({s.get('correlaciones_metodo', 'método vigente')}): {pares}")
    return lineas


def _construir_candidatos(s: Mapping[str, Any]) -> list[str]:
    nombre = s["recomendado"]
    c = s["candidatos"][nombre]
    return [
        f"cartera recomendada {nombre}: {pesos(c['pesos'])}",
        f"{nombre}: retorno esperado anual {pct(c['retorno_esperado_anual'])}, volatilidad "
        f"anual {pct(c['volatilidad_anual'])}, Sharpe {c['sharpe']:.2f}",
    ]


def _diagnosticar_cartera(s: Mapping[str, Any]) -> list[str]:
    m = s["metricas_oos"]
    return [
        f"cartera evaluada: {pesos(s['pesos_evaluados'])}",
        f"fuera de muestra: Sharpe {m['sharpe_oos']:.2f}, retorno anualizado "
        f"{pct(m['retorno_anualizado'])}, volatilidad {pct(m['volatilidad_anualizada'])}, "
        f"caída máxima {pct(m['max_drawdown'])}",
    ]


def _market_analyst(s: Mapping[str, Any]) -> list[str]:
    views = s["market_views"]["views"]
    if not views:
        return ["sin views: el posterior sería el equilibrio"]
    return [
        f"view {v['tipo']} {v['coeficientes']}: {v['q_anual'] * 100:+g} % anual, "
        f"confianza {v['confianza']:g}"
        for v in views
    ]


def _convocar_comite(s: Mapping[str, Any]) -> list[str]:
    lineas = [f"corrida {s['run_id']}: {s['iteraciones']} iteración(es), acta en {s['acta']}"]
    if s.get("recomendacion"):
        r = s["recomendacion"]
        lineas.append(f"cartera {r['candidato']}: {pesos(r['pesos'])}")
    if s.get("metricas_oos"):
        m = s["metricas_oos"]
        lineas.append(
            f"fuera de muestra: Sharpe {m['sharpe_oos']:.2f}, retorno anualizado "
            f"{pct(m['retorno_anualizado'])}, volatilidad {pct(m['volatilidad_anualizada'])}, "
            f"caída máxima {pct(m['max_drawdown'])}"
        )
    return lineas


CIFRAS_CLAVE: Mapping[str, Callable[[Mapping[str, Any]], list[str]]] = {
    "estimar_mercado": _estimar_mercado,
    "construir_candidatos": _construir_candidatos,
    "diagnosticar_cartera": _diagnosticar_cartera,
    "market_analyst": _market_analyst,
    "convocar_comite": _convocar_comite,
}


def construir_ficha(
    herramienta: str, salida: Mapping[str, Any], sello_vigente: str | None = None
) -> str | None:
    """La ficha de ``salida``, o ``None`` si no es un resultado con ``validado`` (o falló).

    ``sello_vigente`` se usa solo si la salida no trae su propio ``universe_version``.
    """
    if salida.get("status") != "success" or not isinstance(salida.get("validado"), bool):
        return None
    validado: bool = salida["validado"]
    if herramienta == "convocar_comite":
        etiqueta = ETIQUETA_FICHA_COMITE if validado else ETIQUETA_FICHA_COMITE_SIN_APROBAR
    else:
        etiqueta = ETIQUETA_FICHA_EXPLORATORIA
    sello = salida.get("universe_version") or sello_vigente
    prefijo = "" if validado else PREFIJO_NO_VALIDADO
    cifras = CIFRAS_CLAVE[herramienta](salida) if herramienta in CIFRAS_CLAVE else []
    return "\n".join(
        [
            f"**Ficha de origen — {etiqueta}**",
            f"- Fuente: **{ATIENDE[herramienta].value}** · herramienta `{herramienta}` · "
            f"universo `{sello[:12] if sello else 'sin sello'}`",
            *(f"- {prefijo}{linea}" for linea in cifras),
        ]
    )
