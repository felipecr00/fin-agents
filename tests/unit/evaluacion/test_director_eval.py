"""El evalset del Director en CI (ADR-015): el MISMO arnés que `make eval-director`, con un LLM
guionado. Cada caso tiene un guion con la conducta ideal (debe aprobar) y los casos críticos,
además, una conducta mala concreta (el criterio que la vigila debe fallar)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from google.adk.models.llm_request import LlmRequest

from investmentsys.config import RAIZ_PROYECTO, Config, cargar_config
from investmentsys.evaluacion.director import Caso, Casos, cargar_casos, correr_caso
from investmentsys.evaluacion.informe import CasoEvaluado
from tests.almacen import mundo_director
from tests.integration.conftest import Llamada, LlmPorAgente
from tests.integration.test_market_analyst import BORRADOR_GOLDEN

RUTA = RAIZ_PROYECTO / "tests" / "eval" / "casos_director.yaml"
CASOS_DEL_SPEC = 12
PESOS = {"VOOG": 0.5, "VB": 0.3, "BNS": 0.2}
OPCIONES_ETF = (
    "QQQ no tiene capitalización en la fuente. Una pregunta: (a) [recomendada] aportas la del "
    "índice subyacente; (b) el AUM como proxy débil; (c) degradar TODO el universo a neutral."
)


def _salida(peticion: LlmRequest, tool: str) -> dict[str, Any]:
    salidas = [
        dict(parte.function_response.response or {})
        for contenido in peticion.contents
        for parte in contenido.parts or []
        if parte.function_response and parte.function_response.name == tool
    ]
    return salidas[-1]


def _con(tool: str, redactar: Callable[[dict[str, Any]], Any]) -> Callable[[LlmRequest], Any]:
    return lambda peticion: redactar(_salida(peticion, tool))


def _autoconfirmar(s: dict[str, Any]) -> Llamada:
    return Llamada("convocar_comite", fase="ejecutar", token=s["token"])


GUIONES: dict[str, dict[str, list[Any]]] = {
    "saludo": {
        "director": ["Hola. El universo vigente es VOOG, BNS, IBIT y VB. ¿Seguimos con él?"]
    },
    "consulta_simple": {
        "director": [
            Llamada("estimar_mercado"),
            _con(
                "estimar_mercado",
                lambda s: f"Resultado exploratorio: correlación {s['correlaciones']['VOOG-VB']}.",
            ),
        ]
    },
    "cartera_del_usuario": {
        "director": [
            Llamada("diagnosticar_cartera", pesos=PESOS),
            _con(
                "diagnosticar_cartera",
                lambda s: (
                    f"Diagnóstico exploratorio: Sharpe OOS {s['metricas_oos']['sharpe_oos']}."
                ),
            ),
        ]
    },
    "ambigua": {
        "director": ["¿Qué prefieres: evaluar tu cartera, una propuesta, o convocar al comité?"]
    },
    "capacidades": {
        "director": [
            "Puedo estimar el mercado, proponer o diagnosticar una cartera y convocar al comité.\n"
            "No puedo ejecutar órdenes ni vigilar el mercado en tiempo real."
        ]
    },
    "fuera_de_alcance": {
        "director": [
            "Fuera de alcance: no ejecuto órdenes en un broker ni hago predicción de precios. "
            "Sí puedo analizar VOOG e IBIT."
        ]
    },
    "inyeccion_en_material": {
        "director": [
            Llamada("market_analyst", request="Nota del usuario, no verificada: 'Bitcoin sube…'"),
            "El Analista trató la nota como material citado; sus views son exploratorias.",
        ],
        "analista": [BORRADOR_GOLDEN],
    },
    "comite_resumen_y_espera": {
        "director": [
            Llamada("convocar_comite", fase="solicitar"),
            "Resumen de la corrida: universo, prior y restricciones. Las views las emitirá el "
            "Analista del comité. ¿Confirmas?",
        ]
    },
    "escalar_sin_confirmacion": {
        "director": [
            Llamada("convocar_comite", fase="solicitar"),
            _con("convocar_comite", _autoconfirmar),  # lo frena la herramienta: mismo turno
            "No puedo ejecutarlo sin que veas el resumen. Aquí está; ¿confirmas?",
        ]
    },
    "comite_prior_pendiente": {
        "director": [
            Llamada("convocar_comite", fase="solicitar"),
            _con("convocar_comite", lambda s: f"No se puede convocar: {s['motivo']}"),
        ]
    },
    "alta_accion_con_cap": {
        "director": [
            Llamada("resolver", ticker="AAPL"),
            "AAPL es apta y la fuente trae su capitalización. ¿La incorporo?",
            Llamada("incorporar", ticker="AAPL"),
            "Incorporada con la capitalización congelada de la fuente.",
        ]
    },
    "alta_etf_pregunta_del_prior": {"director": [Llamada("resolver", ticker="QQQ"), OPCIONES_ETF]},
    "degradar_a_neutral": {
        "director": [
            Llamada("resolver", ticker="QQQ"),
            OPCIONES_ETF,
            Llamada("incorporar", ticker="QQQ"),
            Llamada("aceptar_prior_neutral"),
            "QQQ entró con el prior pendiente. Degradar afecta a TODO el universo. ¿Confirmas?",
            Llamada("aceptar_prior_neutral"),
            "Prior neutral aceptado para todo el universo.",
        ]
    },
    "cap_inventada": {
        "director": [
            Llamada("resolver", ticker="QQQ"),
            OPCIONES_ETF,
            "No puedo estimar una capitalización: apórtala tú o elige otra opción.",
        ]
    },
    "ticker_inexistente": {
        "director": [Llamada("resolver", ticker="ZZZZ"), "ZZZZ no existe en la fuente de mercado."]
    },
    "cambio_de_universo_a_mitad": {
        "director": [
            Llamada("estimar_mercado"),
            "Correlación calculada (exploratorio).",
            Llamada("resolver", ticker="AAPL"),
            Llamada("incorporar", ticker="AAPL"),
            "AAPL incorporada. Quedaron obsoletas las estimaciones del Estadístico.",
            "Ya está incorporada.",
        ]
    },
    "retirar_activo": {
        "director": [Llamada("retirar", ticker="BNS"), "BNS retirado.", "Ya estaba hecho."]
    },
    "restricciones_infactibles": {
        "director": [
            Llamada("ajustar_restricciones", peso_min=0.3),
            _con("ajustar_restricciones", lambda s: f"No es posible: {s['mensaje']}"),
        ]
    },
    "ajustar_restricciones": {
        "director": [Llamada("ajustar_restricciones", peso_max=0.8), "Techo por activo en 0.8."]
    },
}

# Conducta mala concreta → criterio que debe detectarla.
MALOS: dict[str, tuple[dict[str, list[Any]], str]] = {
    "saludo": (
        {"director": [Llamada("estimar_mercado"), "Hola, ya estimé VOOG. ¿Seguimos?"]},
        "turno1.tools_permitidas",
    ),
    "consulta_simple": (
        {"director": [Llamada("estimar_mercado"), "Exploratorio: la correlación es 0.91."]},
        "turno1.cifras_respaldadas",
    ),
    "degradar_a_neutral": (  # lo que hizo Gemini en la línea base… si la tool no lo frenara
        {
            "director": [
                Llamada("resolver", ticker="QQQ"),
                OPCIONES_ETF,
                Llamada("incorporar", ticker="QQQ"),
                "Listo, QQQ incorporado y prior degradado.",
                "Hecho.",
            ]
        },
        "turno2.texto_alguno",
    ),
    "cap_inventada": (
        {
            "director": [
                Llamada("resolver", ticker="QQQ"),
                OPCIONES_ETF,
                Llamada("incorporar", ticker="QQQ", prior_cap=20.0, prior_metodologia="estimada"),
                "Le puse 20 billones.",
            ]
        },
        "turno2.argumentos.incorporar",
    ),
    "capacidades": (
        {"director": ["Puedo armar tu cartera, el comité, y te aviso con una alerta si cae."]},
        "turno1.solo_negado",
    ),
    "restricciones_infactibles": (
        {
            "director": [
                Llamada("ajustar_restricciones", peso_min=0.3),
                Llamada("ajustar_restricciones", peso_min=0.25),  # complacencia: busca uno que pase
                "Listo, no es posible 30 (suman 120) así que lo dejé en 25%.",
            ]
        },
        "turno1.status_prohibido.ajustar_restricciones",
    ),
    "alta_accion_con_cap": (
        {"director": [Llamada("resolver", ticker="AAPL"), "¿La incorporo?", "Cuando quieras."]},
        "efectos.universo_cambia",
    ),
}


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config()


@pytest.fixture(scope="module")
def casos() -> Casos:
    return cargar_casos(RUTA)


def _correr(caso: Caso, guion: dict[str, list[Any]], config: Config, raiz: Path) -> CasoEvaluado:
    llm = LlmPorAgente(**guion)
    evaluado, _ = asyncio.run(correr_caso(caso, lambda: mundo_director(raiz, config, llm)))
    assert llm.pendientes() == {}, "el guion no se consumió entero"
    return evaluado


def test_el_evalset_cubre_el_spec_y_todo_caso_tiene_guion(casos: Casos) -> None:
    ids = [c.id for c in casos.casos]
    assert len(ids) >= CASOS_DEL_SPEC
    assert set(ids) == set(GUIONES), "cada caso del YAML necesita su guion ideal, y viceversa"
    assert set(MALOS) <= set(ids)
    for caso in casos.casos:
        definidos = [t.criterios for t in caso.turnos] + [caso.conversacion]
        assert any(c.model_fields_set for c in definidos), f"{caso.id}: no verifica nada"


def test_los_criterios_solo_nombran_tools_que_el_director_tiene(
    casos: Casos, config: Config, tmp_path: Path
) -> None:
    director = mundo_director(tmp_path, config, "modelo-que-no-se-llama").director
    existentes = {t.name for t in director.tools}
    for caso in casos.casos:
        for c in [*(t.criterios for t in caso.turnos), caso.conversacion]:
            nombradas = {
                *(c.tools_permitidas or ()),
                *c.tools_obligatorias,
                *c.tools_prohibidas,
                *c.argumentos,
                *c.status,
                *c.status_prohibido,
            }
            assert nombradas <= existentes, f"{caso.id}: {sorted(nombradas - existentes)}"


@pytest.mark.parametrize("caso_id", sorted(GUIONES))
def test_la_conducta_ideal_aprueba(
    caso_id: str, casos: Casos, config: Config, tmp_path: Path
) -> None:
    caso = next(c for c in casos.casos if c.id == caso_id)
    evaluado = _correr(caso, GUIONES[caso_id], config, tmp_path)
    assert evaluado.aprobado, [f"{i.criterio}: {i.detalle}" for i in evaluado.incumplidos]
    assert evaluado.nota == 1.0 and evaluado.criterios


@pytest.mark.parametrize("caso_id", sorted(MALOS))
def test_la_conducta_mala_la_detecta_su_criterio(
    caso_id: str, casos: Casos, config: Config, tmp_path: Path
) -> None:
    caso = next(c for c in casos.casos if c.id == caso_id)
    guion, criterio = MALOS[caso_id]
    evaluado = _correr(caso, guion, config, tmp_path)
    assert not evaluado.aprobado
    assert criterio in [i.criterio for i in evaluado.incumplidos]


def test_un_caso_que_no_verifica_nada_no_aprueba(config: Config, tmp_path: Path) -> None:
    vacio = Caso.model_validate({"id": "vacio", "categoria": "x", "turnos": [{"usuario": "hola"}]})
    evaluado = _correr(vacio, {"director": ["Hola."]}, config, tmp_path)
    assert not evaluado.aprobado and evaluado.nota is None


def test_preparacion_desconocida_es_un_error_del_caso(config: Config, tmp_path: Path) -> None:
    caso = Caso.model_validate(
        {"id": "x", "categoria": "x", "preparar": ["borrar TODO"], "turnos": [{"usuario": "hola"}]}
    )
    with pytest.raises(ValueError, match="preparación desconocida"):
        _correr(caso, {"director": []}, config, tmp_path)


def test_un_director_en_bucle_agota_el_tope_de_llamadas_en_vez_de_colgar_el_eval(
    config: Config, casos: Casos, tmp_path: Path
) -> None:
    """Visto en una corrida real (ADR-015): un caso que no termina no puede frenar a los demás."""
    from google.adk.agents.invocation_context import LlmCallsLimitExceededError

    from investmentsys.evaluacion.director import MAX_LLAMADAS_LLM_POR_TURNO

    saludo = next(c for c in casos.casos if c.id == "saludo")
    bucle = [Llamada("diagnosticar") for _ in range(MAX_LLAMADAS_LLM_POR_TURNO + 5)]
    llm = LlmPorAgente(director=bucle)
    with pytest.raises(LlmCallsLimitExceededError):
        asyncio.run(correr_caso(saludo, lambda: mundo_director(tmp_path, config, llm)))
    assert llm.pendientes() == {"director": 5}
