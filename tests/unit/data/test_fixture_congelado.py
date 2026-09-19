"""Los tests usan precios CONGELADOS, nunca el CSV vivo (S6, ADR-011).

``make update-prices`` reescribe ``data/precios.csv`` cada mes con la serie ajustada completa
(los niveles cambian con cada dividendo). Si el golden o cualquier oráculo leyera ese archivo,
una actualización de datos rompería —o, peor, "arreglaría"— tests sin que cambie el código.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from investmentsys.config import cargar_config
from tests.conftest import CSV_REFERENCIA

SHA256_REFERENCIA = "d19de941920e80eca8689e809b29a409b8332de51aafb0f95259be4c3eb443f5"
TESTS = Path(__file__).resolve().parents[2]
# Únicos archivos que pueden nombrar la ruta viva: comprueban el valor de config, no leen datos.
PERMITIDOS = {"test_config.py", Path(__file__).name}
MARCA = "datos.ruta_csv"


def test_el_fixture_no_ha_cambiado() -> None:
    """Editar el fixture invalida el golden y todos los oráculos: si hace falta, es un ADR."""
    assert hashlib.sha256(CSV_REFERENCIA.read_bytes()).hexdigest() == SHA256_REFERENCIA


def test_ningun_test_llega_al_csv_vivo_por_config() -> None:
    """``config.datos.ruta_csv`` es la única vía del código hacia ``data/precios.csv``."""
    assert cargar_config().datos.ruta_csv.name != CSV_REFERENCIA.name
    culpables = [
        str(archivo.relative_to(TESTS))
        for archivo in sorted(TESTS.rglob("*.py"))
        if archivo.name not in PERMITIDOS and MARCA in archivo.read_text(encoding="utf-8")
    ]
    assert not culpables, f"usa CSV_REFERENCIA de tests/conftest.py en: {culpables}"
