"""ADR-008: reintentos siempre; ubicación del modelo solo en Vertex AI con proyecto (prod)."""

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


def _gemini() -> Gemini:
    modelo = resolver_modelo(AGENTES)
    assert isinstance(modelo, Gemini) and modelo.model == AGENTES.modelo
    return modelo


def test_los_reintentos_salen_de_config() -> None:
    opciones = _gemini().retry_options
    esperado = AGENTES.reintentos_modelo
    assert opciones is not None
    assert opciones.attempts == esperado.intentos > 1
    assert opciones.initial_delay == esperado.espera_inicial_s
    assert opciones.max_delay == esperado.espera_maxima_s
    assert opciones.exp_base == esperado.base_exponencial
    assert opciones.http_status_codes == list(esperado.codigos_http)
    assert {429, 503} <= set(esperado.codigos_http)


def test_las_esperas_caben_en_el_timeout_de_cloud_run() -> None:
    r = AGENTES.reintentos_modelo
    esperas = [
        min(r.espera_inicial_s * r.base_exponencial**i, r.espera_maxima_s)
        for i in range(r.intentos - 1)
    ]
    assert 45 <= sum(esperas) <= 120  # cubre la cuota por minuto sin agotar los 300 s


def test_con_api_key_no_se_fija_ubicacion() -> None:
    assert _gemini().client_kwargs is None


def test_modo_express_sin_proyecto_no_fija_ubicacion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_GENAI_USE_ENTERPRISE", "True")
    assert _gemini().client_kwargs is None


@pytest.mark.parametrize("variable", VARIABLES_VERTEX)
def test_vertex_con_proyecto_pide_el_modelo_en_global(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.setenv(variable, "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "un-proyecto")
    modelo = _gemini()
    assert modelo.client_kwargs == {"location": AGENTES.ubicacion_vertex} == {"location": "global"}
    assert modelo.retry_options is not None


def test_sin_ubicacion_en_config_manda_el_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_GENAI_USE_ENTERPRISE", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "un-proyecto")
    sin_ubicacion = AGENTES.model_copy(update={"ubicacion_vertex": None})
    modelo = resolver_modelo(sin_ubicacion)
    assert isinstance(modelo, Gemini) and modelo.client_kwargs is None


def test_un_modelo_inyectado_tiene_prioridad() -> None:
    assert resolver_modelo(AGENTES, "otro-modelo") == "otro-modelo"
