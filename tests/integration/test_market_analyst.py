"""DoD de S3: los views del LLM validan contra ``MarketViews``; si no, el agente reintenta."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from google import genai
from google.genai import _transformers

from investmentsys.agents.market_analyst import (
    CLAVE_ERROR_VIEWS,
    MarketViewsBorrador,
    ViewsInvalidasError,
    crear_market_analyst,
)
from investmentsys.config import Config
from investmentsys.contracts import MarketViews, TipoView
from investmentsys.data import CSVPriceProvider
from investmentsys.portfolio import optimizar_black_litterman
from investmentsys.tools import CLAVE_FECHA_DECISION, CLAVE_MARKET_VIEWS
from tests.conftest import ACTIVOS, FECHA
from tests.integration.conftest import LlmGuionado, ejecutar


def _view(tipo: str, coeficientes: dict[str, float], q: float, **extra: Any) -> dict[str, Any]:
    return {
        "tipo": tipo,
        "coeficientes": [{"activo": a, "coeficiente": c} for a, c in coeficientes.items()],
        "q_anual": q,
        "confianza": 0.5,
        "justificacion": "Razonamiento de prueba suficientemente largo.",
        "fuente": "conocimiento general del modelo, sin verificar",
        **extra,
    }


BORRADOR_GOLDEN = {
    "resumen": "Crecimiento sólido en large caps, banca canadiense favorable, cripto neutral.",
    "views": [
        _view("absoluta", {"IBIT": 1.0}, 0.03),
        _view("relativa", {"VOOG": 1.0, "VB": -1.0}, 0.03),
        _view("absoluta", {"BNS": 1.0}, 0.10),
    ],
}
RELATIVA_QUE_NO_SUMA_CERO = {
    "resumen": "x",
    "views": [_view("relativa", {"VOOG": 1.0, "VB": -0.5}, 0.03)],
}
FUERA_DEL_UNIVERSO = {"resumen": "x", "views": [_view("absoluta", {"TSLA": 1.0}, 0.2)]}
FUENTE_DEL_FUTURO = {
    "resumen": "x",
    "views": [_view("absoluta", {"BNS": 1.0}, 0.1, fecha_fuente="2026-12-31")],
}


@pytest.mark.parametrize("variante", [{"api_key": "x"}, {"vertexai": True, "project": "p"}])
def test_gemini_acepta_el_esquema_del_borrador_pero_no_el_contrato(
    variante: dict[str, Any],
) -> None:
    """Motivo de ADR-006; si el contrato empieza a convertirse, el borrador puede sobrar."""
    cliente = (
        genai.Client(location="us-central1", **variante)
        if "vertexai" in variante
        else (genai.Client(**variante))
    )
    esquema = _transformers.t_schema(cliente._api_client, MarketViewsBorrador)
    # La API real devuelve 400 ante `additional_properties` aunque el conversor lo acepte.
    assert "additional_properties" not in esquema.model_dump_json(exclude_none=True)
    with pytest.raises(ValueError, match=r"exclusiveMinimum|patternProperties"):
        _transformers.t_schema(cliente._api_client, MarketViews)


def test_salida_valida_a_la_primera(config: Config, provider: CSVPriceProvider) -> None:
    llm = LlmGuionado(BORRADOR_GOLDEN)
    corrida = ejecutar(crear_market_analyst(config, provider, llm))

    views = MarketViews.model_validate(corrida.estado[CLAVE_MARKET_VIEWS])
    assert views.fecha_decision == FECHA  # la pone el código (último cierre), no el LLM
    assert views.activos == ACTIVOS
    assert views.horizonte_meses == config.agentes.horizonte_views_meses
    assert [v.tipo for v in views.views] == [
        TipoView.ABSOLUTA,
        TipoView.RELATIVA,
        TipoView.ABSOLUTA,
    ]
    assert views.matriz_p()[1] == [1.0, 0.0, 0.0, -1.0]
    assert corrida.estado[CLAVE_ERROR_VIEWS] is None
    assert len(llm.peticiones) == 1
    assert "intento 1" in corrida.textos("market_analyst")[-1]


def test_peticion_al_modelo(config: Config, provider: CSVPriceProvider) -> None:
    llm = LlmGuionado(BORRADOR_GOLDEN)
    ejecutar(crear_market_analyst(config, provider, llm))
    peticion = llm.peticiones[0].config
    assert peticion.response_schema is MarketViewsBorrador
    assert peticion.response_mime_type == "application/json"
    assert peticion.temperature == config.agentes.temperatura
    assert peticion.seed == config.reproducibilidad.semilla
    assert not peticion.tools
    for esperado in (*ACTIVOS, FECHA.isoformat(), "no inventes URLs"):
        assert esperado in llm.instruccion(0)
    assert "NO validó" not in llm.instruccion(0)


@pytest.mark.parametrize(
    ("invalida", "pista"),
    [
        ("esto no es JSON", "json"),
        ({"resumen": "x", "views": [{"tipo": "absoluta"}]}, "q_anual"),
        (RELATIVA_QUE_NO_SUMA_CERO, "sumar cero"),
        (FUERA_DEL_UNIVERSO, "TSLA"),
        (FUENTE_DEL_FUTURO, "look-ahead"),
    ],
    ids=["no_json", "esquema", "relativa_no_suma_cero", "fuera_del_universo", "fuente_futura"],
)
def test_salida_invalida_reintenta_con_el_error_en_la_instruccion(
    config: Config, provider: CSVPriceProvider, invalida: str | dict[str, Any], pista: str
) -> None:
    llm = LlmGuionado(invalida, BORRADOR_GOLDEN)
    corrida = ejecutar(crear_market_analyst(config, provider, llm))

    assert len(llm.peticiones) == 2
    assert "NO validó" in llm.instruccion(1)
    assert pista.lower() in llm.instruccion(1).lower()
    avisos = corrida.textos("market_analyst")
    assert any("Intento 1/" in t and "no valida" in t for t in avisos)
    views = MarketViews.model_validate(corrida.estado[CLAVE_MARKET_VIEWS])
    assert len(views.views) == 3
    assert corrida.estado[CLAVE_ERROR_VIEWS] is None


def test_agotados_los_intentos_falla_sin_escribir_views(
    config: Config, provider: CSVPriceProvider
) -> None:
    intentos = config.agentes.max_intentos_analista
    llm = LlmGuionado(*[FUERA_DEL_UNIVERSO] * intentos)
    with pytest.raises(ViewsInvalidasError, match="TSLA"):
        ejecutar(crear_market_analyst(config, provider, llm))
    assert len(llm.peticiones) == intentos


def test_un_fallo_del_modelo_no_se_confunde_con_una_salida_invalida(
    config: Config, provider: CSVPriceProvider
) -> None:
    """google-genai lanza ``ValueError`` sin API key: debe propagarse al primer intento."""
    llm = LlmGuionado(ValueError("No API key was provided."), BORRADOR_GOLDEN)
    with pytest.raises(ValueError, match="No API key") as info:
        ejecutar(crear_market_analyst(config, provider, llm))
    assert not isinstance(info.value, ViewsInvalidasError)
    assert len(llm.peticiones) == 1


def test_respeta_la_fecha_de_decision_de_la_corrida(
    config: Config, provider: CSVPriceProvider
) -> None:
    fecha = date(2025, 6, 30)
    llm = LlmGuionado(BORRADOR_GOLDEN)
    corrida = ejecutar(
        crear_market_analyst(config, provider, llm), estado={CLAVE_FECHA_DECISION: "2025-06-30"}
    )
    assert MarketViews.model_validate(corrida.estado[CLAVE_MARKET_VIEWS]).fecha_decision == fecha
    assert "2025-06-30" in llm.instruccion(0)


def test_sin_views_es_valido(config: Config, provider: CSVPriceProvider) -> None:
    llm = LlmGuionado({"resumen": "Sin convicción este mes.", "views": []})
    corrida = ejecutar(crear_market_analyst(config, provider, llm))
    assert MarketViews.model_validate(corrida.estado[CLAVE_MARKET_VIEWS]).views == ()


def test_las_views_del_agente_alimentan_black_litterman(
    config: Config, provider: CSVPriceProvider, views_golden: MarketViews
) -> None:
    """El contrato que deja el agente es intercambiable con las views fijas del golden."""
    from investmentsys.contracts import PortfolioConstraints
    from investmentsys.quant import estimar

    corrida = ejecutar(crear_market_analyst(config, provider, LlmGuionado(BORRADOR_GOLDEN)))
    views = MarketViews.model_validate(corrida.estado[CLAVE_MARKET_VIEWS])
    estimaciones = estimar(
        provider.retornos_log(ACTIVOS, hasta=FECHA),
        fecha_decision=FECHA,
        periodos_por_anio=provider.periodos_por_anio,
        ventana_meses=config.datos.ventana_covarianza_meses,
        metodos=(config.optimizacion.metodo_covarianza,),
        nivel_confianza=config.estimacion.nivel_confianza,
    )
    restricciones = PortfolioConstraints(
        activos=ACTIVOS,
        peso_min=config.optimizacion.peso_min,
        peso_max=config.optimizacion.peso_max,
    )
    args = (restricciones, config.optimizacion, config.prior_equilibrio)
    del_agente = optimizar_black_litterman(estimaciones, views, *args)
    del_golden = optimizar_black_litterman(estimaciones, views_golden, *args)
    assert del_agente.pesos == del_golden.pesos
