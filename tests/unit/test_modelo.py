"""ADR-008: reintentos siempre; ubicación del modelo solo en Vertex AI con proyecto (prod)."""

from __future__ import annotations

from typing import Any

import pytest
from google.adk.models.base_llm import BaseLlm
from pydantic import ValidationError

from investmentsys.agents.modelo import VARIABLES_VERTEX, clase_cliente, resolver_modelo
from investmentsys.config import InferenciaConfig, cargar_config

CONFIG = cargar_config()
AGENTES = CONFIG.agentes
NIVEL_1 = CONFIG.inferencia.nivel_1
AGENTE = "director"


@pytest.fixture(autouse=True)
def _entorno_limpio(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (*VARIABLES_VERTEX, "GOOGLE_CLOUD_PROJECT"):
        monkeypatch.delenv(variable, raising=False)


def _cliente() -> Any:
    """El cliente real del Nivel 1: la clase y el id salen de ``config.yaml: inferencia``."""
    modelo = resolver_modelo(CONFIG, AGENTE)
    assert isinstance(modelo, clase_cliente(NIVEL_1)) and modelo.model == NIVEL_1.modelo
    return modelo


def test_los_reintentos_salen_de_config() -> None:
    opciones = _cliente().retry_options
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
    assert _cliente().client_kwargs is None


def test_modo_express_sin_proyecto_no_fija_ubicacion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_GENAI_USE_ENTERPRISE", "True")
    assert _cliente().client_kwargs is None


@pytest.mark.parametrize("variable", VARIABLES_VERTEX)
def test_vertex_con_proyecto_pide_el_modelo_en_global(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.setenv(variable, "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "un-proyecto")
    modelo = _cliente()
    assert modelo.client_kwargs == {"location": AGENTES.ubicacion_vertex} == {"location": "global"}
    assert modelo.retry_options is not None


def test_sin_ubicacion_en_config_manda_el_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_GENAI_USE_ENTERPRISE", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "un-proyecto")
    agentes = AGENTES.model_copy(update={"ubicacion_vertex": None})
    modelo: Any = resolver_modelo(CONFIG.model_copy(update={"agentes": agentes}), AGENTE)
    assert isinstance(modelo, BaseLlm) and modelo.client_kwargs is None


def test_un_modelo_inyectado_tiene_prioridad() -> None:
    assert resolver_modelo(CONFIG, AGENTE, "otro-modelo") == "otro-modelo"


# ------------------------------------------------------- niveles de inferencia (ADR-018)
def test_todo_agente_con_llm_tiene_un_nivel_asignado_y_utilizable() -> None:
    for agente in ("director", "market_analyst", "constructor", "reporter"):
        assert CONFIG.inferencia.de(agente) is NIVEL_1
    assert CONFIG.inferencia.nivel_3 == "determinista"


def _inferencia(**cambios: Any) -> InferenciaConfig:
    return InferenciaConfig.model_validate(CONFIG.inferencia.model_dump() | cambios)


def test_un_agente_sin_asignar_o_asignado_a_un_nivel_sin_llm_falla_claro() -> None:
    with pytest.raises(ValueError, match="falta el agente 'estratega'"):
        CONFIG.inferencia.de("estratega")
    for nivel in ("nivel_2", "nivel_3"):  # nivel_2 sin asignar; nivel_3 nunca es un LLM
        with pytest.raises(ValueError, match="no tiene un LLM asignado"):
            _inferencia(asignaciones={"director": nivel}).de("director")
    with pytest.raises(ValidationError):
        _inferencia(asignaciones={"director": "nivel_4"})


def test_el_cliente_declarado_debe_ser_un_llm_de_adk() -> None:
    assert issubclass(clase_cliente(NIVEL_1), BaseLlm)
    with pytest.raises(TypeError, match="no es un BaseLlm"):
        clase_cliente(NIVEL_1.model_copy(update={"cliente": "pathlib:Path"}))
    with pytest.raises(ValidationError):
        NIVEL_1.model_validate(NIVEL_1.model_dump() | {"cliente": "sin_dos_puntos"})
