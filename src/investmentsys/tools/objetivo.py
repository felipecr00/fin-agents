"""La cartera OBJETIVO de la sesión: la que está en juego sobre la mesa (S10, ADR-019/020).

La leen el Escéptico cuando el usuario pregunta por «esta cartera» sin dar pesos y la operación
``montos`` del Gestor. Nunca llega por argumentos de un LLM: sale de los contratos sellados del
estado. Una cartera aprobada por el comité sobre el universo vigente manda sobre una propuesta
exploratoria del Constructor.
"""

from __future__ import annotations

from dataclasses import dataclass

from investmentsys.contracts import CandidatePortfolios, RunState, Universe
from investmentsys.tools.estado import (
    CLAVE_CANDIDATOS,
    CLAVE_RUN_STATE,
    CLAVE_UNIVERSO,
    EstadoLegible,
    FaltaEnEstadoError,
    leer,
    leer_lista,
)

SIN_CARTERA = (
    "no hay una cartera vigente sobre la mesa: primero hay que construir candidatos (o convocar "
    "al comité), o que el usuario indique los pesos de la cartera que quiere evaluar"
)


@dataclass(frozen=True)
class CarteraObjetivo:
    pesos: dict[str, float]
    validado: bool
    origen: str
    universe_version: str


def cartera_objetivo(estado: EstadoLegible) -> CarteraObjetivo:
    """Lanza ``FaltaEnEstadoError`` si nada vigente sirve de objetivo."""
    vigente = leer(estado, CLAVE_UNIVERSO, Universe).version
    crudo = estado.get(CLAVE_RUN_STATE)
    if crudo is not None:
        corrida = RunState.model_validate(crudo)
        cartera = corrida.portafolio_final
        if cartera is not None and corrida.universo.version == vigente:
            return CarteraObjetivo(
                pesos=dict(cartera.pesos),
                validado=True,
                origen=f"cartera {cartera.nombre} aprobada por el comité ({corrida.run_id})",
                universe_version=vigente,
            )
    rondas = [
        r
        for r in leer_lista(estado, CLAVE_CANDIDATOS, CandidatePortfolios)
        if r.universe_version == vigente
    ]
    if not rondas:
        raise FaltaEnEstadoError(SIN_CARTERA)
    recomendada = rondas[-1].portafolio_recomendado
    return CarteraObjetivo(
        pesos=dict(recomendada.pesos),
        validado=False,
        origen=f"cartera {recomendada.nombre} propuesta por el Constructor (exploratoria)",
        universe_version=vigente,
    )
