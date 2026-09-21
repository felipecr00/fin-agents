"""Lienzo en blanco (ADR-023): la sesión de ``apps/equipo`` arranca SIN universo.

LLM falso sobre el ``Runner`` real. El guion se porta MAL a propósito donde importa (pide
análisis y comité con la mesa limpia): lo que se prueba es que la custodia está en el código.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from investmentsys.agents.anexos import MARCA_ANEXO
from investmentsys.agents.director import INSTRUCCION, crear_director
from investmentsys.agents.director.agente import MESA_LIMPIA
from investmentsys.config import RAIZ_PROYECTO, Config
from investmentsys.data_manager import GestorDatos
from investmentsys.tools import CLAVE_UNIVERSO
from investmentsys.tools.estado import CLAVE_ORIGEN_UNIVERSO, ORIGEN_GUARDADO, ORIGEN_SESION
from investmentsys.tools.mesa import TITULO_MESA_LIMPIA
from tests.almacen import fuente_de_eval, sembrar_gestor
from tests.conftest import ACTIVOS
from tests.integration.conftest import Corrida, Llamada, LlmPorAgente, conversar, gestor_op

SIN_UNIVERSO = "no hay universo configurado en la sesión"


@pytest.fixture
def gestor(tmp_path: Path, config: Config) -> GestorDatos:
    return sembrar_gestor(tmp_path / "almacen", config, fuente_de_eval())


def _charlar(
    config: Config,
    gestor: GestorDatos,
    tmp_path: Path,
    guion: list[Any],
    mensajes: list[str],
    **otros: list[Any],
) -> tuple[list[Corrida], LlmPorAgente]:
    llm = LlmPorAgente(director=guion, **otros)
    director = crear_director(
        config, gestor.provider(), gestor, llm, tmp_path / "runs", mesa_limpia=True
    )
    turnos = conversar(director, mensajes)
    assert llm.pendientes() == {}
    return turnos, llm


def _tickers(corrida: Corrida) -> list[str]:
    return [d["ticker"] for d in (corrida.estado.get(CLAVE_UNIVERSO) or {}).get("diagnosticos", [])]


def test_la_sesion_abre_limpia_y_el_guardado_solo_se_menciona(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    guion = [Llamada("consultar_mesa_trabajo"), "La mesa está limpia. ¿Con qué tickers partimos?"]
    (apertura,), llm = _charlar(config, gestor, tmp_path, guion, ["hola"])

    assert apertura.estado.get(CLAVE_UNIVERSO) is None, "nada cargado"
    assert apertura.estado[CLAVE_ORIGEN_UNIVERSO] == ORIGEN_SESION
    for clave in ("quant_estimates", "candidatos", "restricciones_sesion", "market_views"):
        assert not apertura.estado.get(clave), clave
    narracion, bloque = apertura.textos("director")[0].split(MARCA_ANEXO)
    assert TITULO_MESA_LIMPIA in bloque
    assert f"NO cargado: {', '.join(ACTIVOS)}" in bloque
    assert all(a not in narracion for a in ACTIVOS), "el guion no los nombró: los trae el código"
    # El Director sabe que la mesa está limpia ANTES de llamar a nada, y ya no se le ordena
    # presentar un universo previo.
    assert MESA_LIMPIA in llm.instrucciones("director")[0]
    assert "si existe un universo previo" not in INSTRUCCION
    assert "Al inicio la mesa está limpia" in INSTRUCCION
    assert "Nunca inventes, sugieras ni des como ejemplo activos" in INSTRUCCION


def test_con_la_mesa_limpia_ninguna_herramienta_de_analisis_corre(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    """Personas, Analista, Constructor y el gate del comité: error de dominio, no excepción; y
    el Analista NO cae al universo de ``config.yaml`` (su LLM ni siquiera se llama)."""
    guion = [
        Llamada("estadistico", pregunta="¿correlación VOOG-VB?"),
        Llamada("esceptico", pregunta="¿y esta cartera?", pesos={"VOOG": 0.5, "VB": 0.5}),
        Llamada("market_analyst", request="dame views"),
        Llamada("construir_candidatos"),
        Llamada("ajustar_restricciones", peso_max=0.5),
        Llamada("convocar_comite", fase="solicitar"),
        gestor_op("montos"),
        gestor_op("plan_compra", aporte_usd=500),
        "Primero hay que configurar el universo: ¿con qué tickers?",
    ]
    (turno,), _ = _charlar(
        config, gestor, tmp_path, guion, ["50/50 VOOG y VB, aporté 500, convoca al comité"]
    )
    for tool in (
        "estadistico",
        "esceptico",
        "market_analyst",
        "construir_candidatos",
        "ajustar_restricciones",
        "convocar_comite",
        "montos",
        "plan_compra",
    ):
        (respuesta,) = turno.respuestas(tool)
        assert respuesta["status"] == "error" and respuesta["tipo"] == "SinUniversoError", tool
        assert SIN_UNIVERSO in respuesta["mensaje"], tool
    assert turno.estado.get(CLAVE_UNIVERSO) is None
    assert not (tmp_path / "runs").exists()


def test_usa_el_guardado_lo_carga_con_diagnosticos_y_desde_ahi_todo_funciona(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    guion = [
        Llamada("consultar_mesa_trabajo"),
        "Mesa limpia.",
        gestor_op("cargar_guardado"),
        "Cargado el guardado, con sus diagnósticos.",
        Llamada("estadistico", pregunta="¿qué correlación hay entre VOOG y VB?"),
        "Ya respondió el Estadístico.",
    ]
    estadistico = [Llamada("estimar_mercado"), "Exploratorio: correlación alta."]
    (_, carga, consulta), _ = _charlar(
        config,
        gestor,
        tmp_path,
        guion,
        ["hola", "usa el guardado", "¿correlación VOOG-VB?"],
        estadistico=estadistico,
    )
    (respuesta,) = carga.respuestas("cargar_guardado")
    assert respuesta["status"] == "success"
    assert [a["ticker"] for a in respuesta["activos"]] == list(ACTIVOS)
    assert respuesta["universo"]["activo_mas_corto"] == "IBIT"
    assert _tickers(carga) == list(ACTIVOS)
    assert carga.estado[CLAVE_ORIGEN_UNIVERSO] == ORIGEN_GUARDADO
    assert consulta.respuestas("estimar_mercado")[0]["status"] == "success"


def test_una_lista_en_el_primer_turno_define_el_universo_de_la_sesion(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    guardado = gestor.ruta_universo.read_bytes()
    lista = ["AAPL", "QQQ"]
    guion = [
        gestor_op("resolver", tickers=lista),
        "Diagnóstico de tu lista; ¿los incorporo?",
        gestor_op("incorporar", tickers=lista),
        "Entró AAPL. QQQ no tiene capitalización en la fuente: ¿subyacente, AUM o neutral?",
        Llamada("consultar_mesa_trabajo"),
        "Esta es la mesa.",
    ]
    (vista, alta, mesa), _ = _charlar(
        config,
        gestor,
        tmp_path,
        guion,
        ["partamos con AAPL y QQQ", "sí, incorpóralos", "¿qué hay?"],
    )
    assert vista.respuestas("resolver")[0]["sin_cap_en_la_fuente"] == ["QQQ"]
    assert _tickers(vista) == [], "resolver no carga nada"
    (respuesta,) = alta.respuestas("incorporar")
    assert respuesta["incorporados"] == ["AAPL"] and respuesta["universo_completo"] is False
    assert [p["activo"]["ticker"] for p in respuesta["pendientes_de_prior"]] == ["QQQ"]
    assert _tickers(alta) == ["AAPL"], "estrictamente lo ingresado: ni VOOG ni BNS ni IBIT ni VB"
    assert gestor.ruta_universo.read_bytes() == guardado, "el modo comando conserva su universo"

    bloque = mesa.textos("director")[0].split(MARCA_ANEXO)[1]
    assert "### Mesa de trabajo (universo" in bloque and "AAPL" in bloque
    primera_fila = next(linea for linea in bloque.splitlines() if linea.startswith("| **"))
    assert primera_fila.startswith("| **Universo** |") and "la limita AAPL" in primera_fila
    assert all(a not in bloque for a in ACTIVOS)


def test_un_ticker_que_el_usuario_no_escribio_no_entra_al_universo(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    """Custodia de procedencia: el Director no completa la lista del usuario (ni en lote)."""
    guion = [
        gestor_op("incorporar", tickers=["AAPL", "QQQ"]),  # el usuario solo escribió aapl
        gestor_op("incorporar", ticker="QQQ"),
        gestor_op("incorporar", tickers=["AAPL"]),
        "Entró AAPL. No propongo otros activos: ¿cuáles más quieres?",
    ]
    (turno,), _ = _charlar(config, gestor, tmp_path, guion, ["parte con aapl y lo que creas bueno"])
    lote, suelto, bien = turno.respuestas("incorporar")
    for rechazo in (lote, suelto):
        assert rechazo["status"] == "rechazado" and rechazo["tipo"] == "TickerSinProcedencia"
        assert "QQQ" in rechazo["motivo"] and "AAPL" not in rechazo["motivo"].split(":")[0]
    assert bien["status"] == "success" and _tickers(turno) == ["AAPL"]


def test_solo_apps_equipo_arranca_en_blanco_y_el_modo_comando_no_cambia() -> None:
    equipo = (RAIZ_PROYECTO / "apps/equipo/agent.py").read_text("utf-8")
    comando = (RAIZ_PROYECTO / "comando/pipeline/agent.py").read_text("utf-8")
    assert "mesa_limpia=True" in equipo
    assert "mesa_limpia" not in comando and "crear_pipeline(" in comando
