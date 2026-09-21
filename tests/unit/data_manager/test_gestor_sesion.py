"""Universo de SESIÓN (ADR-023, lienzo en blanco): el Gestor opera sobre la base que recibe.

Con ``base`` distinta de ``GUARDADO`` nada de lo persistido cambia: ni ``universo.json``, ni su
historial, ni las series del universo guardado. El modo comando sigue leyendo lo de siempre.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from investmentsys.config import Config, cargar_config
from investmentsys.contracts import EstadoPrior, OrigenActivo, PriorProvenance
from investmentsys.data_manager import GestorDatos, GestorError
from tests.almacen import FuenteFalsa, cap_fuente, sembrar_gestor, serie_sintetica
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
            "MSFT": serie_sintetica("MSFT", 40, FIN, semilla=4),
            "QQQ": serie_sintetica("QQQ", 61, FIN, semilla=11),  # ETF: sin cap en la fuente
            "BEBE": serie_sintetica("BEBE", 6, FIN, semilla=5),  # no apto
            "VIEJO": serie_sintetica("VIEJO", 61, FIN - pd.offsets.MonthEnd(1), semilla=2),
        },
        caps={"AAPL": cap_fuente(), "MSFT": cap_fuente(3.1e12), "VIEJO": cap_fuente(1e11)},
    )


@pytest.fixture
def gestor(tmp_path: Path, config: Config, fuente: FuenteFalsa) -> GestorDatos:
    return sembrar_gestor(tmp_path, config, fuente)


def _persistido(gestor: GestorDatos) -> tuple[bytes, bytes, dict[str, bytes]]:
    series = {a: (gestor.directorio_series / f"{a}.csv").read_bytes() for a in ACTIVOS}
    return gestor.ruta_universo.read_bytes(), gestor.ruta_historial.read_bytes(), series


def test_desde_la_mesa_limpia_el_universo_es_solo_lo_ingresado_y_nada_persistido_cambia(
    gestor: GestorDatos,
) -> None:
    antes = _persistido(gestor)
    uno = gestor.incorporar("aapl", base=None)
    dos = gestor.incorporar("MSFT", base=uno)

    assert uno.activos == ("AAPL",) and dos.activos == ("AAPL", "MSFT")
    assert uno.version != dos.version != gestor.universo().version
    assert set(dos.origenes.values()) == {OrigenActivo.AGREGADO_EN_SESION}
    assert dos.diagnostico("AAPL").prior_provenance is PriorProvenance.FUENTE
    assert _persistido(gestor) == antes, "el guardado es del modo comando: no se toca"
    assert gestor.universo().activos == ACTIVOS
    # Las series nuevas quedan en el almacén como caché: el núcleo las lee de ahí.
    assert list(gestor.provider().precios(["AAPL", "MSFT"]).columns) == ["AAPL", "MSFT"]
    # La ventana común sale ESTRICTAMENTE de lo ingresado: la limita MSFT, no IBIT.
    informe = gestor.diagnosticar(dos)
    assert informe.activo_mas_corto == "MSFT" and informe.ventana_comun.meses == 40


def test_un_activo_del_guardado_entra_con_su_serie_y_su_cap_congelada_sin_redescargar(
    gestor: GestorDatos, fuente: FuenteFalsa
) -> None:
    """Desde una sesión jamás se sobrescribe una serie validada por ``make update-prices``."""
    fuente.series["VOOG"] = serie_sintetica("VOOG", 61, FIN, semilla=99)  # la fuente "cambió"
    antes = _persistido(gestor)
    universo = gestor.incorporar("VOOG", base=None)
    assert universo.diagnostico("VOOG") == gestor.universo().diagnostico("VOOG")
    assert universo.diagnostico("VOOG").prior_provenance is PriorProvenance.USUARIO
    assert _persistido(gestor) == antes
    assert "VOOG" not in fuente.consultas_cap


def test_alta_por_lista_entra_lo_que_no_requiere_decision_y_el_resto_queda_dicho(
    gestor: GestorDatos,
) -> None:
    antes = _persistido(gestor)
    lista = ["aapl", "QQQ", "BEBE", "NOEXISTE", "MSFT", "AAPL"]
    resultado = gestor.incorporar_lista(lista, base=None)

    assert resultado.incorporados == ("AAPL", "MSFT")
    assert resultado.universo is not None and resultado.universo.activos == ("AAPL", "MSFT")
    assert [d.ticker for d in resultado.pendientes_de_prior] == ["QQQ"], "la cascada no se salta"
    assert set(resultado.rechazados) == {"BEBE", "NOEXISTE"}
    assert "no es apto" in resultado.rechazados["BEBE"]
    assert "inexistente" in resultado.rechazados["NOEXISTE"]
    assert resultado.universo.estado_prior is EstadoPrior.CAPITALIZACION
    assert _persistido(gestor) == antes

    # El pendiente entra después, uno por uno, con lo que responda el usuario.
    con_etf = gestor.incorporar(
        "QQQ", 22.0, "capitalización del Nasdaq-100", base=resultado.universo
    )
    assert con_etf.activos == ("AAPL", "MSFT", "QQQ")
    assert con_etf.estado_prior is EstadoPrior.CAPITALIZACION


def test_si_nada_entra_no_hay_universo(gestor: GestorDatos) -> None:
    resultado = gestor.incorporar_lista(["QQQ", "NOEXISTE"], base=None)
    assert resultado.universo is None and resultado.incorporados == ()
    assert [d.ticker for d in resultado.pendientes_de_prior] == ["QQQ"]


def test_resolver_lista_da_la_ventana_si_entran_todos_sin_modificar_nada(
    gestor: GestorDatos,
) -> None:
    antes = _persistido(gestor)
    diagnosticos, rechazados, informe = gestor.resolver_lista(["AAPL", "QQQ", "BEBE", "NOEXISTE"])
    assert [d.ticker for d in diagnosticos] == ["AAPL", "QQQ", "BEBE"]
    assert set(rechazados) == {"NOEXISTE"}
    assert informe is not None and informe.sin_cap == ("QQQ",)
    assert informe.estado_prior is EstadoPrior.PENDIENTE
    assert _persistido(gestor) == antes
    assert gestor.resolver_lista(["NOEXISTE"])[2] is None


def test_neutral_retirar_y_refrescar_operan_sobre_la_sesion_con_las_mismas_reglas(
    gestor: GestorDatos,
) -> None:
    antes = _persistido(gestor)
    base = gestor.incorporar("QQQ", base=gestor.incorporar("AAPL", base=None))
    assert base.estado_prior is EstadoPrior.PENDIENTE

    neutral = gestor.aceptar_prior_neutral(base=base)
    assert neutral.estado_prior is EstadoPrior.NEUTRAL and neutral.prior_neutral_aceptado
    con_cap = gestor.refrescar_cap("QQQ", 22.0, "capitalización del Nasdaq-100", base=neutral)
    assert con_cap.estado_prior is EstadoPrior.CAPITALIZACION  # la aceptación caduca sola
    assert gestor.retirar("QQQ", base=con_cap).activos == ("AAPL",)
    with pytest.raises(GestorError, match="no puede quedar vacío"):
        gestor.retirar("AAPL", base=gestor.incorporar("AAPL", base=None))
    with pytest.raises(GestorError, match="nada que degradar"):
        gestor.aceptar_prior_neutral(base=gestor.incorporar("AAPL", base=None))
    assert _persistido(gestor) == antes


def test_sin_universo_en_la_sesion_los_cambios_son_un_error_de_dominio(
    gestor: GestorDatos,
) -> None:
    for operacion in (
        lambda: gestor.retirar("AAPL", base=None),
        lambda: gestor.refrescar_cap("AAPL", base=None),
        lambda: gestor.aceptar_prior_neutral(base=None),
    ):
        with pytest.raises(GestorError, match="no hay universo configurado en la sesión"):
            operacion()


def test_un_activo_desalineado_con_los_de_la_sesion_se_rechaza(gestor: GestorDatos) -> None:
    base = gestor.incorporar("AAPL", base=None)
    with pytest.raises(GestorError, match="update-prices"):
        gestor.incorporar("VIEJO", base=base)


def test_por_defecto_todo_sigue_operando_sobre_el_guardado(gestor: GestorDatos) -> None:
    """El modo comando, ``make universo`` y los tests de S7-S11 no pasan ``base``."""
    nuevo = gestor.incorporar("AAPL")
    assert nuevo.activos == (*ACTIVOS, "AAPL") and gestor.universo() == nuevo
    assert '"accion": "incorporar"' in gestor.ruta_historial.read_text("utf-8")
