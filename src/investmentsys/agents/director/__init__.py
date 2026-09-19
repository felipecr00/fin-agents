"""Director de Análisis (LlmAgent conversacional sobre los especialistas y el comité)."""

from investmentsys.agents.director.agente import NOMBRE, crear_director, exploratorio
from investmentsys.agents.director.instruccion import INSTRUCCION, MARCADORES

__all__ = ["INSTRUCCION", "MARCADORES", "NOMBRE", "crear_director", "exploratorio"]
