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
from investmentsys.contracts.fintual import (
    DISCLAIMER_OPERATIVO,
    DecisionInercia,
    OrdenInercia,
    PlanInercia,
)
from investmentsys.contracts.hitos_comite import (
    CronologiaComite,
    EventoComite,
    FaseComite,
    HitoComite,
)
from investmentsys.contracts.mesa_trabajo import (
    CategoriaPizarra,
    Especialista,
    ItemPizarra,
    MesaDeTrabajoState,
    Silla,
)
from investmentsys.contracts.plan_compra import (
    ActaOperativa,
    AsesoriaFiscal,
    BaseCosto,
    CompraNeta,
    EscenarioFiscal,
    OverrideFiscal,
    PerdidaLatente,
    PlanCompraNeta,
    SupuestosFiscales,
    TipoEscenario,
    etiqueta_costo,
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
    "DISCLAIMER_OPERATIVO",
    "ETIQUETA_DIAGNOSTICO",
    "ActaOperativa",
    "AprobacionComite",
    "AsesoriaFiscal",
    "AssetDiagnostic",
    "BaseCosto",
    "CandidatePortfolio",
    "CandidatePortfolios",
    "CategoriaPizarra",
    "CompraNeta",
    "ContractBase",
    "Criterio",
    "CronologiaComite",
    "DecisionInercia",
    "DiagnosticoCartera",
    "EscenarioFiscal",
    "Especialista",
    "EstadoPrior",
    "EtapaCorrida",
    "EventoComite",
    "FaseComite",
    "Fraccion",
    "Frecuencia",
    "HitoComite",
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
    "OrdenInercia",
    "OrigenActivo",
    "OrigenRestriccion",
    "OverrideFiscal",
    "PerdidaLatente",
    "PlanCompraNeta",
    "PlanInercia",
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
    "SupuestosFiscales",
    "TecnicaOptimizacion",
    "Ticker",
    "TipoEscenario",
    "TipoView",
    "Universe",
    "UniverseVersion",
    "ValidationReport",
    "Veredicto",
    "View",
    "etiqueta_costo",
]
