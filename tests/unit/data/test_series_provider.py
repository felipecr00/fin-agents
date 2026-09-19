"""``SeriesPriceProvider`` y la escritura todo-o-nada de ``data/series`` (S7)."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from investmentsys.config import ActualizacionConfig, cargar_config
from investmentsys.data import CSVPriceProvider, DatosInvalidosError, SeriesPriceProvider
from investmentsys.data import actualizacion as modulo
from investmentsys.data.actualizacion import Estado, actualizar_precios, escribir_series_atomico
from tests.conftest import ACTIVOS, CSV_REFERENCIA
from tests.unit.data.test_actualizacion import _con_mes_nuevo, _Fuente

INICIO = date(2021, 9, 1)


@pytest.fixture(scope="module")
def config() -> ActualizacionConfig:
    return cargar_config().datos.actualizacion


@pytest.fixture(scope="module")
def referencia() -> pd.DataFrame:
    return CSVPriceProvider(CSV_REFERENCIA).precios(list(ACTIVOS))


@pytest.fixture
def almacen(tmp_path: Path, referencia: pd.DataFrame, config: ActualizacionConfig) -> Path:
    destino = tmp_path / "series"
    assert escribir_series_atomico(referencia, destino, config, "m0") is None
    return destino


def _foto(directorio: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(directorio)): p.read_bytes()
        for p in sorted(directorio.rglob("*"))
        if p.is_file()
    }


def _actualizar(panel: pd.DataFrame, almacen: Path, config: ActualizacionConfig, **kw: Any) -> Any:
    return actualizar_precios(
        _Fuente(panel),
        ACTIVOS,
        almacen,
        config,
        INICIO,
        hoy=kw.pop("hoy", date(2026, 11, 3)),
        ahora=datetime(2026, 11, 3, 12, 0, 0, tzinfo=UTC),
        nombre_fuente="falsa",
        **kw,
    )


def test_el_panel_de_series_es_identico_al_del_csv_unico(
    almacen: Path, referencia: pd.DataFrame
) -> None:
    provider = SeriesPriceProvider(almacen)
    assert provider.activos() == tuple(sorted(ACTIVOS))
    pd.testing.assert_frame_equal(provider.precios(list(ACTIVOS)), referencia)
    hasta = provider.precios(["IBIT", "VB"], hasta=date(2024, 3, 31))
    assert list(hasta.columns) == ["IBIT", "VB"] and hasta.index[-1] == pd.Timestamp("2024-03-31")
    assert (almacen / "IBIT.csv").read_text().splitlines()[1].startswith("2024-01,")


def test_activo_sin_serie_y_columna_equivocada(almacen: Path) -> None:
    with pytest.raises(KeyError, match="incorpóralo antes"):
        SeriesPriceProvider(almacen, ["TSLA"]).precios()
    (almacen / "TSLA.csv").write_text((almacen / "VB.csv").read_text())
    with pytest.raises(DatosInvalidosError, match="única columna 'TSLA'"):
        SeriesPriceProvider(almacen, ["TSLA"]).precios()


def test_almacen_a_medio_actualizar_es_un_error(almacen: Path) -> None:
    lineas = (almacen / "BNS.csv").read_text().splitlines()
    (almacen / "BNS.csv").write_text("\n".join(lineas[:-1]) + "\n")
    with pytest.raises(DatosInvalidosError, match=r"no llegan a 2026-09: \['BNS'\]"):
        SeriesPriceProvider(almacen, list(ACTIVOS)).precios()


def test_actualizacion_escribe_con_respaldo_y_luego_sin_cambios(
    almacen: Path, referencia: pd.DataFrame, config: ActualizacionConfig
) -> None:
    antes = _foto(almacen)
    nuevo = _con_mes_nuevo(referencia)
    r = _actualizar(nuevo, almacen, config)
    assert r.estado is Estado.ESCRITO and r.continuidad is not None and r.continuidad.ok
    assert r.backup is not None and _foto(Path(r.backup)) == antes
    assert SeriesPriceProvider(almacen, list(ACTIVOS)).precios().index[-1] == pd.Timestamp(
        "2026-10-31"
    )
    assert not list(almacen.glob(".*.tmp"))
    assert _actualizar(nuevo, almacen, config).estado is Estado.SIN_CAMBIOS


def test_discrepancia_de_continuidad_deja_el_almacen_intacto(
    almacen: Path, referencia: pd.DataFrame, config: ActualizacionConfig
) -> None:
    antes = _foto(almacen)
    alterado = _con_mes_nuevo(referencia)
    alterado.loc[pd.Timestamp("2023-09-30"), "BNS"] *= 1.03
    r = _actualizar(alterado, almacen, config)
    assert r.estado is Estado.ABORTADO and "continuidad" in r.motivo
    assert _foto(almacen) == antes


def test_fallo_a_mitad_de_los_reemplazos_restaura_todo(
    almacen: Path,
    referencia: pd.DataFrame,
    config: ActualizacionConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    antes = _foto(almacen)
    real, llamadas = os.replace, []

    def falla_al_tercero(origen: Any, destino: Any) -> None:
        llamadas.append(destino)
        if len(llamadas) == 3:
            raise OSError("disco lleno")
        real(origen, destino)

    monkeypatch.setattr(modulo.os, "replace", falla_al_tercero)
    with pytest.raises(OSError, match="disco lleno"):
        escribir_series_atomico(_con_mes_nuevo(referencia), almacen, config, "m1")
    assert _foto(almacen) == antes  # ni series mezcladas, ni temporales, ni respaldo huérfano


def test_se_conservan_solo_los_ultimos_respaldos(
    almacen: Path, referencia: pd.DataFrame, config: ActualizacionConfig
) -> None:
    panel = referencia
    for i in range(config.backups_a_conservar + 2):
        panel = _con_mes_nuevo(panel, factor=1.01)
        escribir_series_atomico(panel, almacen, config, f"2026100{i}T120000")
    respaldos = sorted(p.name for p in (almacen / ".backups").iterdir())
    assert len(respaldos) == config.backups_a_conservar and respaldos[-1] == "20261004T120000"
