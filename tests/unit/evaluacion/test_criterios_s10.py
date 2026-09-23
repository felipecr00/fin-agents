"""Criterios del evalset que añade S10 (ADR-019): voces de las personas y cifras con miles."""

from __future__ import annotations

from investmentsys.agents.anexos import MARCA_ANEXO as MARCA_DEL_CODIGO
from investmentsys.evaluacion.criterios_director import (
    MARCA_ANEXO,
    Criterios,
    TurnoObservado,
    cifras_sin_respaldo,
    evaluar,
    lineas_no_negadas,
)
from investmentsys.evaluacion.director import nombre_observado

VOZ = ("estadistico", "Exploratorio: estimé una correlación de 0.76 con tope de 70 %.")


def _no_repite(texto: str, previo: tuple[str, ...] = ()) -> bool:
    turno = TurnoObservado(
        usuario="¿correlación?", texto=texto, voces=(VOZ,), respaldo_previo=previo
    )
    (resultado,) = evaluar(Criterios(no_repite_cifras=True), turno, "t")
    return resultado.cumple


def test_la_marca_del_anexo_es_la_misma_que_usa_el_codigo() -> None:
    assert MARCA_ANEXO == MARCA_DEL_CODIGO


def test_no_repite_cifras_detecta_al_director_que_re_narra() -> None:
    assert not _no_repite("El Estadístico estimó 0.76.")
    assert _no_repite("Ya respondió el Estadístico. ¿Seguimos?")


def test_la_ficha_anexada_por_codigo_no_cuenta_como_re_narracion() -> None:
    assert _no_repite(f"Ya respondió.\n\n{MARCA_ANEXO}\n\n---\n\n- correlaciones: VOOG-VB 0.76")


def test_una_cifra_que_el_director_ya_conocia_no_es_re_narrar() -> None:
    assert not _no_repite("Podemos bajar el tope del 70 %.")
    assert _no_repite("Podemos bajar el tope del 70 %.", previo=("pesos 2%-70%",))


def test_habla_exige_texto_de_la_persona_en_el_turno() -> None:
    mudo = TurnoObservado(usuario="x", texto="El Estadístico dice…")
    (resultado,) = evaluar(Criterios(habla=("estadistico",)), mudo, "t")
    assert not resultado.cumple and "estadistico" in resultado.detalle
    (resultado,) = evaluar(
        Criterios(habla=("estadistico",)), TurnoObservado("x", voces=(VOZ,)), "t"
    )
    assert resultado.cumple


def test_los_criterios_de_texto_miran_lo_que_el_usuario_leyo_personas_incluidas() -> None:
    turno = TurnoObservado(usuario="x", texto="Ya respondió.", voces=(VOZ,))
    (resultado,) = evaluar(Criterios(texto_alguno=(("exploratori",),)), turno, "t")
    assert resultado.cumple
    (resultado,) = evaluar(Criterios(cifras_respaldadas=True), turno, "t")
    assert not resultado.cumple, "la cifra de la persona también se exige respaldada"


def test_montos_con_separador_de_miles_son_una_sola_cifra() -> None:
    fuentes = ['{"valor_cartera_usd": 9739.94, "monto": 2243.52, "corr": 0.7578}']
    assert cifras_sin_respaldo("US$ 9,739.94 y US$ 2,243.52; correlación 0,76", fuentes) == []
    assert cifras_sin_respaldo("US$ 9,740.94", fuentes) == ["9,740.94"]


def test_fuera_de_banda_no_es_una_negacion() -> None:
    assert lineas_no_negadas("VOOG está fuera de banda: vender.") != []
    assert lineas_no_negadas("No indica vender nada.") == []
    # Visto con el modelo real: negar sin decir "no".
    assert lineas_no_negadas("En lugar de vender lo sobreponderado, se usan flujos nuevos.") == []
    assert lineas_no_negadas("Así evitamos vender con ganancia.") == []


def test_una_tool_que_despacha_por_operacion_se_observa_como_tool_operacion() -> None:
    assert nombre_observado("gestionar_datos_y_fricciones", {"operacion": "montos"}) == (
        "gestionar_datos_y_fricciones:montos"
    )
    assert nombre_observado("estimar_mercado", {}) == "estimar_mercado"


def test_truncar_no_es_redondear_el_detector_no_se_afloja() -> None:
    """Decisión de S10: se probó admitir el truncado y 0.7578 pasó a respaldar "0.75"."""
    fuentes = ['{"max_drawdown": 0.28816, "correlacion": 0.7578}']
    assert cifras_sin_respaldo("drawdown del 28.82 %", fuentes) == []
    assert cifras_sin_respaldo("drawdown del 28.81 %; correlación 0.75", fuentes) == [
        "28.81 %",
        "0.75",
    ]


def test_anunciar_los_anexos_no_es_rehacer_un_bloque() -> None:
    """Visto con el modelo real (2026-09-21): «### Mesa de Trabajo y Fichas Técnicas» seguido de
    una frase contaba como bloque imitado. Rehacerlo es el título MÁS contenido estructurado."""
    from investmentsys.evaluacion.criterios_director import bloques_con_contenido, normalizar

    anuncia = "### Mesa de Trabajo y Fichas Técnicas\nA continuación van los anexos del plan.\n"
    rehace = "### Plan de Compra Neta (por defecto)\n* VB: US$ 500\n* VOOG: nada\n"
    tabla = "### En la sala\n\n| Silla | Atiende |\n| Escéptico | todo |\n"
    assert bloques_con_contenido(normalizar(anuncia)) == []
    assert len(bloques_con_contenido(normalizar(rehace))) == 1
    assert len(bloques_con_contenido(normalizar(tabla))) == 1
    assert len(bloques_con_contenido(normalizar(anuncia + rehace + tabla))) == 2
