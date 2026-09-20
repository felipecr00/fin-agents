"""Carga tipada de ``config.yaml``. Ningún número mágico vive fuera de ese archivo."""

from __future__ import annotations

import hashlib
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from investmentsys.contracts import Fraccion, MetodoCovarianza, Ticker
from investmentsys.contracts.common import validar_mismo_universo, validar_suma

NOMBRE_CONFIG = "config.yaml"


def _localizar_raiz(desde: Path) -> Path:
    """Primer ancestro de ``desde`` con ``config.yaml`` (ADR-008).

    En el repo es la raíz (``src/investmentsys`` → ``src`` → raíz); en los contenedores de
    Cloud Run y Agent Engine es ``/app``, donde el paquete no cuelga de ``src/``.
    """
    for carpeta in desde.resolve().parents:
        if (carpeta / NOMBRE_CONFIG).is_file():
            return carpeta
    raise FileNotFoundError(f"ningún directorio por encima de {desde} contiene {NOMBRE_CONFIG}")


RAIZ_PROYECTO = _localizar_raiz(Path(__file__))
RUTA_CONFIG = RAIZ_PROYECTO / NOMBRE_CONFIG


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
    degradacion: Literal["neutral", "solo_views"] = Field(
        description="Prior cuando falta alguna cap y el usuario aceptó degradar (ADR-013)."
    )
    capitalizacion_usd_billones: dict[Ticker, float] = Field(min_length=1)
    as_of: date = Field(description="Fecha de las caps pinneadas del universo de referencia.")
    metodologia: str = Field(min_length=1)

    @model_validator(mode="after")
    def _positivas(self) -> PriorEquilibrioConfig:
        no_positivas = [a for a, c in self.capitalizacion_usd_billones.items() if c <= 0]
        if no_positivas:
            raise ValueError(f"capitalizaciones no positivas: {no_positivas}")
        return self


class EstimacionConfig(_Seccion):
    nivel_confianza: float = Field(gt=0.0, lt=1.0)


class ReintentosHttpConfig(_Seccion):
    """Reintentos con espera exponencial ante 429 y timeouts de una fuente de datos."""

    intentos: int = Field(ge=1, description="Incluye la petición original; 1 = sin reintentos.")
    espera_inicial_s: float = Field(gt=0.0)
    espera_maxima_s: float = Field(gt=0.0)
    base_exponencial: float = Field(ge=1.0)


class TiingoConfig(_Seccion):
    """Fuente de precios mensuales ajustados (ADR-011). La API key va por entorno."""

    url_base: str = Field(pattern=r"^https://")
    fecha_inicio: date
    timeout_s: float = Field(gt=0.0)
    reintentos: ReintentosHttpConfig


class ActualizacionConfig(_Seccion):
    """Validaciones y escritura de ``make update-prices`` (``data.actualizacion``)."""

    tolerancia_continuidad: float = Field(gt=0.0, description="0.005 = 0,5 p.p. de retorno.")
    retorno_mensual_max: float = Field(gt=0.0)
    activos_inicio_tardio: tuple[Ticker, ...] = ()
    backups_a_conservar: int = Field(ge=1)
    decimales_csv: int = Field(ge=2)
    directorio_resumenes: Path


class GestorDatosConfig(_Seccion):
    """Gestor de Datos (``data_manager``): universo vigente y reglas de aptitud."""

    ruta_universo: Path
    ruta_historial: Path
    bolsas_usd: tuple[str, ...] = Field(min_length=1)
    meses_minimos_apto: int = Field(ge=3)
    usd_por_unidad_cap: float = Field(gt=0.0)


class DatosConfig(_Seccion):
    proveedor: Literal["series"]
    directorio_series: Path
    ventana_covarianza_meses: int = Field(gt=0)
    gestor: GestorDatosConfig
    tiingo: TiingoConfig
    actualizacion: ActualizacionConfig


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


class ReintentosModeloConfig(_Seccion):
    """Reintentos HTTP del cliente del LLM ante errores transitorios (espera exponencial)."""

    intentos: int = Field(ge=1, description="Incluye la petición original; 1 = sin reintentos.")
    espera_inicial_s: float = Field(gt=0.0)
    espera_maxima_s: float = Field(gt=0.0)
    base_exponencial: float = Field(ge=1.0)
    codigos_http: tuple[int, ...] = Field(min_length=1)


class AgentesConfig(_Seccion):
    temperatura: float = Field(ge=0.0, le=2.0)
    temperatura_personas: float = Field(
        ge=0.0, le=2.0, description="Estadístico y Escéptico (S10): baja, redactan sobre cifras."
    )
    max_intentos_analista: int = Field(ge=1)
    horizonte_views_meses: int = Field(gt=0)
    max_views: int = Field(ge=1)
    confianza_max_sin_conviccion: Fraccion
    ubicacion_vertex: str | None = Field(
        default=None, description="Ubicación del modelo en Vertex AI; None = la del entorno."
    )
    reintentos_modelo: ReintentosModeloConfig


NombreNivel = Literal["nivel_1", "nivel_2", "nivel_3"]


class NivelLLM(_Seccion):
    """Asignación real de un nivel de inferencia servido por un LLM (ADR-018)."""

    cliente: str = Field(
        pattern=r"^[\w.]+:\w+$", description='Clase de ADK que sirve el modelo: "módulo:Clase".'
    )
    modelo: str = Field(min_length=1, description="Id fijo del modelo (ADR-005).")
    secreto_llave: str | None = Field(
        default=None, description="Secreto de Secret Manager con la llave (despliegue de dev)."
    )

    @field_validator("modelo")
    @classmethod
    def _id_fijo(cls, v: str) -> str:
        if v.endswith("-latest"):
            raise ValueError("usa un id de modelo fijo, no un alias -latest (ADR-005)")
        return v


class InferenciaConfig(_Seccion):
    """Niveles de inferencia y qué nivel atiende a cada agente. Único lugar con nombres reales.

    Nivel 1: Frontier LLM. Nivel 2: Edge/cuantizado (NLP local). Nivel 3: determinista, sin LLM.
    """

    nivel_1: NivelLLM
    nivel_2: NivelLLM | None = None
    nivel_3: Literal["determinista"]
    asignaciones: dict[str, NombreNivel] = Field(min_length=1)
    nombres_vetados: tuple[str, ...] = Field(min_length=1)
    excepciones_de_tooling: tuple[str, ...] = ()

    def de(self, agente: str) -> NivelLLM:
        """El nivel con LLM asignado a ``agente``; error claro si no tiene uno utilizable."""
        nombre = self.asignaciones.get(agente)
        if nombre is None:
            raise ValueError(f"inferencia.asignaciones: falta el agente '{agente}'")
        nivel = getattr(self, nombre)
        if not isinstance(nivel, NivelLLM):
            raise ValueError(
                f"inferencia: '{agente}' está asignado a {nombre}, que no tiene un LLM asignado"
            )
        return nivel


class EvaluacionConfig(_Seccion):
    """Criterios universales de los evalsets del analista (ADR-010)."""

    q_absoluta_max: float = Field(gt=0.0, description="|q_anual| máximo de una view absoluta.")
    q_relativa_max: float = Field(gt=0.0, description="|q_anual| máximo de una view relativa.")


class RegimenConfig(_Seccion):
    """Clasificador simple de régimen de mercado (``quant.regimen``)."""

    activos_referencia: tuple[Ticker, ...] = Field(min_length=1)
    ventana_tendencia_meses: int = Field(gt=0)
    ventana_volatilidad_meses: int = Field(gt=1)
    observaciones_minimas: int = Field(gt=1)
    umbral_tendencia: float = Field(gt=0.0)
    drawdown_estres: Fraccion
    ratio_volatilidad_estres: float = Field(gt=0.0)

    @model_validator(mode="after")
    def _ventanas_dentro_del_minimo(self) -> RegimenConfig:
        ventanas = max(self.ventana_tendencia_meses, self.ventana_volatilidad_meses)
        if self.observaciones_minimas < ventanas:
            raise ValueError("observaciones_minimas debe cubrir las ventanas de tendencia y vol")
        return self


class SensibilidadConfig(_Seccion):
    """Rejilla de perturbaciones del análisis de sensibilidad (``risk.sensibilidad``)."""

    retornos_pp: tuple[float, ...] = Field(min_length=1, description="Absolutas: 0.01 = 1 p.p.")
    covarianza_rel: tuple[float, ...] = Field(min_length=1, description="Relativas: 0.10 = 10 %.")
    parametros_rel: tuple[float, ...] = Field(min_length=1, description="Relativas, sobre δ y τ.")

    @model_validator(mode="after")
    def _magnitudes(self) -> SensibilidadConfig:
        if any(m <= 0.0 for m in self.retornos_pp):
            raise ValueError("retornos_pp: magnitudes positivas (el signo lo pone el análisis)")
        for nombre in ("covarianza_rel", "parametros_rel"):
            if any(not 0.0 < m < 1.0 for m in getattr(self, nombre)):
                raise ValueError(f"{nombre}: magnitudes relativas en (0, 1)")
        return self


class FintualConfig(_Seccion):
    """Gobernanza operativa en Fintual Acciones (``fintual/``, ADR-020)."""

    banda_inercia: float = Field(
        gt=0.0, le=1.0, description="Semiancho ABSOLUTO de la No-Trade Zone: 0.05 = ±5 p.p."
    )
    bandas_por_activo: dict[Ticker, float] = Field(default_factory=dict)
    decimales_usd: int = Field(ge=0, le=4, description="Fintual compra fracciones: montos a 2.")
    dias_historia_dividendos: int = Field(gt=0)

    @model_validator(mode="after")
    def _bandas(self) -> FintualConfig:
        fuera = sorted(a for a, b in self.bandas_por_activo.items() if not 0.0 < b <= 1.0)
        if fuera:
            raise ValueError(f"bandas_por_activo fuera de (0, 1]: {fuera}")
        return self


class CorridasConfig(_Seccion):
    directorio: Path


class ReproducibilidadConfig(_Seccion):
    semilla: int
    tolerancia_replay: float = Field(gt=0.0)


class Config(_Seccion):
    portafolio: PortafolioConfig
    optimizacion: OptimizacionConfig
    prior_equilibrio: PriorEquilibrioConfig
    estimacion: EstimacionConfig
    regimen: RegimenConfig
    datos: DatosConfig
    validacion: ValidacionConfig
    inferencia: InferenciaConfig
    agentes: AgentesConfig
    evaluacion: EvaluacionConfig
    fintual: FintualConfig
    sensibilidad: SensibilidadConfig
    corridas: CorridasConfig
    reproducibilidad: ReproducibilidadConfig

    @model_validator(mode="after")
    def _universo_consistente(self) -> Config:
        validar_mismo_universo(
            self.prior_equilibrio.capitalizacion_usd_billones,
            self.portafolio.activos,
            "prior_equilibrio.capitalizacion_usd_billones",
        )
        fuera = sorted(set(self.regimen.activos_referencia) - set(self.portafolio.activos))
        if fuera:
            raise ValueError(f"regimen.activos_referencia fuera del universo: {fuera}")
        tardios = self.datos.actualizacion.activos_inicio_tardio
        fuera = sorted(set(tardios) - set(self.portafolio.activos))
        if fuera:
            raise ValueError(f"actualizacion.activos_inicio_tardio fuera del universo: {fuera}")
        return self


def cargar_config(ruta: Path = RUTA_CONFIG) -> Config:
    with ruta.open(encoding="utf-8") as f:
        crudo: Any = yaml.safe_load(f)
    return Config.model_validate(crudo)


def hash_config(ruta: Path = RUTA_CONFIG) -> str:
    """SHA-256 del archivo tal cual está en disco; se guarda en ``RunState.config_hash``."""
    return hashlib.sha256(ruta.read_bytes()).hexdigest()
