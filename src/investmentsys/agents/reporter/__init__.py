"""Reporter: narrativa por LLM, cifras y tablas por código."""

from investmentsys.agents.reporter.agente import crear_reporter
from investmentsys.agents.reporter.reporte import (
    cifras_no_verificadas,
    hoja_de_hechos,
    renderizar,
)

__all__ = ["cifras_no_verificadas", "crear_reporter", "hoja_de_hechos", "renderizar"]
