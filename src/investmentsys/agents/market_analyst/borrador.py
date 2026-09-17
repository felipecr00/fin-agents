"""Esquema que ve el LLM y su conversión determinista al contrato ``MarketViews``.

``MarketViews`` no sirve directamente como ``output_schema``: google-genai 2.24 rechaza
``exclusiveMinimum`` y ``patternProperties`` (el ``dict[Ticker, float]`` de ``View``) al
construir la petición (ADR-006). El borrador usa solo construcciones que Gemini acepta y
deja fuera lo que el LLM no decide: la fecha de decisión y el universo los pone el código.
El borrador no cruza fronteras entre agentes; al estado solo llega el contrato validado.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from investmentsys.contracts import MarketViews, TipoView, View

CONFIANZA_MINIMA = 0.01  # el contrato exige confianza > 0; Gemini no admite cotas exclusivas


class _Borrador(BaseModel):
    # Sin extra="forbid": genera `additionalProperties`, que la Gemini API rechaza con un 400
    # aunque el conversor local de google-genai lo acepte. Un campo de más se ignora; lo que
    # importa se valida al construir el contrato.
    model_config = ConfigDict(frozen=True)


class CoeficienteBorrador(_Borrador):
    activo: str = Field(description="Ticker del universo, en mayúsculas.")
    coeficiente: float = Field(
        description="Absoluta: 1.0. Relativa: positivo el lado largo, negativo el corto; suman 0."
    )


class ViewBorrador(_Borrador):
    tipo: TipoView = Field(
        description="absoluta: 'X rendirá q'. relativa: 'la canasta larga superará a la corta'."
    )
    coeficientes: list[CoeficienteBorrador] = Field(
        min_length=1,
        description="Absoluta: un solo activo con 1.0. Relativa: p. ej. VOOG 1.0 y VB -1.0.",
    )
    q_anual: float = Field(
        description=(
            "Retorno anual esperado como fracción (0.03 = 3 %). Absoluta: retorno TOTAL del "
            "activo. Relativa: diferencial entre el lado largo y el corto."
        )
    )
    confianza: float = Field(ge=CONFIANZA_MINIMA, le=1.0, description="Entre 0.01 y 1.")
    justificacion: str = Field(min_length=10, description="Razonamiento en una o dos frases.")
    fuente: str = Field(
        min_length=1,
        description="Referencia verificable. Nunca inventes una URL: si no tienes una, dilo.",
    )
    fecha_fuente: date | None = Field(
        default=None,
        description="null salvo que la fuente sea un documento con fecha conocida (AAAA-MM-DD).",
    )


class MarketViewsBorrador(_Borrador):
    resumen: str = Field(min_length=1, description="Lectura del mercado en dos o tres frases.")
    views: list[ViewBorrador] = Field(description="Puede ser vacía si no hay convicción.")

    def a_contrato(
        self, fecha_decision: date, activos: tuple[str, ...], horizonte_meses: int
    ) -> MarketViews:
        """Construye el contrato; lanza ``ValueError`` (incl. ``ValidationError``) si no valida."""
        views = []
        for i, borrador in enumerate(self.views):
            tickers = [c.activo for c in borrador.coeficientes]
            repetidos = sorted({t for t in tickers if tickers.count(t) > 1})
            if repetidos:
                raise ValueError(f"view {i}: activos repetidos en coeficientes: {repetidos}")
            views.append(
                View(
                    tipo=borrador.tipo,
                    coeficientes={c.activo: c.coeficiente for c in borrador.coeficientes},
                    q_anual=borrador.q_anual,
                    confianza=borrador.confianza,
                    justificacion=borrador.justificacion,
                    fuente=borrador.fuente,
                    fecha_fuente=borrador.fecha_fuente,
                )
            )
        return MarketViews(
            fecha_decision=fecha_decision,
            activos=activos,
            horizonte_meses=horizonte_meses,
            resumen=self.resumen,
            views=tuple(views),
        )
