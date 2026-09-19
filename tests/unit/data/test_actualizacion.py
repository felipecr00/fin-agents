"""``data.actualizacion``: las tres barreras de ``make update-prices``. Sin red: la fuente es un
``PriceProvider`` falso construido a partir del fixture congelado.

Lo que importa de cada aborto no es solo el estado: es que el CSV vigente queda byte a byte
como estaba, sin respaldos ni temporales nuevos en la carpeta.
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from investmentsys.config import ActualizacionConfig, cargar_config
from investmentsys.data import CSVPriceProvider, PriceProvider
from investmentsys.data import actualizacion as modulo
from investmentsys.data.actualizacion import (
    Estado,
    ResumenActualizacion,
    actualizar_precios,
    escribir_csv_atomico,
    formatear_resumen,
    guardar_resumen,
    validar_continuidad,
    validar_sanidad,
)
from tests.conftest import CSV_REFERENCIA

ACTIVOS = ("VOOG", "BNS", "IBIT", "VB")
# El fixture termina en 2026-09 (mes que en su día se cargó sin cerrar). Con hoy = 2026-10-05
# todos sus meses están cerrados; con hoy = 2026-09-19, el último es provisional.
HOY = date(2026, 10, 5)
AHORA = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
INICIO = date(2021, 9, 1)


class _Fuente(PriceProvider):
    """``PriceProvider`` en memoria: hace de Tiingo."""

    def __init__(self, panel: pd.DataFrame) -> None:
        self._panel = panel

    @property
    def periodos_por_anio(self) -> int:
        return 12

    def activos(self) -> tuple[str, ...]:
        return tuple(str(c) for c in self._panel.columns)

    def precios(
        self, activos: Sequence[str] | None = None, hasta: date | None = None
    ) -> pd.DataFrame:
        return self._panel.loc[:, list(activos or self.activos())].copy()


@pytest.fixture(scope="module")
def config() -> ActualizacionConfig:
    return cargar_config().datos.actualizacion


@pytest.fixture(scope="module")
def referencia() -> pd.DataFrame:
    return CSVPriceProvider(CSV_REFERENCIA).precios()


@pytest.fixture
def csv_vigente(tmp_path: Path) -> Path:
    destino = tmp_path / "data" / "precios.csv"
    destino.parent.mkdir()
    shutil.copy(CSV_REFERENCIA, destino)
    return destino


def _con_mes_nuevo(panel: pd.DataFrame, factor: float = 1.02) -> pd.DataFrame:
    siguiente = panel.index[-1] + pd.offsets.MonthEnd(1)
    return pd.concat([panel, (panel.iloc[[-1]] * factor).set_axis([siguiente])])


def _actualizar(
    panel: pd.DataFrame,
    ruta: Path,
    config: ActualizacionConfig,
    hoy: date = HOY,
    ahora: datetime = AHORA,
    **opciones: bool,
) -> ResumenActualizacion:
    return actualizar_precios(
        _Fuente(panel),
        ACTIVOS,
        ruta,
        config,
        INICIO,
        hoy=hoy,
        ahora=ahora,
        nombre_fuente="falsa",
        **opciones,
    )


def _carpeta_intacta(ruta: Path, antes: bytes) -> bool:
    return ruta.read_bytes() == antes and [p.name for p in ruta.parent.iterdir()] == [ruta.name]


# --- camino feliz --------------------------------------------------------------------------


def test_mes_nuevo_empalma_y_se_escribe_con_respaldo(
    referencia: pd.DataFrame, csv_vigente: Path, config: ActualizacionConfig
) -> None:
    antes = csv_vigente.read_bytes()
    hoy = date(2026, 11, 3)
    r = _actualizar(_con_mes_nuevo(referencia), csv_vigente, config, hoy=hoy)

    assert r.estado is Estado.ESCRITO
    assert r.continuidad is not None and r.continuidad.ok
    assert [c.meses_nuevos for c in r.cobertura] == [("2026-10",)] * 4
    assert {c.activo: c.meses_descargados for c in r.cobertura} == {
        "VOOG": 62,
        "BNS": 62,
        "VB": 62,
        "IBIT": 34,
    }
    escrito = CSVPriceProvider(csv_vigente)
    assert escrito.activos() == ("VOOG", "BNS", "VB", "IBIT")  # orden de columnas del vigente
    assert escrito.precios().index[-1] == pd.Timestamp("2026-10-31")
    assert r.backup is not None and Path(r.backup).read_bytes() == antes
    assert Path(r.backup).name == "precios_backup_20261005T120000.csv"


def test_niveles_reescalados_no_rompen_la_continuidad(
    referencia: pd.DataFrame, csv_vigente: Path, config: ActualizacionConfig
) -> None:
    """Un dividendo nuevo reescala TODO el histórico ajustado: cambian niveles, no retornos."""
    reescalado = referencia * 0.97
    r = _actualizar(reescalado, csv_vigente, config, simular=True)
    assert r.estado is Estado.SIMULACION
    assert r.continuidad is not None and r.continuidad.ok
    assert all(
        a.diferencia_maxima is not None and a.diferencia_maxima < 1e-3
        for a in r.continuidad.por_activo
    )


def test_sin_cambios_no_escribe_ni_respalda(csv_vigente: Path, config: ActualizacionConfig) -> None:
    antes = csv_vigente.read_bytes()
    panel = CSVPriceProvider(csv_vigente).precios()
    primera = _actualizar(panel, csv_vigente, config)  # normaliza el formato (4 decimales)
    assert primera.estado is Estado.ESCRITO
    normalizado = csv_vigente.read_bytes()
    assert normalizado != antes
    segunda = _actualizar(panel, csv_vigente, config, ahora=AHORA + timedelta(hours=1))
    assert segunda.estado is Estado.SIN_CAMBIOS and segunda.backup is None
    assert csv_vigente.read_bytes() == normalizado
    assert len(list(csv_vigente.parent.glob("precios_backup_*"))) == 1


def test_simulacion_no_toca_nada(
    referencia: pd.DataFrame, csv_vigente: Path, config: ActualizacionConfig
) -> None:
    antes = csv_vigente.read_bytes()
    r = _actualizar(
        _con_mes_nuevo(referencia), csv_vigente, config, hoy=date(2026, 11, 3), simular=True
    )
    assert r.estado is Estado.SIMULACION and r.backup is None
    assert _carpeta_intacta(csv_vigente, antes)


def test_sin_csv_vigente_lo_crea(
    referencia: pd.DataFrame, tmp_path: Path, config: ActualizacionConfig
) -> None:
    destino = tmp_path / "nuevo" / "precios.csv"
    r = _actualizar(referencia, destino, config)
    assert r.estado is Estado.ESCRITO and r.continuidad is None and r.backup is None
    assert CSVPriceProvider(destino).precios().shape == (61, 4)


def test_el_mes_en_curso_nunca_se_escribe_ni_se_compara(
    referencia: pd.DataFrame, csv_vigente: Path, config: ActualizacionConfig
) -> None:
    """Situación real del 2026-09-19: el vigente trae 2026-09 provisional y la fuente, por si
    acaso, también. No se compara (no es comparable) y no se escribe."""
    otro_septiembre = referencia.copy()
    otro_septiembre.iloc[-1] *= 1.08  # el precio "de hoy" ya no es el que se cargó a mano
    r = _actualizar(otro_septiembre, csv_vigente, config, hoy=date(2026, 9, 19))
    assert r.ultimo_mes_cerrado == "2026-08"
    assert r.continuidad is not None and r.continuidad.ok
    assert r.continuidad.meses_provisionales_excluidos == ("2026-09",)
    assert r.continuidad.ventana == ("2021-10", "2026-08")
    assert r.estado is Estado.ESCRITO
    assert CSVPriceProvider(csv_vigente).precios().index[-1] == pd.Timestamp("2026-08-31")
    septiembre = [f for f in r.diff_ultimos_meses if f.mes == "2026-09"]
    assert len(septiembre) == 4 and all(f.nuevo is None and f.vigente for f in septiembre)


# --- aborto por continuidad ------------------------------------------------------------------


def test_discrepancia_inyectada_aborta_sin_escribir_y_dice_donde(
    referencia: pd.DataFrame, csv_vigente: Path, config: ActualizacionConfig
) -> None:
    antes = csv_vigente.read_bytes()
    alterado = _con_mes_nuevo(referencia)
    alterado.loc["2024-03-31", "BNS"] *= 1.02  # +2 %: mueve los retornos de 2024-03 y 2024-04

    r = _actualizar(alterado, csv_vigente, config, hoy=date(2026, 11, 3))

    assert r.estado is Estado.ABORTADO and "continuidad" in r.motivo
    assert r.continuidad is not None and not r.continuidad.ok
    assert [(d.activo, d.mes) for d in r.continuidad.discrepancias] == [
        ("BNS", "2024-03"),
        ("BNS", "2024-04"),
    ]
    assert all(d.diferencia > config.tolerancia_continuidad for d in r.continuidad.discrepancias)
    assert _carpeta_intacta(csv_vigente, antes)
    texto = formatear_resumen(r)
    assert "ABORTADO" in texto and "| BNS | 2024-03 |" in texto


def test_diferencia_dentro_de_la_tolerancia_no_aborta(
    referencia: pd.DataFrame, csv_vigente: Path, config: ActualizacionConfig
) -> None:
    casi = referencia.copy()
    casi.loc["2024-03-31", "BNS"] *= 1.0 + config.tolerancia_continuidad / 2
    assert _actualizar(casi, csv_vigente, config, simular=True).estado is Estado.SIMULACION


def test_aceptar_discrepancias_es_una_decision_explicita_y_queda_registrada(
    referencia: pd.DataFrame, csv_vigente: Path, config: ActualizacionConfig
) -> None:
    alterado = referencia.copy()
    alterado.loc["2024-03-31", "BNS"] *= 1.02
    r = _actualizar(alterado, csv_vigente, config, aceptar_discrepancias=True)
    assert r.estado is Estado.ESCRITO and r.discrepancias_aceptadas
    assert "2 discrepancia(s) de continuidad ACEPTADAS" in r.motivo  # nunca "en verde"
    assert r.continuidad is not None and len(r.continuidad.discrepancias) == 2
    assert "ACEPTADAS por el operador" in formatear_resumen(r)


def test_perder_historia_aborta_aunque_se_acepten_discrepancias(
    referencia: pd.DataFrame, csv_vigente: Path, config: ActualizacionConfig
) -> None:
    antes = csv_vigente.read_bytes()
    r = _actualizar(referencia.iloc[:-2], csv_vigente, config, aceptar_discrepancias=True)
    assert r.estado is Estado.ABORTADO and "pierde meses" in r.motivo
    assert r.continuidad is not None
    assert r.continuidad.meses_perdidos["VOOG"] == ("2026-08", "2026-09")
    assert _carpeta_intacta(csv_vigente, antes)


def test_continuidad_compara_retornos_solo_donde_ambos_existen(referencia: pd.DataFrame) -> None:
    c = validar_continuidad(referencia, referencia, 0.005, pd.Timestamp("2026-09-30"))
    por_activo = {a.activo: a.meses_comparados for a in c.por_activo}
    assert por_activo == {"VOOG": 60, "BNS": 60, "VB": 60, "IBIT": 32}
    assert c.ok and c.ventana == ("2021-10", "2026-09")


# --- aborto por sanidad --------------------------------------------------------------------


def test_retorno_absurdo_inyectado_aborta_sin_escribir(
    referencia: pd.DataFrame, csv_vigente: Path, config: ActualizacionConfig
) -> None:
    antes = csv_vigente.read_bytes()
    absurdo = _con_mes_nuevo(referencia)
    absurdo.loc["2026-10-31", "IBIT"] = absurdo.loc["2026-09-30", "IBIT"] * 1.75  # +75 % > 60 %

    r = _actualizar(absurdo, csv_vigente, config, hoy=date(2026, 11, 3), aceptar_discrepancias=True)

    assert r.estado is Estado.ABORTADO and "sanidad" in r.motivo
    assert [(p.regla, p.activo, p.mes) for p in r.sanidad] == [
        ("retorno_absurdo", "IBIT", "2026-10")
    ]
    assert r.continuidad is None  # no tiene sentido comparar un panel insano
    assert _carpeta_intacta(csv_vigente, antes)


def test_un_retorno_grande_pero_creible_de_ibit_pasa(
    referencia: pd.DataFrame, config: ActualizacionConfig
) -> None:
    volatil = _con_mes_nuevo(referencia)
    volatil.loc["2026-10-31", "IBIT"] = volatil.loc["2026-09-30", "IBIT"] * 1.45
    assert validar_sanidad(volatil, config, INICIO) == ()


def _reglas(panel: pd.DataFrame, config: ActualizacionConfig) -> set[tuple[str, str | None]]:
    return {(p.regla, p.activo) for p in validar_sanidad(panel, config, INICIO)}


def test_sanidad_detecta_cada_tipo_de_problema(
    referencia: pd.DataFrame, config: ActualizacionConfig
) -> None:
    assert validar_sanidad(referencia, config, INICIO) == ()

    duplicado = pd.concat([referencia, referencia.iloc[[-1]]])
    assert _reglas(duplicado, config) == {("fecha_duplicada", None)}

    sin_un_mes = referencia.drop(index=pd.Timestamp("2023-05-31"))
    assert ("mes_faltante", None) in _reglas(sin_un_mes, config)

    con_hueco = referencia.copy()
    con_hueco.loc["2025-02-28", "VB"] = np.nan
    assert _reglas(con_hueco, config) == {("hueco", "VB")}

    negativo = referencia.copy()
    negativo.loc["2022-06-30", "VOOG"] = 0.0
    assert ("precio_no_positivo", "VOOG") in _reglas(negativo, config)

    assert _reglas(referencia.iloc[0:0], config) == {("panel_vacio", None)}


def test_solo_los_activos_declarados_pueden_empezar_tarde(
    referencia: pd.DataFrame, config: ActualizacionConfig
) -> None:
    assert "IBIT" in config.activos_inicio_tardio
    tardio = referencia.copy()
    tardio.loc[:"2021-12-31", "BNS"] = np.nan
    assert _reglas(tardio, config) == {("inicio_inesperado", "BNS")}


# --- escritura atómica ---------------------------------------------------------------------


def test_fallo_durante_el_reemplazo_deja_el_vigente_intacto(
    referencia: pd.DataFrame,
    csv_vigente: Path,
    config: ActualizacionConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    antes = csv_vigente.read_bytes()

    def falla(*_: object) -> None:
        raise OSError("disco lleno")

    monkeypatch.setattr(modulo.os, "replace", falla)
    with pytest.raises(OSError, match="disco lleno"):
        escribir_csv_atomico(_con_mes_nuevo(referencia), csv_vigente, config, "20261103T000000")
    assert csv_vigente.read_bytes() == antes
    assert not list(csv_vigente.parent.glob(".*.tmp"))  # el temporal se limpia


def test_un_csv_que_el_consumidor_no_puede_leer_nunca_reemplaza_al_vigente(
    referencia: pd.DataFrame, csv_vigente: Path, config: ActualizacionConfig
) -> None:
    """Se salta la sanidad a propósito: la escritura relee el temporal con CSVPriceProvider."""
    antes = csv_vigente.read_bytes()
    con_hueco = referencia.copy()
    con_hueco.loc["2025-02-28", "VB"] = np.nan
    with pytest.raises(ValueError, match="huecos"):
        escribir_csv_atomico(con_hueco, csv_vigente, config, "20261103T000000")
    assert _carpeta_intacta(csv_vigente, antes)


def test_el_temporal_vive_en_la_carpeta_del_destino(
    referencia: pd.DataFrame,
    csv_vigente: Path,
    config: ActualizacionConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``os.replace`` solo es atómico dentro de un mismo sistema de archivos."""
    vistos: list[tuple[Path, Path]] = []
    original = modulo.os.replace

    def espia(origen: Path, destino: Path) -> None:
        vistos.append((Path(origen), Path(destino)))
        original(origen, destino)

    monkeypatch.setattr(modulo.os, "replace", espia)
    escribir_csv_atomico(referencia, csv_vigente, config, "20261103T000000")
    ((origen, destino),) = vistos
    assert origen.parent == destino.parent == csv_vigente.parent and destino == csv_vigente


def test_conserva_solo_los_ultimos_respaldos(
    referencia: pd.DataFrame, csv_vigente: Path, config: ActualizacionConfig
) -> None:
    panel = referencia
    for i in range(config.backups_a_conservar + 2):
        panel = panel * 1.001  # cada vuelta cambia el contenido (niveles, no retornos)
        r = _actualizar(panel, csv_vigente, config, ahora=AHORA + timedelta(days=i))
        assert r.estado is Estado.ESCRITO
    respaldos = sorted(p.name for p in csv_vigente.parent.glob("precios_backup_*.csv"))
    assert respaldos == [
        "precios_backup_20261007T120000.csv",
        "precios_backup_20261008T120000.csv",
        "precios_backup_20261009T120000.csv",
    ]


def test_formato_del_csv_escrito(
    referencia: pd.DataFrame, csv_vigente: Path, config: ActualizacionConfig
) -> None:
    _actualizar(referencia * 1.00001, csv_vigente, config)
    lineas = csv_vigente.read_text().splitlines()
    assert lineas[0] == "fecha,VOOG,BNS,VB,IBIT"
    assert lineas[1].startswith("2021-09,42.8804,") and lineas[1].endswith(",")  # IBIT vacío
    assert len(lineas) == 62


# --- resumen -------------------------------------------------------------------------------


def test_resumen_se_guarda_en_json_y_markdown_tambien_si_aborta(
    referencia: pd.DataFrame, csv_vigente: Path, config: ActualizacionConfig, tmp_path: Path
) -> None:
    r = _actualizar(referencia.iloc[:-2], csv_vigente, config)
    carpeta = guardar_resumen(r, tmp_path / "runs" / "actualizaciones")
    assert carpeta.name == "20261005T120000"
    releido = ResumenActualizacion.model_validate_json((carpeta / "resumen.json").read_text())
    assert releido == r
    markdown = (carpeta / "resumen.md").read_text()
    assert "ninguna salida constituye asesoría financiera" in markdown


def test_misma_entrada_misma_salida(
    referencia: pd.DataFrame, csv_vigente: Path, config: ActualizacionConfig
) -> None:
    panel = _con_mes_nuevo(referencia)
    a = _actualizar(panel, csv_vigente, config, hoy=date(2026, 11, 3), simular=True)
    b = _actualizar(panel, csv_vigente, config, hoy=date(2026, 11, 3), simular=True)
    assert a == b and a.sha256_nuevo == b.sha256_nuevo
