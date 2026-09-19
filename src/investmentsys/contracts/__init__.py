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
from investmentsys.contracts.prior import (
    ADVERTENCIA_PRIOR_NEUTRAL,
    ADVERTENCIA_PRIOR_SOLO_VIEWS,
    MetodoPrior,
    PriorActivo,
    PriorSnapshot,
)
from investmentsys.contracts.run_state import EtapaCorrida, RunState
from investmentsys.contracts.session import (
    LimiteActivo,
    LimiteGlobal,
    OrigenRestriccion,
    SessionConstraints,
)
from investmentsys.contracts.universe import (
    AssetDiagnostic,
    EstadoPrior,
    Frecuencia,
    OrigenActivo,
    PriorProvenance,
    Universe,
    UniverseVersion,
)
from investmentsys.contracts.validation import (
    Criterio,
    MetricasOOS,
    ResultadoStress,
    ValidationReport,
    Veredicto,
)
from investmentsys.contracts.views import MarketViews, TipoView, View

__all__ = [
    "ADVERTENCIA_PRIOR_NEUTRAL",
    "ADVERTENCIA_PRIOR_SOLO_VIEWS",
    "DISCLAIMER",
    "AssetDiagnostic",
    "CandidatePortfolio",
    "CandidatePortfolios",
    "ContractBase",
    "Criterio",
    "EstadoPrior",
    "EtapaCorrida",
    "Fraccion",
    "Frecuencia",
    "LimiteActivo",
    "LimiteGlobal",
    "MarketViews",
    "MatrizCovarianza",
    "MetodoCovarianza",
    "MetodoPrior",
    "MetricasExAnte",
    "MetricasOOS",
    "OrigenActivo",
    "OrigenRestriccion",
    "PortfolioConstraints",
    "PriorActivo",
    "PriorProvenance",
    "PriorSnapshot",
    "QuantEstimates",
    "RegimenMercado",
    "ResultadoStress",
    "RetornoEsperado",
    "RunState",
    "Sensibilidad",
    "SessionConstraints",
    "TecnicaOptimizacion",
    "Ticker",
    "TipoView",
    "Universe",
    "UniverseVersion",
    "ValidationReport",
    "Veredicto",
    "View",
]
