"""Comparación de corridas (diff estructurado entre dos ``RunState``). Sin ADK ni LLM."""

from investmentsys.comparacion.corridas import (
    Cambio,
    CambioCriterio,
    CambioTexto,
    CambioView,
    CorridasIncomparablesError,
    DiffCorridas,
    DiffViews,
    ViewNormalizada,
    cartera_de,
    comparar_corridas,
    normalizar_view,
)
from investmentsys.comparacion.informe import diff_markdown

__all__ = [
    "Cambio",
    "CambioCriterio",
    "CambioTexto",
    "CambioView",
    "CorridasIncomparablesError",
    "DiffCorridas",
    "DiffViews",
    "ViewNormalizada",
    "cartera_de",
    "comparar_corridas",
    "diff_markdown",
    "normalizar_view",
]
