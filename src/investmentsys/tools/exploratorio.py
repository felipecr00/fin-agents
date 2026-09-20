"""Fuera del comité todo resultado es EXPLORATORIO, y lo dice el dato (ADR-014).

``exploratorio`` envuelve un tool del núcleo sin modificarlo: mismo nombre, firma y docstring,
con ``validado: false`` en la salida. Lo usan el Director (Constructor) y las personas thin
(Estadístico, S10): la etiqueta no depende de quién redacte.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from google.adk.tools.tool_context import ToolContext

from investmentsys.contracts import QuantEstimates
from investmentsys.tools.estado import CLAVE_QUANT_ESTIMATES

ETIQUETA_EXPLORATORIO = "exploratorio"


def exploratorio(
    tool: Callable[..., dict[str, Any]],
    antes: Callable[[ToolContext], None] | None = None,
    anexo: Callable[[ToolContext], dict[str, Any]] | None = None,
) -> Callable[..., dict[str, Any]]:
    """El mismo tool (nombre, firma y docstring), con ``validado: false`` EN EL DATO.

    ``NucleoTools`` no se modifica: fuera del comité sus salidas son exploratorias y lo dicen
    en el contrato de salida, no solo en el texto que redacte un agente (ADR-014).
    """

    @functools.wraps(tool)
    def envuelto(*args: Any, tool_context: ToolContext, **kwargs: Any) -> dict[str, Any]:
        if antes is not None:
            antes(tool_context)
        salida = tool(*args, tool_context=tool_context, **kwargs)
        if salida.get("status") != "success":
            return salida
        extra = anexo(tool_context) if anexo is not None else {}
        return {**salida, **extra, "etiqueta": ETIQUETA_EXPLORATORIO, "validado": False}

    return envuelto


def correlaciones(ctx: ToolContext) -> dict[str, Any]:
    """Las correlaciones de las estimaciones recién guardadas, leídas del contrato.

    El resumen de ``estimar_mercado`` está pensado para el pipeline y no las trae; quien las
    cita las necesita. No se calcula nada aquí: es ``MatrizCovarianza.correlacion``.
    """
    estimaciones = QuantEstimates.model_validate(ctx.state[CLAVE_QUANT_ESTIMATES])
    metodo, cov = next(iter(estimaciones.covarianzas.items()))
    activos = estimaciones.activos
    return {
        "correlaciones": {
            f"{a}-{b}": cov.correlacion(a, b)
            for i, a in enumerate(activos)
            for b in activos[i + 1 :]
        },
        "correlaciones_metodo": str(metodo),
    }
