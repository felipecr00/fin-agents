"""S9 — la sala se ve: mesa, roster, fichas y orden del comité los anexa el CÓDIGO.

LLM falso sobre el ``Runner`` real. El guion narra MAL a propósito (no etiqueta, no atribuye, no
copia nada): lo que se prueba es que el bloque llega igual al usuario, porque no depende de él.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from google.adk.models.llm_request import LlmRequest

from investmentsys.agents.anexos import (
    CLAVE_ANEXOS_TURNO,
    MARCA_ANEXO,
)
from investmentsys.agents.anexos import SEPARADOR as SEPARADOR_DE_BLOQUES
from investmentsys.agents.director import crear_director
from investmentsys.config import Config
from investmentsys.data_manager import GestorDatos
from investmentsys.tools.ficha import (
    ATIENDE,
    CLAVE_ANEXO,
    ETIQUETA_FICHA_EXPLORATORIA,
    PREFIJO_NO_VALIDADO,
)
from tests.almacen import sembrar_gestor
from tests.integration.conftest import Corrida, Llamada, LlmPorAgente, conversar
from tests.integration.test_director import cifras_sin_respaldo

NARRACION_POBRE = "Listo."
SEPARADOR = f"\n\n{MARCA_ANEXO}{SEPARADOR_DE_BLOQUES}"  # termina el LLM, empieza el código


@pytest.fixture
def gestor(tmp_path: Path, config: Config) -> GestorDatos:
    return sembrar_gestor(tmp_path / "almacen", config)


ESTADISTICO = [Llamada("estimar_mercado"), "Exploratorio: estimé una correlación alta."]


def _charlar(
    config: Config,
    gestor: GestorDatos,
    tmp_path: Path,
    guion: list[Any],
    mensajes: list[str],
    **personas: list[Any],
) -> tuple[list[Corrida], LlmPorAgente]:
    llm = LlmPorAgente(director=guion, **personas)
    director = crear_director(config, gestor.provider(), gestor, llm, tmp_path / "runs")
    turnos = conversar(director, mensajes)
    assert llm.pendientes() == {}
    return turnos, llm


def _lo_que_vio_el_llm(peticion: LlmRequest, tool: str) -> dict[str, Any]:
    return next(
        dict(p.function_response.response or {})
        for c in reversed(peticion.contents)
        for p in c.parts or []
        if p.function_response and p.function_response.name == tool
    )


def test_apertura_con_mesa_la_tabla_llega_aunque_el_director_no_la_copie(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    vistos: list[dict[str, Any]] = []

    def saludar(peticion: LlmRequest) -> str:
        vistos.append(_lo_que_vio_el_llm(peticion, "consultar_mesa_trabajo"))
        return "Hola. ¿Seguimos con este universo?"

    (turno,), _ = _charlar(
        config, gestor, tmp_path, [Llamada("consultar_mesa_trabajo"), saludar], ["hola"]
    )
    (respuesta,) = turno.textos("director")
    narracion, tabla = respuesta.split(SEPARADOR)
    assert narracion == "Hola. ¿Seguimos con este universo?"
    assert tabla.startswith(f"### Mesa de trabajo (universo `{gestor.universo().version[:12]}`")
    assert "| **Universo** | VOOG (datos desde 2021-09)" in tabla
    assert "| **Restricción** | peso por activo entre 2 %" in tabla
    # El LLM recibe los datos de la mesa, no el bloque redactado: no hay nada que copiar mal.
    (visto,) = vistos
    assert CLAVE_ANEXO not in visto and "se anexa solo" in visto["anexo"]
    assert visto["mesa"]["items"][0]["categoria"] == "Universo"
    assert turno.estado.get(CLAVE_ANEXOS_TURNO) is None, "entregado: no se repite"


def test_consulta_con_ficha_la_etiqueta_sobrevive_a_una_narracion_que_la_omite(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    """S10: la ficha la recoge la PERSONA (el Director solo recibe su texto) y llega igual."""
    guion = [Llamada("estadistico", pregunta="¿correlación VOOG-VB?"), "Ya respondió."]
    persona = [Llamada("estimar_mercado"), "La correlación entre VOOG y VB es alta."]
    (turno,), _ = _charlar(
        config, gestor, tmp_path, guion, ["¿correlación VOOG-VB?"], estadistico=persona
    )
    assert "exploratori" not in turno.textos("estadistico")[0].lower(), "la persona NO etiqueta"
    (respuesta,) = turno.textos("director")
    (salida,) = turno.respuestas("estimar_mercado")
    assert "exploratori" not in respuesta.split(SEPARADOR)[0].lower(), "el guion NO etiqueta"
    ficha = respuesta.split(SEPARADOR)[1]
    assert ficha.startswith(f"**Ficha de origen — {ETIQUETA_FICHA_EXPLORATORIA}**")
    assert "- Fuente: **Estadístico** · herramienta `estimar_mercado` · universo " in ficha
    assert f"`{gestor.universo().version[:12]}`" in ficha
    cifras = ficha.splitlines()[2:]
    assert len(cifras) == 5 and all(c.startswith(f"- {PREFIJO_NO_VALIDADO}") for c in cifras)
    assert f"VOOG-VB {salida['correlaciones']['VOOG-VB']:.2f}" in cifras[-1]
    assert cifras_sin_respaldo(respuesta, [salida]) == []


def test_quien_esta_en_la_sala_es_la_composicion_real_del_director(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    guion = [Llamada("consultar_mesa_trabajo", vista="sala"), NARRACION_POBRE]
    (turno,), _ = _charlar(config, gestor, tmp_path, guion, ["¿quién está en la sala?"])
    sala = turno.textos("director")[0].split(SEPARADOR)[1]
    director = crear_director(config, gestor.provider(), gestor, "sin-llamar", tmp_path)
    reales = {t.name for t in director.tools}  # type: ignore[union-attr]
    reales |= {t.name for a in director.sub_agents for t in getattr(a, "tools", [])}
    assert reales == set(ATIENDE), "toda herramienta del equipo tiene silla, y viceversa"
    for nombre in reales:
        assert f"`{nombre}`" in sala
    assert "| **Analista de Mercado** | conversa (LLM) | `market_analyst` |" in sala
    # S10: el Estadístico y el Escéptico ya son personas; el Gestor sigue sin voz propia.
    assert "| **Escéptico** | conversa (LLM) | `esceptico`, `diagnosticar_cartera` |" in sala
    assert "| **Estadístico** | conversa (LLM) | `estadistico`, `estimar_mercado` |" in sala
    assert "| **Gestor de Datos** | herramientas deterministas | `gestionar_datos_y_" in sala


def test_la_orden_preparatoria_se_anexa_al_solicitar_y_no_se_repite_despues(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    guion = [Llamada("convocar_comite", fase="solicitar"), "Revisa la orden.", "De nada."]
    (solicitud, charla), _ = _charlar(
        config, gestor, tmp_path, guion, ["convoca al comité", "gracias, aún no"]
    )
    narracion, orden = solicitud.textos("director")[0].split(SEPARADOR)
    assert narracion == "Revisa la orden."
    assert orden.startswith("### Orden Preparatoria de Sesión — Comité formal")
    assert orden.endswith("¿Confirmas la convocatoria formal para iniciar la deliberación?")
    assert charla.textos("director") == ["De nada."], "un turno sin herramientas no anexa nada"


def test_un_resultado_con_error_no_anexa_ficha(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    guion = [Llamada("esceptico", pregunta="¿y 90 %?", pesos={"VOOG": 0.9}), "No suman 1."]
    persona = [Llamada("diagnosticar_cartera"), "No puedo: los pesos no suman 1."]
    (turno,), _ = _charlar(config, gestor, tmp_path, guion, ["90 % VOOG"], esceptico=persona)
    assert turno.respuestas("diagnosticar_cartera")[0]["status"] == "error"
    assert turno.textos("director") == ["No suman 1."]


def test_el_modelo_no_ve_en_su_historial_los_bloques_que_anexo_el_codigo(
    config: Config, gestor: GestorDatos, tmp_path: Path
) -> None:
    """Visto en la demo real: si los ve, desde el segundo turno los imita (sin el prefijo)."""
    historial: list[str] = []

    def espiar(peticion: LlmRequest) -> str:
        historial.extend(
            p.text for c in peticion.contents if c.role == "model" for p in c.parts or [] if p.text
        )
        return "De nada."

    guion = [
        Llamada("estadistico", pregunta="¿correlación?"),
        "El Estadístico estimó la correlación.",
        espiar,
    ]
    (primero, _), _ = _charlar(
        config, gestor, tmp_path, guion, ["¿correlación?", "gracias"], estadistico=ESTADISTICO
    )
    assert "Ficha de origen" in primero.textos("director")[0], "el usuario SÍ la vio"
    (propio,) = historial
    assert propio == "El Estadístico estimó la correlación.", "ni bloques ni notas que imitar"
    assert "Ficha de origen" not in propio and MARCA_ANEXO not in propio
