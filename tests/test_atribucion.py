"""Verificación de atribución (S9): ninguna cifra de retorno, riesgo o correlación sin su fuente.

El evaluador (``evaluacion.criterios_director.cifras_sin_atribuir``) es el mismo que usa el
evalset del Director contra el modelo real (criterio ``cifras_atribuidas``). Aquí se prueba el
evaluador y se le pasan respuestas del Director sobre el ``Runner`` real con LLM guionado: una
narración que suelta la cifra sin nombrar a nadie FALLA aunque la cifra sea correcta y aunque
la ficha de origen (que redacta el código) venga anexada; los bloques del código siempre pasan.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from google.adk.models.llm_request import LlmRequest

from investmentsys.agents.director import crear_director
from investmentsys.config import Config, cargar_config
from investmentsys.contracts import Especialista
from investmentsys.data_manager import GestorDatos
from investmentsys.evaluacion.criterios_director import (
    Criterios,
    TurnoObservado,
    cifras_sin_atribuir,
    evaluar,
    fuentes_atribuibles,
)
from tests.almacen import sembrar_gestor
from tests.integration.conftest import Llamada, LlmPorAgente, conversar, gestor_op
from tests.integration.test_market_analyst import BORRADOR_GOLDEN

PESOS = {"VOOG": 0.5, "VB": 0.3, "BNS": 0.2}


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config()


@pytest.fixture
def gestor(tmp_path: Path, config: Config) -> GestorDatos:
    return sembrar_gestor(tmp_path / "almacen", config)


# --------------------------------------------------------------------- el evaluador
@pytest.mark.parametrize(
    "texto",
    [
        "El Estadístico estimó que la correlación entre VOOG y VB es de 0.7578.",
        "Según el Escéptico, la caída máxima fue de 29.1 % y el Sharpe OOS de 0.56.",
        "El comité aprobó la cartera: retorno anualizado 10.12 %, volatilidad 18.57 %.",
        "El Constructor propone VOOG 70 %: retorno esperado 9.4 % con volatilidad 17.0 %.",
        "El Analista opina que VOOG superará a VB, con un retorno relativo de 3 % anual.",
        "Esto midió el Estadístico:\n\n* VOOG: volatilidad 19.17 %\n* BNS: volatilidad 23.76 %",
        "El Gestor de Datos informa 33 meses de ventana común.",  # sin cifra atribuible
        "Las restricciones son 2 % y 70 % por activo.",  # no es retorno, riesgo ni correlación
        "Tu cartera tiene 50 % en VOOG y 30 % en VB.",  # lo dijo el usuario; no es una métrica
    ],
)
def test_pasa_lo_que_nombra_a_su_fuente_o_no_es_una_cifra_atribuible(texto: str) -> None:
    assert cifras_sin_atribuir(texto) == []


@pytest.mark.parametrize(
    ("texto", "culpable"),
    [
        ("La correlación entre VOOG y VB es de 0.7578.", "0.7578"),
        ("La volatilidad anual de IBIT es 51.12 %, la más alta.", "51.12"),
        ("Resultado exploratorio: Sharpe OOS 0.56 y caída máxima de 29.1 %.", "0.56"),
        ("El retorno esperado es de 9.4 %.", "9.4"),
        # El Director coordina, no calcula: no es una fuente de cifras.
        ("Como Director, te informo que el riesgo de la cartera es 18.5 %.", "18.5"),
        # Una lista solo hereda la atribución del párrafo que la encabeza.
        ("Estos son los números:\n\n* VOOG: volatilidad 19.17 %", "19.17"),
        # Nombrar a la fuente en OTRO párrafo no atribuye este.
        ("Hablé con el Estadístico.\n\nLa volatilidad de VOOG es 19.17 %.", "19.17"),
    ],
)
def test_falla_la_cifra_de_retorno_riesgo_o_correlacion_sin_fuente(
    texto: str, culpable: str
) -> None:
    (linea,) = cifras_sin_atribuir(texto)
    assert culpable in linea


def test_las_fuentes_salen_del_roster_y_el_director_no_es_una() -> None:
    fuentes = fuentes_atribuibles()
    assert {"estadistico", "esceptico", "gestor de datos", "comite", "analista"} <= set(fuentes)
    assert "director" not in fuentes
    assert all(e.value for e in Especialista)


def test_el_criterio_del_evalset_reporta_las_lineas_culpables() -> None:
    turno = TurnoObservado(usuario="¿riesgo?", texto="La volatilidad de VOOG es 19.17 %.")
    (resultado,) = evaluar(Criterios(cifras_atribuidas=True), turno, "turno1")
    assert resultado.criterio == "turno1.cifras_atribuidas" and not resultado.cumple
    assert "19.17" in resultado.detalle


# ------------------------------------------------- respuestas del Director (Runner real)
# S10: las cifras del Estadístico y del Escéptico las dicen ELLOS (su autoría es la atribución).
# El Director sigue narrando al Constructor, al Gestor y al comité: ahí se le exige la fuente.
PROPUESTA = [Llamada("market_analyst", request="views de partida"), Llamada("construir_candidatos")]
PERSONAS: dict[str, list[Any]] = {
    "estadistico": [Llamada("estimar_mercado"), "Exploratorio: estimé una correlación alta."],
    "esceptico": [Llamada("diagnosticar_cartera"), "Exploratorio: me preocupa la concentración."],
}


def _responder(
    config: Config,
    gestor: GestorDatos,
    runs: Path,
    guion: list[Any],
    mensaje: str,
    **otros: list[Any],
) -> str:
    llm = LlmPorAgente(director=guion, analista=[BORRADOR_GOLDEN], **otros)
    (turno,) = conversar(crear_director(config, gestor.provider(), gestor, llm, runs), [mensaje])
    assert llm.pendientes() == {}
    return turno.textos("director")[-1]


def _recomendada(peticion: LlmRequest) -> dict[str, Any]:
    salida = next(
        dict(p.function_response.response or {})
        for c in reversed(peticion.contents)
        for p in c.parts or []
        if p.function_response and p.function_response.name == "construir_candidatos"
    )
    cartera: dict[str, Any] = salida["candidatos"][salida["recomendado"]]
    return cartera


def test_el_director_que_suelta_la_cifra_sin_fuente_falla_aunque_lleve_la_ficha(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    def sin_fuente(peticion: LlmRequest) -> str:
        c = _recomendada(peticion)
        return f"Exploratorio: el retorno esperado es {c['retorno_esperado_anual'] * 100:.2f} %."

    texto = _responder(config, gestor, tmp_path, [*PROPUESTA, sin_fuente], "propón una cartera")
    assert "Ficha de origen" in texto and "**Constructor de Carteras**" in texto, "la ficha está…"
    (linea,) = cifras_sin_atribuir(texto)
    assert linea.startswith("exploratorio: el retorno esperado"), "…pero la NARRACIÓN no atribuye"


def test_el_director_que_nombra_al_especialista_pasa(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    def con_fuente(peticion: LlmRequest) -> str:
        c = _recomendada(peticion)
        return (
            "Propuesta exploratoria. El Constructor propone una cartera con retorno esperado de "
            f"{c['retorno_esperado_anual'] * 100:.2f} % y Sharpe {c['sharpe']:.2f}."
        )

    texto = _responder(config, gestor, tmp_path, [*PROPUESTA, con_fuente], "propón una cartera")
    assert cifras_sin_atribuir(texto) == []


def test_los_bloques_que_redacta_el_codigo_siempre_atribuyen(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    """Fichas de las personas y del Constructor, y la mesa: ninguna cifra huérfana."""
    guion = [
        Llamada("estadistico", pregunta="estima"),
        Llamada("esceptico", pregunta="diagnostica", pesos=PESOS),
        *PROPUESTA,
        gestor_op("montos"),
        Llamada("consultar_mesa_trabajo"),
        "Listo.",
    ]
    texto = _responder(
        config, gestor, tmp_path, guion, "estima, diagnostica, propón y muestra", **PERSONAS
    )
    for bloque in (
        "### Mesa de trabajo",
        "**Estadístico**",
        "**Escéptico**",
        "**Constructor de Carteras**",
        "**Gestor de Datos** · herramienta `gestionar_datos_y_fricciones`",
        "NO VALIDADO",
    ):
        assert bloque in texto
    assert cifras_sin_atribuir(texto) == []
