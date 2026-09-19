"""Demo del DoD de S8: una sesión completa con el Director contra Gemini REAL.

    uv run python scripts/demo_director.py

A (consulta) → B (mesa de trabajo) → alta de una acción (automática) → alta de un ETF
(elicitación del prior) → C (solicitar / resumen / confirmación / ejecutar) → acta.

Corre en un mundo aislado (almacén sembrado + fuente de mercado falsa, como el evalset): no toca
`data/` ni Tiingo. La transcripción y el acta quedan en `runs/demos/director_<marca>/`.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from investmentsys.config import RAIZ_PROYECTO, cargar_config

sys.path.insert(0, str(RAIZ_PROYECTO))  # el mundo aislado vive en tests/almacen.py

from tests.almacen import mundo_director

from investmentsys.contracts import RunState
from investmentsys.evaluacion.director import conversar
from investmentsys.orchestrator import ARCHIVO_RUN_STATE

SESION = (
    "hola",
    "¿qué correlación hay entre VOOG y VB?",
    "creo que la banca canadiense lo va a hacer bien los próximos 12 meses por la baja de "
    "provisiones; pide views al analista con eso y propón una cartera",
    "agrega AAPL",
    "sí, confirmo: incorpórala",
    "agrega QQQ",
    "la opción a: la capitalización del Nasdaq-100, el índice subyacente, es de 22 billones de "
    "dólares (22 en tus unidades de 10^12). Incorpóralo con eso",
    "convoca al comité",
    "sí, confirmo: ejecuta el comité con ese resumen",
)


def main() -> None:
    load_dotenv(RAIZ_PROYECTO / ".env")
    config = cargar_config()
    raiz = Path(tempfile.mkdtemp(prefix="demo_director_"))
    mundo = mundo_director(raiz, config)
    turnos = asyncio.run(conversar(mundo, SESION))

    lineas = ["# Demo del Director (S8)", ""]
    for turno in turnos:
        lineas += [f"## Usuario: {turno.usuario}", ""]
        lineas += [f"- `{n}({json.dumps(a, ensure_ascii=False)})`" for n, a in turno.llamadas]
        lineas += [
            f"- ← `{n}`: status={r.get('status')} validado={r.get('validado')} "
            f"{r.get('motivo') or r.get('mensaje') or ''}"
            for n, r in turno.respuestas
        ]
        lineas += ["", turno.texto, ""]
    destino = (
        RAIZ_PROYECTO
        / config.corridas.directorio
        / "demos"
        / f"director_{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    )
    destino.mkdir(parents=True)
    (destino / "transcripcion.md").write_text("\n".join(lineas), encoding="utf-8")

    actas = sorted(mundo.runs.iterdir()) if mundo.runs.is_dir() else []
    if not actas:
        sys.exit(f"la sesión terminó SIN acta; transcripción en {destino}")
    shutil.copytree(actas[-1], destino / "acta")
    acta = RunState.model_validate_json((actas[-1] / ARCHIVO_RUN_STATE).read_text("utf-8"))
    assert acta.aprobacion is not None, "el acta no registra la aprobación del usuario"
    reporte = acta.reporte_markdown or ""
    print(f"Transcripción y acta en {destino.relative_to(RAIZ_PROYECTO)}/")
    print(
        f"- etapa: {acta.etapa.value}; aprobado: {acta.aprobado}; "
        f"iteraciones: {len(acta.candidatos)}"
    )
    print(f"- universo {acta.universo.version[:12]}: {', '.join(acta.activos)}")
    procedencias = acta.aprobacion.resumen.procedencias_prior
    print(f"- procedencias: { {a: p.value for a, p in procedencias.items()} }")
    sesion = acta.restricciones_sesion
    print(f"- restricciones: piso {sesion.peso_min.valor}, techo {sesion.peso_max.valor}")
    print(f"- tabla π en el informe: {'Prior de equilibrio' in reporte}")
    print(
        f"- resumen aprobado en el acta: {acta.aprobacion.solicitado_en} → "
        f"{acta.aprobacion.confirmado_en}; sección en el informe: "
        f"{'Aprobación del usuario' in reporte}"
    )


if __name__ == "__main__":
    main()
