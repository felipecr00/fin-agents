"""Carga tipada de ``config.yaml``. Ningún número mágico vive fuera de ese archivo."""

from __future__ import annotations

import hashlib
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from investmentsys.contracts import Fraccion, MetodoCovarianza, Ticker
from investmentsys.contracts.common import validar_mismo_universo, validar_suma

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]
RUTA_CONFIG = RAIZ_PROYECTO / "config.yaml"


class MetodoOmega(StrEnum):
    """Cómo se construye Ω (incertidumbre de las views) en Black-Litterman."""

    HE_LITTERMAN = "he_litterman"
    IDZOREK = "idzorek"


class _Seccion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class PortafolioConfig(_Seccion):
    activos: tuple[Ticker, ...] = Field(min_length=1)
    valor_usd: float = Field(gt=0.0)
    pesos_actuales: dict[Ticker, Fraccion]

    @model_validator(mode="after")
    def _pesos(self) -> PortafolioConfig:
        validar_mismo_universo(self.pesos_actuales, self.activos, "pesos_actuales")
        validar_suma(self.pesos_actuales, 1.0, "pesos_actuales")
        return self


class OptimizacionConfig(_Seccion):
    aversion_riesgo_delta: float = Field(gt=0.0)
    tau: float = Field(gt=0.0)
    tasa_libre_riesgo: float
    peso_min: float
    peso_max: float = Field(le=1.0)
    permitir_cortos: bool
    metodo_covarianza: MetodoCovarianza
    metodo_omega: MetodoOmega


class PriorEquilibrioConfig(_Seccion):
    metodo: Literal["capitalizacion"]
    capitalizacion_usd_billones: dict[Ticker, float] = Field(min_length=1)

    @model_validator(mode="after")
    def _positivas(self) -> PriorEquilibrioConfig:
        no_positivas = [a for a, c in self.capitalizacion_usd_billones.items() if c <= 0]
        if no_positivas:
            raise ValueError(f"capitalizaciones no positivas: {no_positivas}")
        return self


class EstimacionConfig(_Seccion):
    nivel_confianza: float = Field(gt=0.0, lt=1.0)


class DatosConfig(_Seccion):
    proveedor: Literal["csv"]
    ruta_csv: Path
    ventana_covarianza_meses: int = Field(gt=0)


class EscenarioStressConfig(_Seccion):
    """Ventana histórica de stress: se incluyen los retornos de los meses en [desde, hasta]."""

    nombre: str = Field(min_length=1)
    desde: date
    hasta: date

    @model_validator(mode="after")
    def _ordenado(self) -> EscenarioStressConfig:
        if self.desde > self.hasta:
            raise ValueError(f"{self.nombre}: 'desde' posterior a 'hasta'")
        return self


class ValidacionConfig(_Seccion):
    sharpe_oos_minimo: float
    max_drawdown_tolerado: Fraccion
    turnover_maximo_anual: float = Field(ge=0.0)
    concentracion_hhi_maxima: Fraccion
    costo_transaccion_bps: float = Field(ge=0.0)
    rebalanceo: Literal["mensual"]
    max_iteraciones_constructor: int = Field(ge=1)
    escenarios_stress: tuple[EscenarioStressConfig, ...] = ()

    @model_validator(mode="after")
    def _escenarios_unicos(self) -> ValidacionConfig:
        nombres = [e.nombre for e in self.escenarios_stress]
        if len(set(nombres)) != len(nombres):
            raise ValueError("escenarios_stress: nombres repetidos")
        return self


class ReproducibilidadConfig(_Seccion):
    semilla: int


class Config(_Seccion):
    portafolio: PortafolioConfig
    optimizacion: OptimizacionConfig
    prior_equilibrio: PriorEquilibrioConfig
    estimacion: EstimacionConfig
    datos: DatosConfig
    validacion: ValidacionConfig
    reproducibilidad: ReproducibilidadConfig

    @model_validator(mode="after")
    def _universo_consistente(self) -> Config:
        validar_mismo_universo(
            self.prior_equilibrio.capitalizacion_usd_billones,
            self.portafolio.activos,
            "prior_equilibrio.capitalizacion_usd_billones",
        )
        return self


def cargar_config(ruta: Path = RUTA_CONFIG) -> Config:
    with ruta.open(encoding="utf-8") as f:
        crudo: Any = yaml.safe_load(f)
    return Config.model_validate(crudo)


def hash_config(ruta: Path = RUTA_CONFIG) -> str:
    """SHA-256 del archivo tal cual está en disco; se guarda en ``RunState.config_hash``."""
    return hashlib.sha256(ruta.read_bytes()).hexdigest()
