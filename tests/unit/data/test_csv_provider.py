from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from investmentsys.data import CSVPriceProvider, DatosInvalidosError
from tests.conftest import CSV_REFERENCIA

ACTIVOS = ("VOOG", "BNS", "IBIT", "VB")


@pytest.fixture(scope="module")
def provider() -> CSVPriceProvider:
    return CSVPriceProvider(CSV_REFERENCIA)


def _csv(tmp_path: Path, contenido: str) -> Path:
    ruta = tmp_path / "precios.csv"
    ruta.write_text(contenido.strip() + "\n")
    return ruta


# --- lectura del fixture congelado -----------------------------------------------------


def test_lee_el_csv_del_repo(provider: CSVPriceProvider) -> None:
    precios = provider.precios()
    assert provider.activos() == ("VOOG", "BNS", "VB", "IBIT")  # orden de la fuente
    assert precios.shape == (61, 4)
    assert precios.index[0] == pd.Timestamp("2021-09-30")
    assert precios.index[-1] == pd.Timestamp("2026-09-30")
    assert provider.periodos_por_anio == 12


def test_reordena_al_orden_canonico(provider: CSVPriceProvider) -> None:
    assert tuple(provider.precios(ACTIVOS).columns) == ACTIVOS


def test_inicio_tardio_de_ibit(provider: CSVPriceProvider) -> None:
    ibit = provider.precios(["IBIT"])["IBIT"]
    assert provider.fecha_inicio("IBIT") == date(2024, 1, 31)
    assert provider.fecha_inicio("VOOG") == date(2021, 9, 30)
    assert ibit.loc[:"2023-12-31"].isna().all()
    assert ibit.loc["2024-01-31":].notna().all()
    assert ibit.notna().sum() == 33


def test_retornos_logaritmicos(provider: CSVPriceProvider) -> None:
    r = provider.retornos_log(ACTIVOS)
    assert r.shape == (60, 4)
    assert r.index[0] == pd.Timestamp("2021-10-31")
    assert r.loc["2021-10-31", "VOOG"] == pytest.approx(math.log(46.79 / 42.88))
    assert r["IBIT"].notna().sum() == 32
    assert math.isnan(r.loc["2024-01-31", "IBIT"])  # primer precio, aún sin retorno
    assert r.loc["2024-02-29", "IBIT"] == pytest.approx(math.log(35.42 / 24.30))
    assert r[["VOOG", "BNS", "VB"]].notna().all().all()


def test_hasta_recorta_sin_look_ahead(provider: CSVPriceProvider) -> None:
    precios = provider.precios(ACTIVOS, hasta=date(2024, 12, 31))
    assert precios.index[-1] == pd.Timestamp("2024-12-31")
    assert len(precios) == 40
    retornos = provider.retornos_log(ACTIVOS, hasta=date(2024, 12, 15))
    assert retornos.index[-1] == pd.Timestamp("2024-11-30")  # el 15/12 aún no cerró diciembre


def test_hasta_anterior_al_inicio_es_error(provider: CSVPriceProvider) -> None:
    with pytest.raises(DatosInvalidosError, match="sin precios hasta"):
        provider.precios(hasta=date(2020, 1, 31))


def test_activo_desconocido(provider: CSVPriceProvider) -> None:
    with pytest.raises(KeyError, match="AAPL"):
        provider.precios(["AAPL"])


def test_es_determinista_y_devuelve_copias(provider: CSVPriceProvider) -> None:
    a, b = provider.precios(ACTIVOS), provider.precios(ACTIVOS)
    pd.testing.assert_frame_equal(a, b)
    a.iloc[0, 0] = -1.0
    assert provider.precios(ACTIVOS).iloc[0, 0] == 42.88


# --- validación del formato -------------------------------------------------------------


def test_archivo_inexistente(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        CSVPriceProvider(tmp_path / "no_existe.csv")


@pytest.mark.parametrize(
    ("contenido", "mensaje"),
    [
        ("dia,A\n2021-09,1", "falta la columna"),
        ("fecha\n2021-09", "no hay columnas de activos"),
        ("fecha,A\n2021-09-01,1\n2021-10-01,2", "formato distinto"),
        ("fecha,A\n2021-09,1\n2021-09,2", "duplicadas"),
        ("fecha,A\n2021-10,1\n2021-09,2", "orden ascendente"),
        ("fecha,A\n2021-09,1\n2021-11,2", "meses faltantes"),
        ("fecha,A\n2021-09,1\n2021-10,0\n2021-11,2", "no positivos"),
        ("fecha,A\n2021-09,1\n2021-10,\n2021-11,2", "huecos después"),
        ("fecha,A,B\n2021-09,1,\n2021-10,2,", "B no tiene ningún precio"),
    ],
)
def test_csv_invalido(tmp_path: Path, contenido: str, mensaje: str) -> None:
    with pytest.raises(DatosInvalidosError, match=mensaje):
        CSVPriceProvider(_csv(tmp_path, contenido))


def test_inicio_tardio_es_valido(tmp_path: Path) -> None:
    p = CSVPriceProvider(_csv(tmp_path, "fecha,A,B\n2021-09,1,\n2021-10,2,\n2021-11,4,8"))
    assert p.fecha_inicio("B") == date(2021, 11, 30)
    r = p.retornos_log(["A", "B"])
    assert r["A"].tolist() == pytest.approx([math.log(2), math.log(2)])
    assert r["B"].isna().all()
