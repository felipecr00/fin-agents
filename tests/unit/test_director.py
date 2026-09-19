"""``crear_director``: la instrucción es el spec aprobado, literal, más el cableado de tools."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from google.adk.agents import LlmAgent

from investmentsys.agents.director import INSTRUCCION, MARCADORES, crear_director
from investmentsys.config import Config, cargar_config
from investmentsys.contracts import DISCLAIMER
from investmentsys.tools import CLAVE_UNIVERSO
from tests.almacen import sembrar_gestor, universo_referencia

TOOLS_DEL_BRIEF = {
    "resolver",
    "incorporar",
    "retirar",
    "aceptar_prior_neutral",
    "refrescar_cap",
    "diagnosticar",
    "estimar_mercado",
    "construir_candidatos",
    "ajustar_restricciones",
    "diagnosticar_cartera",
    "convocar_comite",
    "market_analyst",  # el sub-agente, expuesto como herramienta (mode="single_turn")
}


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config()


@pytest.fixture
def director(config: Config, tmp_path: Path) -> LlmAgent:
    gestor = sembrar_gestor(tmp_path, config)
    return crear_director(config, gestor.provider(), gestor, "modelo-que-no-se-llama", tmp_path)


def _instruccion(director: LlmAgent, estado: dict[str, object]) -> str:
    assert callable(director.instruction)
    texto = director.instruction(SimpleNamespace(state=estado))  # type: ignore[arg-type]
    assert isinstance(texto, str)
    return texto


def test_la_instruccion_contiene_los_marcadores_estructurales_del_spec(director: LlmAgent) -> None:
    """Los cuatro modos A-D y la regla de la decisión final del usuario."""
    texto = _instruccion(director, {})
    assert len(MARCADORES) == 5
    for marcador in MARCADORES:
        assert marcador in texto, marcador


def test_la_base_es_el_spec_literal_y_el_codigo_solo_agrega_el_cableado(
    director: LlmAgent,
) -> None:
    texto = _instruccion(director, {})
    assert texto.startswith(INSTRUCCION)
    cableado = texto.removeprefix(INSTRUCCION)
    assert cableado.lstrip().startswith("Cableado de herramientas")
    for marcador in MARCADORES:  # los modos y las reglas no se parafrasean en el cableado
        assert marcador not in cableado
    assert DISCLAIMER in cableado


def test_el_cableado_nombra_solo_herramientas_que_existen(director: LlmAgent) -> None:
    nombres = {t.name for t in director.tools}  # type: ignore[union-attr]
    assert nombres == TOOLS_DEL_BRIEF
    cableado = _instruccion(director, {}).removeprefix(INSTRUCCION)
    for nombre in TOOLS_DEL_BRIEF:
        assert f"`{nombre}" in cableado, nombre
    assert "validar_candidato" not in nombres  # el veredicto es solo del comité


def test_la_instruccion_refleja_el_universo_de_la_sesion(director: LlmAgent) -> None:
    sin_universo = _instruccion(director, {})
    assert "no hay universo cargado" in sin_universo
    universo = universo_referencia()
    con_universo = _instruccion(director, {CLAVE_UNIVERSO: universo.model_dump(mode="json")})
    assert f"`{universo.version[:12]}` con VOOG, BNS, IBIT, VB" in con_universo


def test_no_hay_llaves_de_plantilla_sin_resolver(director: LlmAgent) -> None:
    texto = _instruccion(director, {})
    assert "{" not in texto and "}" not in texto
