"""Gestor de Datos (S7): resolver, incorporar, refrescar_cap, diagnosticar. Sin red."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from investmentsys.config import Config, cargar_config
from investmentsys.contracts import EstadoPrior, OrigenActivo, PriorProvenance, Universe
from investmentsys.data import SeriesPriceProvider
from investmentsys.data_manager import (
    ActivoNoAptoError,
    GestorDatos,
    GestorError,
    TickerNoResueltoError,
    UniversoDesincronizadoError,
)
from tests.almacen import (
    AHORA,
    FuenteFalsa,
    cap_fuente,
    panel_referencia,
    sembrar_gestor,
    serie_sintetica,
)
from tests.conftest import ACTIVOS

FIN = pd.Timestamp("2026-09-30")


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config()


@pytest.fixture
def fuente() -> FuenteFalsa:
    return FuenteFalsa(
        series={
            "AAPL": serie_sintetica("AAPL", 61, FIN),
            "QQQ": serie_sintetica("QQQ", 61, FIN, semilla=11),
            "NUEVO": serie_sintetica("NUEVO", 20, FIN, semilla=3),
            "BEBE": serie_sintetica("BEBE", 6, FIN, semilla=5),
            "TSX": serie_sintetica("TSX", 61, FIN, semilla=9),
            "VIEJO": serie_sintetica("VIEJO", 61, FIN - pd.offsets.MonthEnd(1), semilla=2),
        },
        bolsas={"TSX": "TSX"},
        caps={"AAPL": cap_fuente()},
    )


@pytest.fixture
def gestor(tmp_path: Path, config: Config, fuente: FuenteFalsa) -> GestorDatos:
    return sembrar_gestor(tmp_path, config, fuente)


# ------------------------------------------------------------- universo de referencia
def test_universo_sembrado_lleva_las_caps_pinneadas(gestor: GestorDatos, config: Config) -> None:
    u = gestor.universo()
    assert u.activos == ACTIVOS
    assert u.estado_prior is EstadoPrior.CAPITALIZACION
    assert set(u.origenes.values()) == {OrigenActivo.CONFIG_INICIAL}
    for d in u.diagnosticos:
        assert d.prior_cap == config.prior_equilibrio.capitalizacion_usd_billones[d.ticker]
        assert d.prior_provenance is PriorProvenance.USUARIO
        assert d.prior_fuente_detalle == config.prior_equilibrio.metodologia
        assert d.prior_as_of == config.prior_equilibrio.as_of


def test_diagnostico_de_historia_corta(gestor: GestorDatos) -> None:
    ibit = gestor.universo().diagnostico("IBIT")
    assert ibit.meses_disponibles == 33 and ibit.apto
    assert any("stress tasas_2022 no aplica" in a for a in ibit.advertencias)
    assert any(a.startswith("historia corta") for a in ibit.advertencias)
    assert gestor.universo().diagnostico("VOOG").advertencias == ()


def test_diagnosticar_universo(gestor: GestorDatos) -> None:
    informe = gestor.diagnosticar()
    assert informe.activo_mas_corto == "IBIT"
    assert (informe.ventana_comun.inicio.isoformat(), informe.ventana_comun.meses) == (
        "2024-01-31",
        33,
    )
    tasas = next(s for s in informe.stress if s.escenario == "tasas_2022")
    assert tasas.completa == ("VOOG", "BNS", "VB") and tasas.ninguna == ("IBIT",)
    assert informe.estado_prior is EstadoPrior.CAPITALIZACION and informe.sin_cap == ()


# -------------------------------------------------------------------------- resolver
def test_ticker_inexistente_da_error_claro(gestor: GestorDatos) -> None:
    with pytest.raises(TickerNoResueltoError, match="ticker inexistente: ZZZZ"):
        gestor.resolver("ZZZZ")


def test_moneda_no_soportada(gestor: GestorDatos) -> None:
    with pytest.raises(TickerNoResueltoError, match=r"moneda no soportada.*'TSX'"):
        gestor.resolver("TSX")


def test_resolver_no_modifica_nada(gestor: GestorDatos) -> None:
    antes = gestor.ruta_universo.read_bytes()
    d = gestor.resolver("aapl")
    assert d.ticker == "AAPL" and d.apto
    assert (d.prior_provenance, d.prior_cap) == (PriorProvenance.FUENTE, pytest.approx(4.9))
    assert d.prior_as_of == cap_fuente().as_of and "marketCap" in (d.prior_fuente_detalle or "")
    assert gestor.ruta_universo.read_bytes() == antes
    assert not (gestor.directorio_series / "AAPL.csv").exists()


def test_etf_sin_cap_en_la_fuente_queda_pendiente(gestor: GestorDatos) -> None:
    d = gestor.resolver("QQQ")
    assert d.apto and not d.tiene_cap and d.prior_provenance is None


def test_no_apto_por_historia_insuficiente(gestor: GestorDatos) -> None:
    d = gestor.resolver("BEBE")
    assert not d.apto and "solo 6 meses" in d.advertencias[0]
    with pytest.raises(ActivoNoAptoError, match="solo 6 meses"):
        gestor.incorporar("BEBE", prior_cap=1.0, prior_metodologia="x")


# ------------------------------------------------------------------------ incorporar
def test_incorporar_accion_con_cap_de_la_fuente(gestor: GestorDatos) -> None:
    antes = gestor.universo()
    u = gestor.incorporar("AAPL")
    assert u.activos == (*ACTIVOS, "AAPL") and u.version != antes.version
    assert u.origenes["AAPL"] is OrigenActivo.AGREGADO_EN_SESION
    assert u.estado_prior is EstadoPrior.CAPITALIZACION
    assert gestor.universo() == u  # persistido y coherente con las series en disco
    panel = SeriesPriceProvider(gestor.directorio_series, list(u.activos)).precios()
    assert panel["AAPL"].notna().sum() == 61


def test_incorporar_con_cap_del_usuario_gana_a_la_fuente(gestor: GestorDatos) -> None:
    u = gestor.incorporar("AAPL", prior_cap=5.0, prior_metodologia="AUM: proxy débil")
    d = u.diagnostico("AAPL")
    assert (d.prior_cap, d.prior_provenance) == (5.0, PriorProvenance.USUARIO)
    assert d.prior_fuente_detalle == "AUM: proxy débil" and d.prior_as_of == AHORA.date()


def test_cap_de_usuario_exige_metodologia(gestor: GestorDatos) -> None:
    with pytest.raises(GestorError, match="exige prior_metodologia"):
        gestor.incorporar("QQQ", prior_cap=20.0)
    with pytest.raises(GestorError, match="falta el valor"):
        gestor.incorporar("QQQ", prior_metodologia="índice subyacente")
    assert gestor.universo().activos == ACTIVOS


def test_sin_cap_y_sin_aceptar_neutral_el_prior_queda_pendiente(gestor: GestorDatos) -> None:
    u = gestor.incorporar("QQQ")
    assert u.estado_prior is EstadoPrior.PENDIENTE and u.sin_cap == ("QQQ",)
    informe = gestor.diagnosticar()
    assert "Black-Litterman no disponible: falta la capitalización de QQQ" in informe.mensaje_prior
    assert "HRP y mínima varianza siguen operativos" in informe.mensaje_prior


def test_aceptar_neutral_degrada_todo_y_conserva_las_caps(gestor: GestorDatos) -> None:
    u = gestor.incorporar("QQQ", aceptar_neutral=True)
    assert u.estado_prior is EstadoPrior.NEUTRAL
    assert u.diagnostico("VOOG").prior_cap == 28.0
    # Llega la cap que faltaba: vuelve el prior de mercado sin consultar ninguna fuente.
    consultas = len(gestor.fuente.consultas_cap)  # type: ignore[union-attr]
    v = gestor.refrescar_cap("QQQ", prior_cap=22.0, prior_metodologia="cap del Nasdaq-100")
    assert v.estado_prior is EstadoPrior.CAPITALIZACION and not v.prior_neutral_aceptado
    assert len(gestor.fuente.consultas_cap) == consultas  # type: ignore[union-attr]


def test_aceptar_prior_neutral_despues_del_alta(gestor: GestorDatos) -> None:
    with pytest.raises(GestorError, match="nada que degradar"):
        gestor.aceptar_prior_neutral()
    pendiente = gestor.incorporar("QQQ")
    neutral = gestor.aceptar_prior_neutral()
    assert neutral.estado_prior is EstadoPrior.NEUTRAL and neutral.version != pendiente.version


def test_incorporar_repetido_o_desalineado(gestor: GestorDatos) -> None:
    with pytest.raises(GestorError, match="ya está en el universo"):
        gestor.incorporar("VOOG")
    with pytest.raises(GestorError, match="make update-prices antes de incorporar"):
        gestor.incorporar("VIEJO", prior_cap=1.0, prior_metodologia="x")
    assert not (gestor.directorio_series / "VIEJO.csv").exists()


def test_retorno_absurdo_no_entra(gestor: GestorDatos, fuente: FuenteFalsa) -> None:
    mala = serie_sintetica("MALA", 40, FIN)
    mala.iloc[20:] *= 3.0
    fuente.series["MALA"] = mala
    with pytest.raises(ActivoNoAptoError, match="retorno_absurdo"):
        gestor.incorporar("MALA", prior_cap=1.0, prior_metodologia="x")
    assert gestor.universo().activos == ACTIVOS


# --------------------------------------------------------------------- refrescar_cap
def test_refrescar_cap_registra_el_cambio_y_altera_la_version(gestor: GestorDatos) -> None:
    antes = gestor.universo()
    despues = gestor.refrescar_cap("BNS", prior_cap=0.125, prior_metodologia="cap bursátil 2026-10")
    assert despues.version != antes.version
    assert despues.diagnostico("BNS").prior_cap == 0.125
    ultima = json.loads(gestor.ruta_historial.read_text(encoding="utf-8").splitlines()[-1])
    assert ultima["accion"] == "refrescar_cap" and ultima["ticker"] == "BNS"
    assert ultima["prior_antes"]["cap"] == 0.116 and ultima["prior_despues"]["cap"] == 0.125
    assert (ultima["version_antes"], ultima["version_despues"]) == (antes.version, despues.version)


def test_refrescar_cap_desde_la_fuente_o_error_claro(gestor: GestorDatos) -> None:
    gestor.incorporar("AAPL", prior_cap=5.0, prior_metodologia="a ojo")
    u = gestor.refrescar_cap("AAPL")
    assert u.diagnostico("AAPL").prior_provenance is PriorProvenance.FUENTE
    with pytest.raises(GestorError, match=r"no expone su capitalización.*no AUM"):
        gestor.refrescar_cap("VOOG")
    with pytest.raises(GestorError, match="no está en el universo"):
        gestor.refrescar_cap("TSLA")


# -------------------------------------------------------------------- sincronización
def test_universo_desincronizado_de_las_series(gestor: GestorDatos, config: Config) -> None:
    from investmentsys.data.actualizacion import escribir_series_atomico

    panel = panel_referencia()
    siguiente = panel.index[-1] + pd.offsets.MonthEnd(1)
    ampliado = pd.concat([panel, (panel.iloc[[-1]] * 1.01).set_axis([siguiente])])
    escribir_series_atomico(ampliado, gestor.directorio_series, config.datos.actualizacion, "m2")
    with pytest.raises(UniversoDesincronizadoError, match="make update-prices"):
        gestor.universo()
    previo = Universe.model_validate_json(gestor.ruta_universo.read_text(encoding="utf-8"))
    nuevo = gestor.sincronizar()
    assert nuevo.version != previo.version
    assert nuevo.diagnostico("VOOG").meses_disponibles == 62
    assert nuevo.diagnostico("VOOG").prior_cap == 28.0  # las caps no se tocan al sincronizar
    assert gestor.universo() == nuevo
