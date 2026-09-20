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
from investmentsys.tools.fintual import OPERACIONES
from tests.almacen import sembrar_gestor, universo_referencia

# Ruteo jerárquico (S10, ADR-020): 8 entradas en vez de las 13 planas de S8-S9.
TOOLS_DEL_BRIEF = {
    "consultar_mesa_trabajo",  # S9: la pizarra y el roster
    "gestionar_datos_y_fricciones",  # el Gestor-Fintual: transaccional, sin persona
    "construir_candidatos",
    "ajustar_restricciones",
    "convocar_comite",
    # Las personas: sub-agentes expuestos como herramienta (mode="single_turn").
    "market_analyst",
    "estadistico",
    "esceptico",
}
# La herramienta de cada persona es SUYA: el Director ya no la ve.
TOOLS_DE_LAS_PERSONAS = {"estadistico": ["estimar_mercado"], "esceptico": ["diagnosticar_cartera"]}


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
    for operacion in OPERACIONES:  # el cableado explica cada operación del Gestor
        assert f'"{operacion}"' in cableado, operacion


def test_las_personas_son_thin_una_herramienta_y_sin_transferencias(director: LlmAgent) -> None:
    personas = {a.name: a for a in director.sub_agents if a.name in TOOLS_DE_LAS_PERSONAS}
    assert set(personas) == set(TOOLS_DE_LAS_PERSONAS)
    for nombre, persona in personas.items():
        assert isinstance(persona, LlmAgent) and persona.mode == "single_turn"
        assert [t.name for t in persona.tools] == TOOLS_DE_LAS_PERSONAS[nombre]  # type: ignore[union-attr]
        assert persona.disallow_transfer_to_parent and persona.disallow_transfer_to_peers
        assert persona.input_schema is not None and "pregunta" in persona.input_schema.model_fields
        assert not set(TOOLS_DE_LAS_PERSONAS[nombre]) & {t.name for t in director.tools}  # type: ignore[union-attr]


def test_la_temperatura_de_las_personas_sale_de_config(director: LlmAgent, config: Config) -> None:
    for persona in director.sub_agents:
        if isinstance(persona, LlmAgent):
            assert persona.generate_content_config is not None
            assert (
                persona.generate_content_config.temperature == config.agentes.temperatura_personas
            )


def test_la_instruccion_refleja_el_universo_de_la_sesion(director: LlmAgent) -> None:
    sin_universo = _instruccion(director, {})
    assert "no hay universo cargado" in sin_universo
    universo = universo_referencia()
    con_universo = _instruccion(director, {CLAVE_UNIVERSO: universo.model_dump(mode="json")})
    assert f"`{universo.version[:12]}` con VOOG, BNS, IBIT, VB" in con_universo


def test_no_hay_llaves_de_plantilla_sin_resolver(director: LlmAgent) -> None:
    texto = _instruccion(director, {})
    assert "{" not in texto and "}" not in texto
