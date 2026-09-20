"""Evalset del Director contra el modelo REAL (ADR-015): `make eval-director [CASOS="id1 id2"]`.

    uv run python scripts/eval_director.py [id_de_caso ...]

Cada caso corre en un mundo aislado (almacén sembrado + fuente de mercado falsa): no toca
`data/`, `runs/` ni Tiingo. Guarda en `runs/evals/director_<marca>/` el resumen por caso y las
conversaciones completas, y termina con código 1 si algún caso falla.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from investmentsys.config import RAIZ_PROYECTO, cargar_config

sys.path.insert(0, str(RAIZ_PROYECTO))  # el mundo de los casos vive en tests/almacen.py

from tests.almacen import mundo_director

from investmentsys.evaluacion.criterios_director import TurnoObservado
from investmentsys.evaluacion.director import (
    LIMITE_POR_CASO_S,
    Caso,
    cargar_casos,
    correr_caso,
)
from investmentsys.evaluacion.informe import CasoEvaluado, a_markdown

CASOS = RAIZ_PROYECTO / "tests" / "eval" / "casos_director.yaml"
SUBCARPETA = "evals"
EN_PARALELO = 4  # mundos aislados: el límite es la cuota del modelo, no la corrección


def _conversacion(caso: Caso, turnos: list[TurnoObservado]) -> str:
    lineas = [f"## {caso.id}", ""]
    for turno in turnos:
        lineas += [f"**Usuario:** {turno.usuario}", ""]
        lineas += [
            f"- `{nombre}({json.dumps(args, ensure_ascii=False)})`"
            for nombre, args in turno.llamadas
        ]
        lineas += [
            f"- ← `{nombre}`: status={r.get('status')} {r.get('motivo') or r.get('mensaje') or ''}"
            for nombre, r in turno.respuestas
        ]
        # S10: las personas hablan ANTES del cierre del Director, y con su propia voz.
        lineas += ["", *(f"**{persona} (persona):** {texto}\n" for persona, texto in turno.voces)]
        lineas += [f"**Director:** {turno.texto}", ""]
    return "\n".join(lineas)


async def _correr(casos: list[Caso]) -> list[tuple[CasoEvaluado, str]]:
    config = cargar_config()
    semaforo = asyncio.Semaphore(EN_PARALELO)

    async def uno(caso: Caso) -> tuple[CasoEvaluado, str]:
        async with semaforo:
            raiz = Path(tempfile.mkdtemp(prefix=f"eval_{caso.id}_"))
            try:
                evaluado, turnos = await asyncio.wait_for(
                    correr_caso(caso, lambda: mundo_director(raiz, config)), LIMITE_POR_CASO_S
                )
            except Exception as exc:  # un caso que revienta es un caso fallido, no un aborto
                sin_evaluar = CasoEvaluado(eval_id=caso.id, aprobado=False, nota=None, criterios=())
                print(f"❌ {caso.id} (no terminó: {type(exc).__name__})", flush=True)
                return sin_evaluar, f"## {caso.id}\n\nNo terminó: {type(exc).__name__}: {exc}\n"
            print(f"{'✅' if evaluado.aprobado else '❌'} {caso.id}", flush=True)
            return evaluado, _conversacion(caso, turnos)

    return list(await asyncio.gather(*(uno(c) for c in casos)))


def main() -> None:
    load_dotenv(RAIZ_PROYECTO / ".env")
    todos = cargar_casos(CASOS)
    pedidos = set(sys.argv[1:])
    desconocidos = pedidos - {c.id for c in todos.casos}
    if desconocidos:
        sys.exit(f"casos desconocidos: {sorted(desconocidos)}")
    casos = [c for c in todos.casos if not pedidos or c.id in pedidos]
    config = cargar_config()
    resultados = asyncio.run(_correr(casos))
    evaluados = [e for e, _ in resultados]
    informe = a_markdown(
        evaluados, f"Evals de {todos.eval_set_id} — modelo {config.inferencia.nivel_1.modelo}"
    )
    marca = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destino = RAIZ_PROYECTO / config.corridas.directorio / SUBCARPETA / f"director_{marca}"
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "resumen.md").write_text(informe, encoding="utf-8")
    (destino / "conversaciones.md").write_text(
        "\n\n".join(texto for _, texto in resultados), encoding="utf-8"
    )
    print(informe)
    print(f"Guardado en {destino.relative_to(RAIZ_PROYECTO)}/")
    if not all(e.aprobado for e in evaluados):
        sys.exit(1)


if __name__ == "__main__":
    main()
