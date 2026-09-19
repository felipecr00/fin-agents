"""``QuantEstimates``: estimaciones deterministas del agente Quant.

Contiene una matriz de covarianza por método, retornos históricos con intervalo y el
régimen de mercado detectado. Todo anualizado y expresado como fracción.
"""

from __future__ import annotations

import math
from datetime import date
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from investmentsys.contracts.common import (
    TOLERANCIA_NUMERICA,
    ContractBase,
    Ticker,
    validar_activos_unicos,
    validar_mismo_universo,
)
from investmentsys.contracts.universe import UniverseVersion


class MetodoCovarianza(StrEnum):
    HISTORICA = "historica"
    LEDOIT_WOLF = "ledoit_wolf"


class RegimenMercado(StrEnum):
    ALCISTA = "alcista"
    BAJISTA = "bajista"
    LATERAL = "lateral"
    ESTRES = "estres"
    INDETERMINADO = "indeterminado"


class MatrizCovarianza(ContractBase):
    """Covarianza anualizada (n × n), simétrica, en el orden canónico de ``activos``."""

    metodo: MetodoCovarianza
    activos: tuple[Ticker, ...] = Field(min_length=1)
    valores: tuple[tuple[float, ...], ...] = Field(description="Filas de la matriz, anualizada.")
    ventana_meses: int = Field(gt=0, description="Ventana máxima de estimación en meses.")
    observaciones_por_activo: dict[Ticker, int] = Field(
        description=(
            "Retornos efectivamente usados por activo. Un activo con serie corta (IBIT) "
            "tendrá menos observaciones que la ventana."
        )
    )

    @field_validator("activos")
    @classmethod
    def _activos_unicos(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        return validar_activos_unicos(v)

    @model_validator(mode="after")
    def _matriz_valida(self) -> MatrizCovarianza:
        n = len(self.activos)
        if len(self.valores) != n or any(len(fila) != n for fila in self.valores):
            raise ValueError(f"la matriz debe ser {n}×{n} (un activo por fila y columna)")
        for i in range(n):
            if self.valores[i][i] < 0.0:
                raise ValueError(f"varianza negativa para {self.activos[i]}")
            for j in range(i + 1, n):
                if abs(self.valores[i][j] - self.valores[j][i]) > TOLERANCIA_NUMERICA:
                    raise ValueError(
                        f"matriz no simétrica en ({self.activos[i]}, {self.activos[j]})"
                    )
        validar_mismo_universo(self.observaciones_por_activo, self.activos, "observaciones")
        for activo, n_obs in self.observaciones_por_activo.items():
            if not 1 <= n_obs <= self.ventana_meses:
                raise ValueError(
                    f"{activo}: {n_obs} observaciones fuera de [1, {self.ventana_meses}]"
                )
        return self

    def varianza(self, activo: str) -> float:
        i = self.activos.index(activo)
        return self.valores[i][i]

    def volatilidad(self, activo: str) -> float:
        return math.sqrt(self.varianza(activo))

    def correlacion(self, a: str, b: str) -> float:
        i, j = self.activos.index(a), self.activos.index(b)
        return self.valores[i][j] / (self.volatilidad(a) * self.volatilidad(b))


class RetornoEsperado(ContractBase):
    """Retorno anual de un activo con su intervalo de confianza."""

    activo: Ticker
    media_anual: float
    intervalo_inferior: float
    intervalo_superior: float
    nivel_confianza: float = Field(gt=0.0, lt=1.0, description="P. ej. 0.95.")

    @model_validator(mode="after")
    def _intervalo_ordenado(self) -> RetornoEsperado:
        if not self.intervalo_inferior <= self.media_anual <= self.intervalo_superior:
            raise ValueError(f"{self.activo}: intervalo incoherente con la media")
        return self


class QuantEstimates(ContractBase):
    """Salida del agente Quant; entrada del Constructor y del Validador."""

    fecha_decision: date
    fecha_inicio_muestra: date
    fecha_fin_muestra: date = Field(
        description="Última observación usada. Nunca posterior a fecha_decision (look-ahead)."
    )
    activos: tuple[Ticker, ...] = Field(min_length=1)
    periodos_por_anio: int = Field(gt=0, description="12 para datos mensuales.")
    covarianzas: dict[MetodoCovarianza, MatrizCovarianza] = Field(min_length=1)
    retornos_historicos: tuple[RetornoEsperado, ...] = Field(
        description="Uno por activo, en el orden canónico."
    )
    regimen: RegimenMercado = RegimenMercado.INDETERMINADO
    universe_version: UniverseVersion | None = Field(
        default=None,
        description=(
            "Sello del Universe sobre el que se calculó (ADR-012). None = sin sellar: solo lo "
            "admite el núcleo puro llamado directamente; las herramientas lo rechazan."
        ),
    )

    @field_validator("activos")
    @classmethod
    def _activos_unicos(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        return validar_activos_unicos(v)

    @model_validator(mode="after")
    def _coherencia(self) -> QuantEstimates:
        if self.fecha_inicio_muestra > self.fecha_fin_muestra:
            raise ValueError("fecha_inicio_muestra posterior a fecha_fin_muestra")
        if self.fecha_fin_muestra > self.fecha_decision:
            raise ValueError(
                f"look-ahead: la muestra termina en {self.fecha_fin_muestra}, después de la "
                f"fecha de decisión {self.fecha_decision}"
            )
        for metodo, matriz in self.covarianzas.items():
            if matriz.metodo is not metodo:
                raise ValueError(f"covarianza registrada como {metodo} pero es {matriz.metodo}")
            if matriz.activos != self.activos:
                raise ValueError(f"covarianza {metodo}: orden de activos distinto al canónico")
        if tuple(r.activo for r in self.retornos_historicos) != self.activos:
            raise ValueError("retornos_historicos: debe haber uno por activo, en orden canónico")
        return self

    def covarianza(self, metodo: MetodoCovarianza) -> MatrizCovarianza:
        return self.covarianzas[metodo]
