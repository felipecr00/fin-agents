"""``AssetDiagnostic`` y ``Universe``: el universo de sesión validado por el Gestor de Datos.

Regla dura (S7): ningún número sobre un activo no validado. Los especialistas reciben un
``Universe`` con diagnósticos, nunca una lista de strings, y sellan sus salidas con
``Universe.version`` (ADR-012). La versión es el hash del contenido —incluidas las
capitalizaciones congeladas del prior (ADR-013)—: cambiar un dato, una cap o la aceptación
del prior neutral produce otro universo y deja obsoleto todo resultado anterior.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import date
from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field, StringConstraints, model_validator

from investmentsys.contracts.common import (
    ContractBase,
    Ticker,
    validar_activos_unicos,
    validar_mismo_universo,
)

PATRON_VERSION = r"^[0-9a-f]{64}$"
UniverseVersion = Annotated[str, StringConstraints(pattern=PATRON_VERSION)]
"""SHA-256 del contenido de un ``Universe``; sello de todo resultado calculado sobre él."""

Moneda = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class Frecuencia(StrEnum):
    MENSUAL = "mensual"


class OrigenActivo(StrEnum):
    CONFIG_INICIAL = "config_inicial"
    AGREGADO_EN_SESION = "agregado_en_sesion"


class PriorProvenance(StrEnum):
    """De dónde sale el peso de un activo en el prior de equilibrio (ADR-013)."""

    FUENTE = "fuente"
    USUARIO = "usuario"
    NEUTRAL = "neutral"


class EstadoPrior(StrEnum):
    """Resolución todo-o-nada del prior sobre el universo completo (ADR-013)."""

    CAPITALIZACION = "capitalizacion"  # todas las caps presentes (fuente o usuario)
    NEUTRAL = "neutral"  # falta alguna cap y el usuario aceptó equal-weight para TODOS
    PENDIENTE = "pendiente"  # falta alguna cap y no se aceptó neutral: BL no disponible


class AssetDiagnostic(ContractBase):
    """Lo que el Gestor de Datos sabe de un activo tras validarlo contra la fuente."""

    ticker: Ticker = Field(description="Ticker resuelto en la fuente.")
    nombre: str = Field(min_length=1)
    moneda: Moneda
    fecha_inicio_datos: date
    fecha_fin_datos: date
    frecuencia: Frecuencia
    huecos: tuple[date, ...] = Field(
        default=(), description="Fines de mes sin precio dentro de [inicio, fin]."
    )
    meses_disponibles: int = Field(ge=0)
    advertencias: tuple[str, ...] = Field(
        default=(), description="P. ej. 'ventana corta: stress tasas_2022 no aplica'."
    )
    apto: bool = Field(description="False = no puede entrar en un Universe.")

    # Bloque de prior: la cap CONGELADA del activo. Los cuatro campos van juntos o ninguno.
    prior_cap: float | None = Field(
        default=None, gt=0.0, description="Capitalización congelada, en US$ billones (10^12)."
    )
    prior_provenance: PriorProvenance | None = Field(
        default=None, description="fuente | usuario. None = cap pendiente."
    )
    prior_fuente_detalle: str | None = Field(
        default=None,
        min_length=1,
        description="Endpoint de la fuente, o metodología del usuario (p. ej. 'AUM: proxy débil').",
    )
    prior_as_of: date | None = Field(default=None, description="Fecha del valor congelado.")

    @model_validator(mode="after")
    def _coherencia(self) -> AssetDiagnostic:
        if self.fecha_inicio_datos > self.fecha_fin_datos:
            raise ValueError(f"{self.ticker}: fecha_inicio_datos posterior a fecha_fin_datos")
        fuera = [h for h in self.huecos if not self.fecha_inicio_datos < h < self.fecha_fin_datos]
        if fuera:
            raise ValueError(f"{self.ticker}: huecos fuera de la ventana de datos: {fuera}")
        if not self.apto and not self.advertencias:
            raise ValueError(
                f"{self.ticker}: 'no apto' exige al menos una advertencia que lo explique"
            )
        bloque = (
            self.prior_cap,
            self.prior_provenance,
            self.prior_fuente_detalle,
            self.prior_as_of,
        )
        presentes = [c is not None for c in bloque]
        if any(presentes) and not all(presentes):
            raise ValueError(
                f"{self.ticker}: el bloque de prior va completo (cap, procedencia, detalle y "
                "fecha as-of) o vacío: una cap sin procedencia es una cap inventada"
            )
        if self.prior_provenance is PriorProvenance.NEUTRAL:
            raise ValueError(
                f"{self.ticker}: 'neutral' no es la procedencia de una cap; es una resolución "
                "del universo completo (Universe.prior_neutral_aceptado)"
            )
        return self

    @property
    def tiene_cap(self) -> bool:
        return self.prior_cap is not None


def calcular_version(
    diagnosticos: Iterable[AssetDiagnostic],
    origenes: Mapping[str, OrigenActivo],
    prior_neutral_aceptado: bool,
) -> str:
    """SHA-256 del contenido canónico (JSON con claves ordenadas): mismo contenido, mismo hash."""
    contenido: dict[str, Any] = {
        "diagnosticos": [d.model_dump(mode="json") for d in diagnosticos],
        "origenes": {a: str(o) for a, o in origenes.items()},
        "prior_neutral_aceptado": prior_neutral_aceptado,
    }
    canonico = json.dumps(contenido, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


class Universe(ContractBase):
    """Universo de sesión: activos APTOS con su diagnóstico, en el orden canónico."""

    diagnosticos: tuple[AssetDiagnostic, ...] = Field(min_length=1)
    origenes: dict[Ticker, OrigenActivo]
    prior_neutral_aceptado: bool = Field(
        default=False,
        description="Confirmación explícita del usuario de degradar TODO el prior a equal-weight.",
    )
    version: UniverseVersion = Field(description="Hash del contenido; usar Universe.crear().")

    @classmethod
    def crear(
        cls,
        diagnosticos: Iterable[AssetDiagnostic],
        origenes: Mapping[str, OrigenActivo],
        prior_neutral_aceptado: bool = False,
    ) -> Universe:
        diagnosticos = tuple(diagnosticos)
        return cls(
            diagnosticos=diagnosticos,
            origenes=dict(origenes),
            prior_neutral_aceptado=prior_neutral_aceptado,
            version=calcular_version(diagnosticos, origenes, prior_neutral_aceptado),
        )

    @model_validator(mode="after")
    def _coherencia(self) -> Universe:
        validar_activos_unicos(self.activos)
        validar_mismo_universo(self.origenes, self.activos, "origenes")
        no_aptos = [d.ticker for d in self.diagnosticos if not d.apto]
        if no_aptos:
            raise ValueError(f"activos no aptos no entran en el universo: {no_aptos}")
        if self.prior_neutral_aceptado and not self.sin_cap:
            raise ValueError(
                "prior_neutral_aceptado=True sin ninguna cap pendiente: neutral es el último "
                "escalón de la cascada, no una alternativa a caps disponibles"
            )
        esperada = calcular_version(self.diagnosticos, self.origenes, self.prior_neutral_aceptado)
        if self.version != esperada:
            raise ValueError("version no coincide con el hash del contenido del universo")
        return self

    @property
    def activos(self) -> tuple[str, ...]:
        return tuple(d.ticker for d in self.diagnosticos)

    @property
    def sin_cap(self) -> tuple[str, ...]:
        return tuple(d.ticker for d in self.diagnosticos if not d.tiene_cap)

    @property
    def estado_prior(self) -> EstadoPrior:
        if not self.sin_cap:
            return EstadoPrior.CAPITALIZACION
        return EstadoPrior.NEUTRAL if self.prior_neutral_aceptado else EstadoPrior.PENDIENTE

    def diagnostico(self, ticker: str) -> AssetDiagnostic:
        for d in self.diagnosticos:
            if d.ticker == ticker:
                return d
        raise KeyError(ticker)
