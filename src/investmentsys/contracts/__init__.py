"""Contratos Pydantic: única forma válida de comunicación entre agentes."""

from investmentsys.contracts.common import DISCLAIMER, ContractBase, Fraccion, Ticker
from investmentsys.contracts.constraints import PortfolioConstraints
from investmentsys.contracts.estimates import (
    MatrizCovarianza,
    MetodoCovarianza,
    QuantEstimates,
    RegimenMercado,
    RetornoEsperado,
)
from investmentsys.contracts.portfolios import (
    CandidatePortfolio,
    CandidatePortfolios,
    MetricasExAnte,
    Sensibilidad,
    TecnicaOptimizacion,
)
from investmentsys.contracts.run_state import EtapaCorrida, RunState
from investmentsys.contracts.validation import (
    Criterio,
    MetricasOOS,
    ResultadoStress,
    ValidationReport,
    Veredicto,
)
from investmentsys.contracts.views import MarketViews, TipoView, View

__all__ = [
    "DISCLAIMER",
    "CandidatePortfolio",
    "CandidatePortfolios",
    "ContractBase",
    "Criterio",
    "EtapaCorrida",
    "Fraccion",
    "MarketViews",
    "MatrizCovarianza",
    "MetodoCovarianza",
    "MetricasExAnte",
    "MetricasOOS",
    "PortfolioConstraints",
    "QuantEstimates",
    "RegimenMercado",
    "ResultadoStress",
    "RetornoEsperado",
    "RunState",
    "Sensibilidad",
    "TecnicaOptimizacion",
    "Ticker",
    "TipoView",
    "ValidationReport",
    "Veredicto",
    "View",
]
