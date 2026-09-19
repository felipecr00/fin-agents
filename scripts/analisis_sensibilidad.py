"""Análisis de sensibilidad del núcleo Black-Litterman (sin agentes ni LLM): `make sensibilidad`.

    uv run python scripts/analisis_sensibilidad.py [--run-state runs/<id>/run_state.json]

Por defecto usa las views del ejercicio de referencia y el último cierre de `data/series/`;
con `--run-state` usa las views y la fecha de decisión de una corrida real. Perturba un
supuesto a la vez según `config.yaml: sensibilidad`, con los límites de peso reales y con
límites relajados (0-100 %), y escribe en `runs/sensibilidad/<fecha>_<hash>/`:
`informe.md` y `sensibilidad.json` (todas las perturbaciones, en el contrato `Sensibilidad`).
Misma entrada = mismo directorio y mismo contenido.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from demo_pipeline import views_fijas

from investmentsys.config import RAIZ_PROYECTO, cargar_config, hash_config
from investmentsys.contracts import MarketViews, PortfolioConstraints, RunState
from investmentsys.data import provider_de_config
from investmentsys.quant import estimar
from investmentsys.risk.informe_sensibilidad import Escenario, informe_markdown
from investmentsys.risk.sensibilidad import PP, analizar_sensibilidad

SUBCARPETA = "sensibilidad"
LARGO_HASH = 8


def _views(ruta: Path | None, config_activos: tuple[str, ...]) -> tuple[MarketViews | None, str]:
    if ruta is None:
        return None, "ejercicio de referencia (CLAUDE.md)"
    estado = RunState.model_validate_json(ruta.read_text(encoding="utf-8"))
    if estado.market_views is None:
        raise SystemExit(f"{ruta}: la corrida no tiene market_views")
    if estado.activos != config_activos:
        raise SystemExit(f"{ruta}: universo {estado.activos} distinto al de config.yaml")
    return estado.market_views, f"corrida `{estado.run_id}`"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--run-state", type=Path, default=None, help="run_state.json de una corrida"
    )
    args = parser.parse_args()

    config = cargar_config()
    opt, activos = config.optimizacion, config.portafolio.activos
    provider = provider_de_config(config)
    views_corrida, origen = _views(args.run_state, activos)
    fecha = (
        views_corrida.fecha_decision
        if views_corrida
        else provider.precios(activos).index[-1].date()
    )
    views = views_corrida or views_fijas(fecha, activos)
    estimates = estimar(
        provider.retornos_log(activos, hasta=fecha),
        fecha_decision=fecha,
        periodos_por_anio=provider.periodos_por_anio,
        ventana_meses=config.datos.ventana_covarianza_meses,
        metodos=(opt.metodo_covarianza,),
        nivel_confianza=config.estimacion.nivel_confianza,
    )

    limites = {
        "Límites reales": (opt.peso_min, opt.peso_max),
        "Límites relajados": (0.0, 1.0),
    }
    escenarios = tuple(
        Escenario(
            nombre=nombre,
            limites=f"peso por activo entre {lo:.0%} y {hi:.0%}",
            analisis=analizar_sensibilidad(
                estimates,
                views,
                PortfolioConstraints(activos=activos, peso_min=lo, peso_max=hi),
                opt,
                config.prior_equilibrio,
                config.sensibilidad,
            ),
        )
        for nombre, (lo, hi) in limites.items()
    )

    s = config.sensibilidad
    rejilla = (
        f"retornos ± {', '.join(f'{m * PP:g}' for m in s.retornos_pp)} p.p.; covarianzas ± "
        f"{', '.join(f'{m:.0%}' for m in s.covarianza_rel)}; δ y τ ± "
        f"{', '.join(f'{m:.0%}' for m in s.parametros_rel)}"
    )
    config_hash = hash_config()
    destino = (
        RAIZ_PROYECTO
        / config.corridas.directorio
        / SUBCARPETA
        / f"{fecha}_{config_hash[:LARGO_HASH]}"
    )
    if args.run_state:
        destino = destino.with_name(f"{destino.name}_{args.run_state.parent.name}")
    destino.mkdir(parents=True, exist_ok=True)
    informe = informe_markdown(escenarios, views, origen, config_hash, rejilla)
    (destino / "informe.md").write_text(informe, encoding="utf-8")
    datos = {
        e.nombre: {
            "pesos_base": e.analisis.pesos_base,
            "limites_activos": e.analisis.limites_activos,
            "perturbaciones": [p.a_contrato().model_dump() for p in e.analisis.perturbaciones],
            "omitidas": e.analisis.omitidas,
        }
        for e in escenarios
    }
    (destino / "sensibilidad.json").write_text(
        json.dumps(datos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(informe)
    print(f"Guardado en {destino.relative_to(RAIZ_PROYECTO)}/")


if __name__ == "__main__":
    main()
