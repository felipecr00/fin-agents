"""``AssetDiagnostic``, ``Universe``, ``SessionConstraints`` y ``PriorSnapshot`` (S7, hito 1)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from investmentsys.contracts import (
    ADVERTENCIA_PRIOR_NEUTRAL,
    AssetDiagnostic,
    EstadoPrior,
    Frecuencia,
    LimiteActivo,
    LimiteGlobal,
    MetodoCovarianza,
    MetodoPrior,
    OrigenActivo,
    OrigenRestriccion,
    PriorActivo,
    PriorProvenance,
    PriorSnapshot,
    SessionConstraints,
    Universe,
)
from tests.conftest import ACTIVOS

CAPS = {"VOOG": 28.0, "BNS": 0.116, "IBIT": 1.9, "VB": 2.5}
AS_OF = date(2026, 9, 16)
RF = 0.04


def _diagnostico(ticker: str, cap: float | None = None, **cambios: Any) -> AssetDiagnostic:
    datos: dict[str, Any] = {
        "ticker": ticker,
        "nombre": f"{ticker} Inc.",
        "moneda": "USD",
        "fecha_inicio_datos": date(2021, 9, 30),
        "fecha_fin_datos": date(2026, 8, 31),
        "frecuencia": Frecuencia.MENSUAL,
        "meses_disponibles": 60,
        "apto": True,
    }
    if cap is not None:
        datos |= {
            "prior_cap": cap,
            "prior_provenance": PriorProvenance.USUARIO,
            "prior_fuente_detalle": "tamaño económico del subyacente",
            "prior_as_of": AS_OF,
        }
    return AssetDiagnostic(**(datos | cambios))


def _universo(caps: dict[str, float | None], neutral: bool = False) -> Universe:
    return Universe.crear(
        [_diagnostico(a, c) for a, c in caps.items()],
        dict.fromkeys(caps, OrigenActivo.CONFIG_INICIAL),
        prior_neutral_aceptado=neutral,
    )


# ------------------------------------------------------------------ AssetDiagnostic
def test_bloque_de_prior_completo_o_vacio() -> None:
    with pytest.raises(ValidationError, match="cap inventada"):
        _diagnostico("VOOG", prior_cap=28.0)
    with pytest.raises(ValidationError, match="cap inventada"):
        _diagnostico("VOOG", cap=28.0, prior_as_of=None)


def test_neutral_no_es_procedencia_de_una_cap() -> None:
    with pytest.raises(ValidationError, match="resolución del universo"):
        _diagnostico("VOOG", cap=28.0, prior_provenance=PriorProvenance.NEUTRAL)


def test_no_apto_exige_explicacion_y_cap_positiva() -> None:
    with pytest.raises(ValidationError, match="advertencia"):
        _diagnostico("VOOG", apto=False)
    with pytest.raises(ValidationError):
        _diagnostico("VOOG", cap=0.0)


def test_huecos_dentro_de_la_ventana() -> None:
    with pytest.raises(ValidationError, match="huecos"):
        _diagnostico("VOOG", huecos=(date(2020, 1, 31),))


# ------------------------------------------------------------------------- Universe
def test_version_es_hash_del_contenido_e_incluye_las_caps() -> None:
    a, b = _universo(CAPS), _universo(CAPS)
    assert a.version == b.version
    assert a.activos == ACTIVOS
    otra_cap = _universo(CAPS | {"BNS": 0.120})
    assert otra_cap.version != a.version
    otro_orden = _universo(dict(reversed(CAPS.items())))
    assert otro_orden.version != a.version  # el orden canónico es contenido


def test_version_manipulada_se_rechaza_y_sobrevive_a_json() -> None:
    u = _universo(CAPS)
    assert Universe.model_validate_json(u.model_dump_json()) == u
    crudo = u.model_dump(mode="json")
    crudo["diagnosticos"][1]["prior_cap"] = 5.0
    with pytest.raises(ValidationError, match="hash"):
        Universe.model_validate(crudo)


def test_estado_del_prior_todo_o_nada() -> None:
    assert _universo(CAPS).estado_prior is EstadoPrior.CAPITALIZACION
    sin_ibit: dict[str, float | None] = CAPS | {"IBIT": None}
    pendiente = _universo(sin_ibit)
    assert pendiente.estado_prior is EstadoPrior.PENDIENTE
    assert pendiente.sin_cap == ("IBIT",)
    neutral = _universo(sin_ibit, neutral=True)
    assert neutral.estado_prior is EstadoPrior.NEUTRAL
    assert neutral.version != pendiente.version
    assert neutral.diagnostico("VOOG").prior_cap == 28.0  # las caps congeladas no se pierden


def test_aceptar_neutral_cambia_la_version() -> None:
    """Cambiar el prior efectivo invalida resultados previos: el flag entra al hash."""
    caps: dict[str, float | None] = CAPS | {"IBIT": None}
    assert _universo(caps, neutral=False).version != _universo(caps, neutral=True).version


def test_neutral_solo_si_falta_alguna_cap() -> None:
    with pytest.raises(ValidationError, match="último escalón"):
        _universo(CAPS, neutral=True)


def test_universo_rechaza_no_aptos_duplicados_y_origenes_incompletos() -> None:
    malo = _diagnostico("VB", apto=False, advertencias=("sin datos",))
    with pytest.raises(ValidationError, match="no aptos"):
        Universe.crear(
            [_diagnostico("VOOG", 28.0), malo], dict.fromkeys(("VOOG", "VB"), "config_inicial")
        )
    with pytest.raises(ValidationError, match="duplicados"):
        Universe.crear([_diagnostico("VOOG", 28.0)] * 2, {"VOOG": OrigenActivo.CONFIG_INICIAL})
    with pytest.raises(ValidationError, match="origenes"):
        Universe.crear([_diagnostico("VOOG", 28.0)], {})


# --------------------------------------------------------------- SessionConstraints
def _sesion(n: int, piso: float, techo: float, **limites: LimiteActivo) -> SessionConstraints:
    activos = tuple(f"A{i}" for i in range(n))
    return SessionConstraints(
        universe_version="0" * 64,
        activos=activos,
        peso_min=LimiteGlobal(valor=piso, origen=OrigenRestriccion.DEFAULT_CONFIG),
        peso_max=LimiteGlobal(valor=techo, origen=OrigenRestriccion.DEFAULT_CONFIG),
        limites_por_activo=limites,
    )


def test_sesion_factible_se_traduce_al_optimizador() -> None:
    propio = LimiteActivo(minimo=0.02, maximo=0.10, origen=OrigenRestriccion.AJUSTE_USUARIO)
    sesion = _sesion(5, 0.02, 0.70, A2=propio)
    assert sesion.limites("A2") == (0.02, 0.10)
    pc = sesion.a_portfolio_constraints()
    assert pc.limites_ordenados() == [(0.02, 0.70)] * 2 + [(0.02, 0.10)] + [(0.02, 0.70)] * 2


def test_piso_por_n_supera_el_cien_por_cien() -> None:
    with pytest.raises(ValidationError, match=r"pisos suman 120\.00% > 100 %"):
        _sesion(6, 0.20, 0.70)


def test_los_techos_no_alcanzan_el_cien_por_cien() -> None:
    with pytest.raises(ValidationError, match=r"techos suman 90\.00% < 100 %"):
        _sesion(3, 0.02, 0.30)


def test_limite_de_un_ticker_fuera_del_universo() -> None:
    propio = LimiteActivo(minimo=0.0, maximo=0.5, origen=OrigenRestriccion.AJUSTE_USUARIO)
    with pytest.raises(ValidationError, match="fuera del universo"):
        _sesion(4, 0.02, 0.70, TSLA=propio)


# -------------------------------------------------------------------- PriorSnapshot
def _fila(
    activo: str, procedencia: PriorProvenance, peso: float | None, **extra: Any
) -> PriorActivo:
    pi = extra.pop("pi_exceso", 0.09)
    return PriorActivo(
        activo=activo,
        procedencia=procedencia,
        peso_mercado=peso,
        pi_exceso=pi,
        pi_total=pi + RF,
        **extra,
    )


def _snapshot(
    filas: list[PriorActivo], metodo: MetodoPrior, advertencia: str | None = None
) -> PriorSnapshot:
    return PriorSnapshot(
        universe_version="0" * 64,
        metodo=metodo,
        delta=2.5,
        tasa_libre_riesgo=RF,
        metodo_covarianza=MetodoCovarianza.HISTORICA,
        activos=tuple(filas),
        advertencia=advertencia,
    )


def _filas_por_cap() -> list[PriorActivo]:
    total = sum(CAPS.values())
    return [
        _fila(
            a, PriorProvenance.USUARIO, c / total, cap=c, fuente_detalle="subyacente", as_of=AS_OF
        )
        for a, c in CAPS.items()
    ]


def test_snapshot_por_capitalizacion() -> None:
    s = _snapshot(_filas_por_cap(), MetodoPrior.CAPITALIZACION)
    assert s.pesos_mercado is not None
    assert s.pesos_mercado["VOOG"] == pytest.approx(0.8611, abs=1e-4)
    assert set(s.procedencias.values()) == {PriorProvenance.USUARIO}


def test_snapshot_nunca_mezcla_procedencias() -> None:
    filas = _filas_por_cap()
    filas[2] = _fila("IBIT", PriorProvenance.NEUTRAL, 0.25)
    with pytest.raises(ValidationError, match="mezcla de procedencias"):
        _snapshot(filas, MetodoPrior.CAPITALIZACION)


def test_snapshot_neutral_exige_equiponderado_y_advertencia() -> None:
    filas = [_fila(a, PriorProvenance.NEUTRAL, 0.25) for a in ACTIVOS]
    assert _snapshot(filas, MetodoPrior.NEUTRAL, ADVERTENCIA_PRIOR_NEUTRAL).advertencia
    with pytest.raises(ValidationError, match="advertencia estándar"):
        _snapshot(filas, MetodoPrior.NEUTRAL)
    filas[0] = _fila("VOOG", PriorProvenance.NEUTRAL, 0.40)
    with pytest.raises(ValidationError, match="1/N"):
        _snapshot(filas, MetodoPrior.NEUTRAL, ADVERTENCIA_PRIOR_NEUTRAL)


def test_snapshot_pesos_deben_salir_de_las_caps() -> None:
    filas = _filas_por_cap()
    filas[0] = _fila(
        "VOOG", PriorProvenance.USUARIO, 0.5, cap=28.0, fuente_detalle="x", as_of=AS_OF
    )
    with pytest.raises(ValidationError, match="cap/Σcap"):
        _snapshot(filas, MetodoPrior.CAPITALIZACION)
