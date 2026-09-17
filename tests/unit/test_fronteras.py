"""Fronteras arquitectónicas (CLAUDE.md): el núcleo puro no conoce ADK ni ningún LLM."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from investmentsys.config import RAIZ_PROYECTO

PAQUETE = RAIZ_PROYECTO / "src" / "investmentsys"
MODULOS_PUROS = ("quant", "portfolio", "risk", "contracts", "data")
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
