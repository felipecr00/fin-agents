"""``MarketViews``: opiniones de mercado del Analista, en formato Black-Litterman.

Cada ``View`` es una fila de la matriz P con su retorno esperado Q y una confianza.
El contrato solo garantiza coherencia estructural; la traducción de la confianza
a la matriz Ω la decide ``config.yaml`` (``optimizacion.metodo_omega``) en ``portfolio/``.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from investmentsys.contracts.common import (
    TOLERANCIA_NUMERICA,
    ContractBase,
    Ticker,
    validar_activos_unicos,
)


class TipoView(StrEnum):
    """Absoluta: "X rendirá q". Relativa: "la canasta larga superará a la corta por q"."""

    ABSOLUTA = "absoluta"
    RELATIVA = "relativa"


class View(ContractBase):
    """Una opinión sobre el mercado, expresada como fila de P y valor de Q."""

    tipo: TipoView
    coeficientes: dict[Ticker, float] = Field(
        min_length=1,
        description=(
            "Fila de la matriz P. Absoluta: {activo: 1.0}. "
            "Relativa: coeficientes que suman cero, p. ej. {VOOG: 1.0, VB: -1.0}."
        ),
    )
    q_anual: float = Field(
        description=(
            "Retorno esperado anual como fracción (0.03 = 3 %). "
            "Absoluta: retorno TOTAL del activo (la tasa libre de riesgo se descuenta en "
            "portfolio/). Relativa: diferencial esperado entre la canasta larga y la corta."
        )
    )
    confianza: float = Field(
        gt=0.0,
        le=1.0,
        description="Confianza en la view, en (0, 1]. 1 = certeza. Uso definido por metodo_omega.",
    )
    justificacion: str = Field(min_length=10, description="Razonamiento del analista.")
    fuente: str = Field(min_length=1, description="URL o referencia verificable de la evidencia.")
    fecha_fuente: date | None = Field(
        default=None, description="Fecha de publicación de la fuente, si se conoce."
    )

    @model_validator(mode="after")
    def _coherencia_de_la_fila(self) -> View:
        nulos = [a for a, c in self.coeficientes.items() if c == 0.0]
        if nulos:
            raise ValueError(f"coeficientes nulos para {nulos}: elimina esos activos de la view")
        valores = list(self.coeficientes.values())
        if self.tipo is TipoView.ABSOLUTA:
            if len(valores) != 1 or abs(valores[0] - 1.0) > TOLERANCIA_NUMERICA:
                raise ValueError(
                    "una view absoluta tiene exactamente un activo con coeficiente 1.0"
                )
        else:
            if len(valores) < 2:
                raise ValueError("una view relativa necesita al menos dos activos")
            if abs(sum(valores)) > TOLERANCIA_NUMERICA:
                raise ValueError("los coeficientes de una view relativa deben sumar cero")
            if not (any(v > 0 for v in valores) and any(v < 0 for v in valores)):
                raise ValueError("una view relativa necesita un lado largo y uno corto")
        return self

    @property
    def activos(self) -> tuple[str, ...]:
        return tuple(self.coeficientes)


class MarketViews(ContractBase):
    """Salida del Analista de Mercados; entrada del Constructor (Black-Litterman)."""

    fecha_decision: date = Field(
        description="Fecha a la que se refieren las views. Ninguna fuente puede ser posterior."
    )
    activos: tuple[Ticker, ...] = Field(min_length=1, description="Universo, en orden canónico.")
    horizonte_meses: int = Field(gt=0, description="Horizonte de las views en meses.")
    resumen: str = Field(min_length=1, description="Lectura del mercado en prosa breve.")
    views: tuple[View, ...] = Field(
        default=(), description="Puede estar vacío: entonces el posterior es el equilibrio."
    )

    @field_validator("activos")
    @classmethod
    def _activos_unicos(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        return validar_activos_unicos(v)

    @model_validator(mode="after")
    def _views_dentro_del_universo(self) -> MarketViews:
        universo = set(self.activos)
        for i, view in enumerate(self.views):
            fuera = sorted(set(view.activos) - universo)
            if fuera:
                raise ValueError(f"view {i}: activos fuera del universo: {fuera}")
            if view.fecha_fuente is not None and view.fecha_fuente > self.fecha_decision:
                raise ValueError(
                    f"view {i}: la fuente ({view.fecha_fuente}) es posterior a la fecha de "
                    f"decisión ({self.fecha_decision}); look-ahead"
                )
        return self

    def matriz_p(self) -> list[list[float]]:
        """Matriz P (k × n) en el orden canónico de ``activos``."""
        return [[view.coeficientes.get(a, 0.0) for a in self.activos] for view in self.views]

    def vector_q(self) -> list[float]:
        """Vector Q (k) tal como lo expresó el analista (ver ``View.q_anual``)."""
        return [view.q_anual for view in self.views]

    def vector_confianza(self) -> list[float]:
        return [view.confianza for view in self.views]
