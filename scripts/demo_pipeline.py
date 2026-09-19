"""Demo del pipeline encadenado a mano, sin agentes ni LLM.

    uv run python scripts/demo_pipeline.py [--fecha AAAA-MM-DD] [--sin-costos]

Cadena: cargar precios → covarianza y retornos (`quant.estimar`) → Black-Litterman con las
views fijas del ejercicio de referencia → `risk.validar` → veredicto impreso.
Todo parámetro sale de `config.yaml`; la fecha de decisión por defecto es el último cierre.
"""

from __future__ import annotations

import argparse
import math
from datetime import date

from investmentsys.config import Config, cargar_config
from investmentsys.contracts import (
    DISCLAIMER,
    CandidatePortfolio,
    MarketViews,
    MetodoCovarianza,
    PortfolioConstraints,
    QuantEstimates,
    TipoView,
    ValidationReport,
    View,
)
from investmentsys.data import provider_de_config
from investmentsys.portfolio import optimizar_black_litterman
from investmentsys.quant import estimar
from investmentsys.risk import validar


def views_fijas(fecha: date, activos: tuple[str, ...]) -> MarketViews:
    """Las tres views del ejercicio de referencia (CLAUDE.md)."""
    fuente = "ejercicio de referencia"
    return MarketViews(
        fecha_decision=fecha,
        activos=activos,
        horizonte_meses=12,
        resumen="Crecimiento sólido en large caps, banca canadiense favorable, cripto neutral.",
        views=(
            View(
                tipo=TipoView.ABSOLUTA,
                coeficientes={"IBIT": 1.0},
                q_anual=0.03,
                confianza=0.5,
                justificacion="Sin catalizadores claros; retorno total neutral cercano al 3 %.",
                fuente=fuente,
            ),
            View(
                tipo=TipoView.RELATIVA,
                coeficientes={"VOOG": 1.0, "VB": -1.0},
                q_anual=0.03,
                confianza=0.5,
                justificacion="Large growth debería superar a small caps por unos 3 puntos.",
                fuente=fuente,
            ),
            View(
                tipo=TipoView.ABSOLUTA,
                coeficientes={"BNS": 1.0},
                q_anual=0.10,
                confianza=0.5,
                justificacion="Banca canadiense con valoración atractiva; retorno total del 10 %.",
                fuente=fuente,
            ),
        ),
    )


def imprimir_estimaciones(est: QuantEstimates, metodo: MetodoCovarianza) -> None:
    cov = est.covarianza(metodo)
    nivel = est.retornos_historicos[0].nivel_confianza
    print(
        f"\n[2] Estimaciones ({metodo}, ventana {cov.ventana_meses} m, "
        f"hasta {est.fecha_fin_muestra})"
    )
    cabecera = f"{'activo':6s} {'obs':>4s} {'vol anual':>10s} {'ret. hist.':>11s}"
    print(f"    {cabecera}  intervalo {nivel:.0%}")
    for r in est.retornos_historicos:
        print(
            f"    {r.activo:6s} {cov.observaciones_por_activo[r.activo]:4d} "
            f"{cov.volatilidad(r.activo):10.1%} {r.media_anual:11.1%}  "
            f"[{r.intervalo_inferior:+.1%}, {r.intervalo_superior:+.1%}]"
        )
    print("    correlaciones:")
    n = len(est.activos)
    for i in range(n):
        fila = " ".join(
            f"{cov.valores[i][j] / math.sqrt(cov.valores[i][i] * cov.valores[j][j]):6.2f}"
            for j in range(n)
        )
        print(f"      {est.activos[i]:6s} {fila}")


def imprimir_candidato(c: CandidatePortfolio, views: MarketViews) -> None:
    print(f"\n[3] Black-Litterman con {len(views.views)} views fijas → candidato '{c.nombre}'")
    for v in views.views:
        print(f"    view {v.tipo.value:8s} {v.coeficientes} q={v.q_anual:+.0%}")
    print("    pesos:", "  ".join(f"{a}={p:.1%}" for a, p in c.pesos.items()))
    print(
        f"    ex ante: retorno {c.metricas.retorno_esperado_anual:.1%}, vol "
        f"{c.metricas.volatilidad_anual:.1%}, Sharpe {c.metricas.sharpe:.2f}, "
        f"HHI {c.metricas.concentracion_hhi:.3f}"
    )
    if c.retornos_esperados:
        print(
            "    μ posterior:", "  ".join(f"{a}={m:.1%}" for a, m in c.retornos_esperados.items())
        )


def imprimir_veredicto(r: ValidationReport) -> None:
    m = r.metricas_oos
    print(
        f"\n[4] Validación walk-forward {m.fecha_inicio} → {m.fecha_fin} ({m.n_periodos} períodos)"
    )
    print(
        f"    OOS: retorno {m.retorno_anualizado:.1%}, vol {m.volatilidad_anualizada:.1%}, "
        f"Sharpe {m.sharpe_oos:.2f}, max DD {m.max_drawdown:.1%}, "
        f"turnover {m.turnover_anual:.2f}/año, costos {m.costo_transaccion_total * 1e4:.1f} p.b."
    )
    print("    criterios:")
    for c in r.criterios:
        marca = "OK " if c.cumple else "NO "
        print(f"      {marca} {c.nombre:26s} {c.valor:8.4f} vs {c.umbral:<6}  {c.detalle}")
    print("    stress:")
    for s in r.stress:
        marca = "OK " if s.superado else "NO "
        print(
            f"      {marca} {s.escenario:16s} {s.fecha_inicio} → {s.fecha_fin}: "
            f"retorno {s.retorno_periodo:+.1%}, max DD {s.max_drawdown:.1%}"
        )
    print(f"    look-ahead verificado: {r.look_ahead_verificado}")
    print(f"\n[5] VEREDICTO: {r.veredicto.value}")
    for razon in r.razones_rechazo:
        print(f"    razón: {razon}")
    for sugerencia in r.sugerencias:
        print(f"    sugerencia: {sugerencia}")


def correr(config: Config, fecha: date | None, costo_bps: float | None) -> ValidationReport:
    provider = provider_de_config(config)
    activos = config.portafolio.activos
    precios = provider.precios(activos, hasta=fecha)
    fecha = fecha or precios.index[-1].date()
    print(
        f"[1] Precios: {provider.directorio} — {len(precios)} cierres hasta {fecha}, "
        f"activos {activos}"
    )

    est = estimar(
        provider.retornos_log(activos, hasta=fecha),
        fecha_decision=fecha,
        periodos_por_anio=provider.periodos_por_anio,
        ventana_meses=config.datos.ventana_covarianza_meses,
        metodos=(config.optimizacion.metodo_covarianza,),
        nivel_confianza=config.estimacion.nivel_confianza,
    )
    imprimir_estimaciones(est, config.optimizacion.metodo_covarianza)

    restricciones = PortfolioConstraints(
        activos=activos,
        peso_min=config.optimizacion.peso_min,
        peso_max=config.optimizacion.peso_max,
        permitir_cortos=config.optimizacion.permitir_cortos,
    )
    views = views_fijas(fecha, activos)
    candidato = optimizar_black_litterman(
        est, views, restricciones, config.optimizacion, config.prior_equilibrio
    )
    imprimir_candidato(candidato, views)

    validacion = config.validacion
    if costo_bps is not None:
        validacion = validacion.model_copy(update={"costo_transaccion_bps": costo_bps})
    reporte = validar(
        candidato,
        precios,
        fecha_decision=fecha,
        iteracion=1,
        validacion=validacion,
        optimizacion=config.optimizacion,
        periodos_por_anio=provider.periodos_por_anio,
        semilla=config.reproducibilidad.semilla,
    )
    imprimir_veredicto(reporte)
    print(f"\n{DISCLAIMER}")
    return reporte


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--fecha", type=date.fromisoformat, default=None, help="fecha de decisión (AAAA-MM-DD)"
    )
    parser.add_argument(
        "--sin-costos", action="store_true", help="costo de transacción 0 en el backtest"
    )
    args = parser.parse_args()
    correr(cargar_config(), args.fecha, 0.0 if args.sin_costos else None)


if __name__ == "__main__":
    main()
