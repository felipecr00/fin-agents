"""ADR-008: la ubicación del modelo solo se fija en Vertex AI con proyecto (prod)."""

from __future__ import annotations

import pytest
from google.adk.models.google_llm import Gemini

from investmentsys.agents.modelo import VARIABLES_VERTEX, resolver_modelo
from investmentsys.config import cargar_config

AGENTES = cargar_config().agentes


@pytest.fixture(autouse=True)
def _entorno_limpio(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (*VARIABLES_VERTEX, "GOOGLE_CLOUD_PROJECT"):
        monkeypatch.delenv(variable, raising=False)


def test_con_api_key_se_usa_el_id_de_config() -> None:
    assert resolver_modelo(AGENTES) == AGENTES.modelo


def test_modo_express_sin_proyecto_no_fija_ubicacion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_GENAI_USE_ENTERPRISE", "True")
    assert resolver_modelo(AGENTES) == AGENTES.modelo


@pytest.mark.parametrize("variable", VARIABLES_VERTEX)
def test_vertex_con_proyecto_pide_el_modelo_en_global(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.setenv(variable, "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "un-proyecto")
    modelo = resolver_modelo(AGENTES)
    assert isinstance(modelo, Gemini) and modelo.model == AGENTES.modelo
    assert modelo.client_kwargs == {"location": AGENTES.ubicacion_vertex} == {"location": "global"}


def test_sin_ubicacion_en_config_manda_el_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_GENAI_USE_ENTERPRISE", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "un-proyecto")
    sin_ubicacion = AGENTES.model_copy(update={"ubicacion_vertex": None})
    assert resolver_modelo(sin_ubicacion) == AGENTES.modelo


def test_un_modelo_inyectado_tiene_prioridad(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_GENAI_USE_ENTERPRISE", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "un-proyecto")
    assert resolver_modelo(AGENTES, "otro-modelo") == "otro-modelo"
