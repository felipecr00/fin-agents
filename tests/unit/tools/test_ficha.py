"""Ficha de origen (S9): la redacta el código desde la salida de la herramienta."""

from __future__ import annotations

from typing import Any

import pytest
from google.adk.tools import ToolContext

from investmentsys.tools import NucleoTools
from investmentsys.tools.ficha import (
    ATIENDE,
    CIFRAS_CLAVE,
    ETIQUETA_FICHA_COMITE,
    ETIQUETA_FICHA_COMITE_SIN_APROBAR,
    ETIQUETA_FICHA_EXPLORATORIA,
    PREFIJO_NO_VALIDADO,
    construir_ficha,
)
from tests.almacen import diagnosticar

VERSION = "c" * 64
PESOS_USUARIO = {"VOOG": 0.5, "BNS": 0.3, "VB": 0.2}


def _comite(validado: bool) -> dict[str, Any]:
    return {
        "status": "success",
        "validado": validado,
        "universe_version": VERSION,
        "run_id": "20261005T120000",
        "iteraciones": 2,
        "acta": "runs/20261005T120000",
        "recomendacion": {"candidato": "black_litterman", "pesos": {"VOOG": 0.7, "VB": 0.3}}
        if validado
        else None,
        "metricas_oos": {
            "sharpe_oos": 0.5449,
            "retorno_anualizado": 0.1012,
            "volatilidad_anualizada": 0.1857,
            "max_drawdown": 0.29,
        },
    }


def test_diagnostico_del_esceptico_fuente_herramienta_sello_etiqueta_y_prefijo(
    tools: NucleoTools, ctx: ToolContext
) -> None:
    salida = diagnosticar(tools, PESOS_USUARIO, ctx)
    ficha = construir_ficha("diagnosticar_cartera", salida)
    assert ficha is not None
    cabecera, fuente, *cifras = ficha.splitlines()
    assert cabecera == f"**Ficha de origen — {ETIQUETA_FICHA_EXPLORATORIA}**"
    assert fuente == (
        "- Fuente: **Escéptico** · herramienta `diagnosticar_cartera` · universo "
        f"`{salida['universe_version'][:12]}`"
    )
    assert cifras and all(c.startswith(f"- {PREFIJO_NO_VALIDADO}") for c in cifras)
    m = salida["metricas_oos"]
    assert f"Sharpe {m['sharpe_oos']:.2f}" in ficha
    assert f"caída máxima {m['max_drawdown'] * 100:.2f} %" in ficha
    assert "aprobad" not in ficha.lower() and "rechazad" not in ficha.lower()


def test_sin_sello_propio_usa_el_vigente_de_la_sesion() -> None:
    views = {"status": "success", "validado": False, "market_views": {"views": []}}
    ficha = construir_ficha("market_analyst", views, VERSION)
    assert ficha is not None and f"universo `{VERSION[:12]}`" in ficha
    assert "**Analista de Mercado**" in ficha and f"{PREFIJO_NO_VALIDADO}sin views" in ficha


def test_solo_una_corrida_aprobada_por_el_comite_va_sin_prefijo() -> None:
    aprobada = construir_ficha("convocar_comite", _comite(True))
    sin_aprobar = construir_ficha("convocar_comite", _comite(False))
    assert aprobada is not None and sin_aprobar is not None
    assert ETIQUETA_FICHA_COMITE in aprobada and PREFIJO_NO_VALIDADO not in aprobada
    assert "cartera black_litterman: VOOG 70.0 % / VB 30.0 %" in aprobada
    assert ETIQUETA_FICHA_COMITE_SIN_APROBAR in sin_aprobar
    assert sin_aprobar.count(PREFIJO_NO_VALIDADO) == len(sin_aprobar.splitlines()) - 2


@pytest.mark.parametrize(
    "salida",
    [
        {"status": "error", "validado": False},
        {"status": "rechazado", "motivo": "x"},
        {"status": "success", "universo": {}},  # sin `validado`: no es un resultado que fichar
        {"status": "pendiente_de_confirmacion", "token": "t"},
    ],
)
def test_sin_resultado_no_hay_ficha(salida: dict[str, Any]) -> None:
    assert construir_ficha("estimar_mercado", salida) is None


def test_toda_herramienta_con_cifras_clave_tiene_silla() -> None:
    assert set(CIFRAS_CLAVE) <= set(ATIENDE)
