"""Fronteras arquitectónicas (CLAUDE.md): el núcleo puro no conoce ADK ni ningún LLM."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from investmentsys.config import RAIZ_PROYECTO

PAQUETE = RAIZ_PROYECTO / "src" / "investmentsys"
# S8: el Gestor de Datos también es puro; sus FunctionTools viven en tools/gestor.py.
# S10: la gobernanza operativa (fintual/) es Nivel 3: también pura.
MODULOS_PUROS = (
    "quant",
    "portfolio",
    "risk",
    "contracts",
    "data",
    "comparacion",
    "data_manager",
    "fintual",
)
PROHIBIDOS = ("google", "litellm", "openai", "anthropic")
CAPAS_DE_AGENTES = ("investmentsys.tools", "investmentsys.agents", "investmentsys.orchestrator")


def _importados(ruta: Path) -> set[str]:
    nombres: set[str] = set()
    for nodo in ast.walk(ast.parse(ruta.read_text(encoding="utf-8"))):
        if isinstance(nodo, ast.Import):
            nombres.update(alias.name for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            nombres.add(nodo.module)
    return nombres


@pytest.mark.parametrize("modulo", MODULOS_PUROS)
def test_modulo_puro_sin_adk_ni_llm_ni_capas_de_agentes(modulo: str) -> None:
    archivos = sorted((PAQUETE / modulo).rglob("*.py"))
    assert archivos, f"{modulo}: sin archivos que revisar"
    for archivo in archivos:
        for nombre in _importados(archivo):
            assert nombre.split(".")[0] not in PROHIBIDOS, f"{archivo.name} importa {nombre}"
            assert not nombre.startswith(CAPAS_DE_AGENTES), f"{archivo.name} importa {nombre}"


def test_lo_nuevo_de_s8_en_el_nucleo_puro_esta_bajo_vigilancia() -> None:
    """Los módulos puros que añade S8 existen donde ``rglob`` los revisa (no en una capa ADK)."""
    for relativo in (
        "contracts/comite.py",
        "contracts/diagnostico.py",
        "portfolio/cartera_usuario.py",
    ):
        assert (PAQUETE / relativo).is_file(), relativo


def test_lo_nuevo_de_s10_en_el_nucleo_puro_esta_bajo_vigilancia() -> None:
    for relativo in ("contracts/fintual.py", "fintual/no_trade_zones.py", "fintual/montos.py"):
        assert (PAQUETE / relativo).is_file(), relativo


def test_las_personas_no_importan_el_nucleo_puro_solo_tools() -> None:
    """Un LlmAgent nunca produce cifras: a la matemática se llega solo vía ``tools/``."""
    puros = tuple(f"investmentsys.{m}" for m in ("quant", "portfolio", "risk", "fintual"))
    for persona in ("estadistico", "esceptico", "fintual_data"):
        for archivo in sorted((PAQUETE / "agents" / persona).rglob("*.py")):
            for nombre in _importados(archivo):
                assert not nombre.startswith(puros), f"{persona}/{archivo.name} importa {nombre}"
