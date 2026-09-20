"""Demo de S11 (sin LLM): Plan de Compra Neta desde un aporte SIMULADO, con No-Trade Zones activas,
filtro tributario consultivo y un Override registrado en el acta operativa.

    uv run python scripts/demo_plan_compra.py --aporte 500 --run 20260919T184929_955370Z \
        --costo-base VOOG=5200 IBIT=900 --forzar VOOG:vender_hasta_banda

La cartera objetivo es la APROBADA en el acta del comité indicada; la cartera actual, la de
``config.yaml``. Pasa por las MISMAS operaciones que usa el Director (``plan_compra`` y
``forzar_orden``), en dos turnos, para que la custodia del Override sea la real. Los costos de
adquisición de ``--costo-base`` son simulados: los reales van en ``config.yaml``.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.sessions import InMemorySessionService
from google.adk.tools import ToolContext
from google.genai import types

from investmentsys.agents.anexos import SEPARADOR
from investmentsys.config import RAIZ_PROYECTO, Config, cargar_config
from investmentsys.contracts import RunState
from investmentsys.data_manager import GestorDatos
from investmentsys.orchestrator import ARCHIVO_RUN_STATE
from investmentsys.tools.estado import CLAVE_RUN_STATE, CLAVE_UNIVERSO
from investmentsys.tools.ficha import CLAVE_ANEXO
from investmentsys.tools.fintual import GestorFintualTools
from investmentsys.tools.plan_operativo import PlanOperativoTools


def _config(costos: dict[str, float]) -> Config:
    config = cargar_config()
    if not costos:
        return config
    tributario = config.fintual.tributario.model_copy(update={"costo_base_usd": costos})
    fintual = config.fintual.model_copy(update={"tributario": tributario})
    return config.model_copy(update={"fintual": fintual})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aporte", type=float, default=500.0)
    parser.add_argument("--dividendos", type=float, default=0.0)
    parser.add_argument("--run", required=True, help="run_id de un acta aprobada en runs/")
    parser.add_argument("--costo-base", nargs="*", default=[], metavar="TICKER=USD")
    parser.add_argument("--forzar", help="id de un escenario: simula el Override del usuario")
    parser.add_argument("--salida", type=Path, default=Path("runs/demos/s11_plan_compra"))
    args = parser.parse_args()

    config = _config({k: float(v) for k, v in (par.split("=") for par in args.costo_base)})
    runs = RAIZ_PROYECTO / config.corridas.directorio
    acta = RunState.model_validate_json((runs / args.run / ARCHIVO_RUN_STATE).read_text("utf-8"))
    estado = {
        CLAVE_UNIVERSO: acta.universo.model_dump(mode="json"),
        CLAVE_RUN_STATE: acta.model_dump(mode="json"),
    }
    sesiones = InMemorySessionService()
    sesion = asyncio.run(sesiones.create_session(app_name="demo", user_id="demo", state=estado))

    def turno(invocacion: str, dicho: str) -> ToolContext:
        contenido = types.Content(role="user", parts=[types.Part(text=dicho)])
        sesion.events.append(Event(invocation_id=invocacion, author="user", content=contenido))
        contexto = InvocationContext(
            session_service=sesiones,
            invocation_id=invocacion,
            agent=LlmAgent(name="relleno"),
            session=sesion,
        )
        return ToolContext(contexto)

    operativo = PlanOperativoTools(config, RAIZ_PROYECTO / args.salida)
    gestor = GestorFintualTools(GestorDatos(config), config, operativo)
    dicho = f"Aporté {args.aporte:g} dólares" + (
        f" y me acreditaron {args.dividendos:g} de dividendos." if args.dividendos else "."
    )
    print(f"» Usuario: {dicho}\n")
    plan = gestor.gestionar_datos_y_fricciones(
        "plan_compra",
        turno("turno-1", dicho),
        aporte_usd=args.aporte,
        dividendos_usd=args.dividendos or None,
    )
    if plan["status"] != "success":
        raise SystemExit(f"{plan['status']}: {plan.get('motivo') or plan.get('mensaje')}")
    print(plan[CLAVE_ANEXO])
    print(f"\n_Acta operativa: {plan['acta_operativa']}_")
    if args.forzar:
        print(f"{SEPARADOR}» Usuario: Entiendo la advertencia. Fuerza `{args.forzar}`.\n")
        forzado = gestor.gestionar_datos_y_fricciones(
            "forzar_orden",
            turno("turno-2", f"fuerza {args.forzar}"),
            escenario=args.forzar,
            token=plan["token"],
        )
        if forzado["status"] != "success":
            raise SystemExit(f"{forzado['status']}: {forzado.get('motivo')}")
        print(forzado[CLAVE_ANEXO])


if __name__ == "__main__":
    main()
