"""Fixtures compartidas por tests unitarios y golden: los datos del ejercicio de referencia."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from investmentsys.contracts import MarketViews, TipoView, View

ACTIVOS = ("VOOG", "BNS", "IBIT", "VB")
FECHA = date(2026, 9, 30)
# Precios CONGELADOS del ejercicio de referencia (copia de data/precios.csv al cerrar S5). Los
# tests leen este archivo y nunca el CSV vivo, que `make update-prices` reescribe cada mes
# (ADR-011). No se edita: `test_fixture_congelado` fija su hash.
CSV_REFERENCIA = Path(__file__).resolve().parent / "fixtures" / "precios_referencia.csv"


@pytest.fixture
def views_golden() -> MarketViews:
    """Las tres views del ejercicio de referencia (ver CLAUDE.md)."""
    return MarketViews(
        fecha_decision=FECHA,
        activos=ACTIVOS,
        horizonte_meses=12,
        resumen="Crecimiento sólido en large caps, banca canadiense favorable, cripto neutral.",
        views=(
            View(
                tipo=TipoView.ABSOLUTA,
                coeficientes={"IBIT": 1.0},
                q_anual=0.03,
                confianza=0.5,
                justificacion="Sin catalizadores claros; retorno total neutral cercano al 3 %.",
                fuente="ejercicio de referencia",
            ),
            View(
                tipo=TipoView.RELATIVA,
                coeficientes={"VOOG": 1.0, "VB": -1.0},
                q_anual=0.03,
                confianza=0.5,
                justificacion="Large growth debería superar a small caps por unos 3 puntos.",
                fuente="ejercicio de referencia",
            ),
            View(
                tipo=TipoView.ABSOLUTA,
                coeficientes={"BNS": 1.0},
                q_anual=0.10,
                confianza=0.5,
                justificacion="Banca canadiense con valoración atractiva; retorno total del 10 %.",
                fuente="ejercicio de referencia",
            ),
        ),
    )
