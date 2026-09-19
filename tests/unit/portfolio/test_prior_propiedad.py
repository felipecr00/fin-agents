"""TEST DE PROPIEDAD DEL PRIOR (S7, DoD; ADR-013). INTOCABLE: si un cambio lo rompe, el error
es del cambio.

Para universos generados arbitrariamente —cualquier número de activos, cualquier combinación
de caps de la fuente, del usuario o ausentes, con o sin aceptación de neutral, con cualquiera
de las dos degradaciones de config— el prior resuelto cumple:

1. las procedencias son ⊆ {fuente, usuario} o TODAS neutral: nunca mezcla;
2. si falta alguna cap y no se aceptó degradar, no hay prior (BL no disponible), con un
   mensaje que nombra a cada activo sin cap;
3. ninguna cap aparece sin haber sido aportada: un prior de mercado usa exactamente las caps
   congeladas del universo, y un prior degradado no registra ninguna;
4. el contrato ``PriorSnapshot`` rechaza cualquier mezcla construida a mano.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from investmentsys.config import cargar_config
from investmentsys.contracts import (
    AssetDiagnostic,
    EstadoPrior,
    Frecuencia,
    MetodoCovarianza,
    MetodoPrior,
    OrigenActivo,
    PriorProvenance,
    PriorSnapshot,
    Universe,
)
from investmentsys.portfolio import PriorNoDisponibleError, resolver_prior
from investmentsys.quant import estimar

CONFIG = cargar_config()
FECHA = date(2026, 8, 31)
DE_MERCADO = {PriorProvenance.FUENTE, PriorProvenance.USUARIO}

procedencia_de_cap = st.sampled_from([PriorProvenance.FUENTE, PriorProvenance.USUARIO, None])
activo = st.tuples(procedencia_de_cap, st.floats(min_value=1e-4, max_value=50.0))
universos = st.tuples(
    st.lists(activo, min_size=2, max_size=7),
    st.booleans(),  # ¿el usuario aceptó degradar a neutral?
    st.sampled_from(["neutral", "solo_views"]),
    st.integers(min_value=0, max_value=2**16),  # semilla de los retornos sintéticos
)


def _universo(activos: list[tuple[PriorProvenance | None, float]], acepta: bool) -> Universe:
    diagnosticos = []
    for i, (procedencia, cap) in enumerate(activos):
        prior: dict[str, Any] = {}
        if procedencia is not None:
            prior = {
                "prior_cap": cap,
                "prior_provenance": procedencia,
                "prior_fuente_detalle": f"origen {procedencia.value}",
                "prior_as_of": date(2026, 9, 1),
            }
        diagnosticos.append(
            AssetDiagnostic(
                ticker=f"A{i}",
                nombre=f"Activo {i}",
                moneda="USD",
                fecha_inicio_datos=date(2023, 8, 31),
                fecha_fin_datos=FECHA,
                frecuencia=Frecuencia.MENSUAL,
                meses_disponibles=37,
                apto=True,
                **prior,
            )
        )
    falta = any(p is None for p, _ in activos)
    return Universe.crear(
        diagnosticos,
        {d.ticker: OrigenActivo.AGREGADO_EN_SESION for d in diagnosticos},
        prior_neutral_aceptado=acepta and falta,  # aceptar sin que falte nada no es un estado
    )


def _estimates(universo: Universe, semilla: int) -> Any:
    rng = np.random.default_rng(semilla)
    indice = pd.date_range(end=FECHA, periods=36, freq="ME")
    retornos = pd.DataFrame(
        rng.normal(0.01, 0.05, size=(36, len(universo.activos))),
        index=indice,
        columns=list(universo.activos),
    )
    return estimar(
        retornos,
        fecha_decision=FECHA,
        periodos_por_anio=12,
        ventana_meses=36,
        metodos=(MetodoCovarianza.HISTORICA,),
        nivel_confianza=0.95,
        universe_version=universo.version,
    )


@settings(max_examples=200, deadline=None)
@given(universos)
def test_las_procedencias_nunca_se_mezclan(caso: Any) -> None:
    activos, acepta, degradacion, semilla = caso
    universo = _universo(activos, acepta)
    prior = CONFIG.prior_equilibrio.model_copy(update={"degradacion": degradacion})
    sin_cap = [f"A{i}" for i, (p, _) in enumerate(activos) if p is None]

    if sin_cap and not acepta:
        assert universo.estado_prior is EstadoPrior.PENDIENTE
        with pytest.raises(PriorNoDisponibleError) as exc:
            resolver_prior(universo, _estimates(universo, semilla), CONFIG.optimizacion, prior)
        assert all(a in str(exc.value) for a in sin_cap)
        return

    snap = resolver_prior(universo, _estimates(universo, semilla), CONFIG.optimizacion, prior)
    procedencias = set(snap.procedencias.values())
    assert procedencias <= DE_MERCADO or procedencias == {PriorProvenance.NEUTRAL}

    if sin_cap:  # degradación aceptada: TODO el vector, no solo los activos sin cap
        assert procedencias == {PriorProvenance.NEUTRAL}
        assert snap.metodo is (
            MetodoPrior.NEUTRAL if degradacion == "neutral" else MetodoPrior.SOLO_VIEWS
        )
        assert all(a.cap is None for a in snap.activos) and snap.advertencia
    else:  # prior de mercado: exactamente las caps congeladas, con su procedencia
        assert snap.metodo is MetodoPrior.CAPITALIZACION and snap.advertencia is None
        assert [(a.procedencia, a.cap) for a in snap.activos] == list(activos)
        assert sum(a.peso_mercado or 0.0 for a in snap.activos) == pytest.approx(1.0)


@settings(max_examples=100, deadline=None)
@given(universos, st.data())
def test_el_contrato_rechaza_una_mezcla_hecha_a_mano(caso: Any, data: st.DataObject) -> None:
    activos, _, _, semilla = caso
    completos = [(p or PriorProvenance.USUARIO, c) for p, c in activos]
    universo = _universo(completos, acepta=False)
    snap = resolver_prior(
        universo, _estimates(universo, semilla), CONFIG.optimizacion, CONFIG.prior_equilibrio
    )
    crudo = snap.model_dump(mode="json")
    victima = data.draw(st.integers(min_value=0, max_value=len(activos) - 1))
    crudo["activos"][victima]["procedencia"] = PriorProvenance.NEUTRAL.value
    with pytest.raises(ValidationError):
        PriorSnapshot.model_validate(crudo)
