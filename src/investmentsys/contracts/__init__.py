"""Contratos Pydantic: única forma válida de comunicación entre agentes."""

from investmentsys.contracts.comite import AprobacionComite, ResumenComite, SolicitudComite
from investmentsys.contracts.common import DISCLAIMER, ContractBase, Fraccion, Ticker
from investmentsys.contracts.constraints import PortfolioConstraints
from investmentsys.contracts.diagnostico import ETIQUETA_DIAGNOSTICO, DiagnosticoCartera
from investmentsys.contracts.estimates import (
    MatrizCovarianza,
    MetodoCovarianza,
    QuantEstimates,
    RegimenMercado,
    RetornoEsperado,
)
from investmentsys.contracts.mesa_trabajo import (
    CategoriaPizarra,
    Especialista,
    ItemPizarra,
    MesaDeTrabajoState,
    Silla,
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
    "ETIQUETA_DIAGNOSTICO",
    "AprobacionComite",
    "AssetDiagnostic",
    "CandidatePortfolio",
    "CandidatePortfolios",
    "CategoriaPizarra",
    "ContractBase",
    "Criterio",
    "DiagnosticoCartera",
    "Especialista",
    "EstadoPrior",
    "EtapaCorrida",
    "Fraccion",
    "Frecuencia",
    "ItemPizarra",
    "LimiteActivo",
    "LimiteGlobal",
    "MarketViews",
    "MatrizCovarianza",
    "MesaDeTrabajoState",
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
    "ResumenComite",
    "RetornoEsperado",
    "RunState",
    "Sensibilidad",
    "SessionConstraints",
    "Silla",
    "SolicitudComite",
    "TecnicaOptimizacion",
    "Ticker",
    "TipoView",
    "Universe",
    "UniverseVersion",
    "ValidationReport",
    "Veredicto",
    "View",
]
