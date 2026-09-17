"""Repetición determinista de una corrida (ADR-009): ¿el núcleo local da los mismos números?

Lo que decidió el LLM (views, candidato recomendado, máximos endurecidos) se toma del
``RunState`` como dato; todo lo demás se recalcula con los mismos tools que usa el pipeline:

- ``quant_estimates``: siempre.
- Validación: todas las rondas (solo depende de los pesos del candidato recomendado).
- Optimización: la última ronda. ``RunState`` guarda las restricciones vigentes al final, no
  las de cada ronda, así que las anteriores no se pueden reconstruir y se informan como tales.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

from google.adk.tools.tool_context import ToolContext

from investmentsys.config import Config, hash_config
from investmentsys.contracts import RunState
from investmentsys.data import PriceProvider
from investmentsys.tools import (
    CLAVE_CANDIDATOS,
    CLAVE_FECHA_DECISION,
    CLAVE_MARKET_VIEWS,
    CLAVE_QUANT_ESTIMATES,
    CLAVE_RESTRICCIONES,
    CLAVE_VALIDACIONES,
    NucleoTools,
)
from investmentsys.tools.estado import volcar


class ReplayImposibleError(RuntimeError):
    """La corrida no se puede repetir aquí: otra configuración, o un tool devolvió error."""


@dataclass(frozen=True)
class Diferencia:
    ruta: str
    remoto: Any
    local: Any

    @property
    def desviacion(self) -> float:
        """Diferencia absoluta si ambos son números; infinito si difieren en otra cosa."""
        if _es_numero(self.remoto) and _es_numero(self.local):
            return abs(float(self.remoto) - float(self.local))
        return math.inf


@dataclass(frozen=True)
class ResultadoReplay:
    comparados: int
    desviacion_maxima: float
    diferencias: tuple[Diferencia, ...]  # solo las que superan la tolerancia
    no_repetible: tuple[str, ...]

    @property
    def reproduce(self) -> bool:
        return not self.diferencias


def _es_numero(valor: Any) -> bool:
    return isinstance(valor, int | float) and not isinstance(valor, bool)


def _comparar(remoto: Any, local: Any, ruta: str) -> list[Diferencia]:
    """Todas las hojas numéricas (con su desviación) y las no numéricas que difieren."""
    if isinstance(remoto, dict) and isinstance(local, dict) and remoto.keys() == local.keys():
        return [d for k in remoto for d in _comparar(remoto[k], local[k], f"{ruta}.{k}")]
    if isinstance(remoto, list) and isinstance(local, list) and len(remoto) == len(local):
        pares = zip(remoto, local, strict=True)
        return [d for i, (r, x) in enumerate(pares) for d in _comparar(r, x, f"{ruta}[{i}]")]
    if (_es_numero(remoto) and _es_numero(local)) or remoto != local:
        return [Diferencia(ruta, remoto, local)]
    return []


def _contexto(estado: dict[str, Any]) -> ToolContext:
    """Los tools solo usan ``.state``: basta un objeto con ese atributo, sin sesión de ADK."""
    return cast(ToolContext, SimpleNamespace(state=estado))


def _exigir(salida: dict[str, Any], paso: str) -> None:
    if salida.get("status") != "success":
        raise ReplayImposibleError(f"{paso}: {salida.get('tipo')}: {salida.get('mensaje')}")


def repetir(corrida: RunState, config: Config, provider: PriceProvider) -> ResultadoReplay:
    if corrida.semilla != config.reproducibilidad.semilla or corrida.config_hash != hash_config():
        raise ReplayImposibleError(
            "la corrida usó otra semilla u otro config.yaml: "
            f"semilla {corrida.semilla}, config_hash {corrida.config_hash[:12]}…"
        )
    tools = NucleoTools(config, provider)
    remoto = corrida.model_dump(mode="json")
    hallazgos: list[Diferencia] = []
    no_repetible: list[str] = []

    base: dict[str, Any] = {
        CLAVE_FECHA_DECISION: corrida.fecha_decision.isoformat(),
        CLAVE_MARKET_VIEWS: remoto["market_views"],
    }
    if corrida.quant_estimates is not None:
        _exigir(tools.estimar_mercado(_contexto(base)), "quant")
        hallazgos += _comparar(
            remoto["quant_estimates"], base[CLAVE_QUANT_ESTIMATES], "quant_estimates"
        )

    ultima = len(corrida.candidatos)
    for i, ronda in enumerate(corrida.candidatos, start=1):
        estado = {
            **base,
            CLAVE_CANDIDATOS: remoto["candidatos"][:i],
            CLAVE_VALIDACIONES: remoto["validaciones"][: i - 1],
        }
        ctx = _contexto(estado)
        if i < ultima:
            no_repetible.append(
                f"candidatos[{i - 1}]: RunState no guarda las restricciones de la ronda {i}"
            )
        elif corrida.market_views is not None and corrida.restricciones is not None:
            estado[CLAVE_CANDIDATOS] = remoto["candidatos"][: i - 1]
            maximos = {a: lim[1] for a, lim in corrida.restricciones.limites_por_activo.items()}
            salida = tools.construir_candidatos(ctx, ronda.recomendado, maximos)
            _exigir(salida, f"constructor (ronda {i})")
            hallazgos += _comparar(
                remoto["restricciones"], estado[CLAVE_RESTRICCIONES], "restricciones"
            )
            hallazgos += _comparar(
                volcar(ronda), estado[CLAVE_CANDIDATOS][-1], f"candidatos[{i - 1}]"
            )
            # La validación se repite sobre los pesos REMOTOS: aísla cada etapa.
            estado[CLAVE_CANDIDATOS] = remoto["candidatos"][:i]
        if i <= len(corrida.validaciones):
            _exigir(tools.validar_candidato(ctx), f"validador (ronda {i})")
            hallazgos += _comparar(
                remoto["validaciones"][i - 1],
                estado[CLAVE_VALIDACIONES][-1],
                f"validaciones[{i - 1}]",
            )

    tolerancia = config.reproducibilidad.tolerancia_replay
    numericas = [d.desviacion for d in hallazgos if math.isfinite(d.desviacion)]
    return ResultadoReplay(
        comparados=len(hallazgos),
        desviacion_maxima=max(numericas, default=0.0),
        diferencias=tuple(d for d in hallazgos if d.desviacion > tolerancia),
        no_repetible=tuple(no_repetible),
    )
