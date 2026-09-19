"""El evalset versionado: en sync con su YAML, válido para ADK y con la cobertura de S5."""

from __future__ import annotations

from collections import Counter

from google.adk.evaluation.local_eval_sets_manager import load_eval_set_from_file

from investmentsys.config import RAIZ_PROYECTO, cargar_config
from investmentsys.evaluacion.criterios import CriteriosCaso
from investmentsys.evaluacion.evalset import cargar_casos, construir_evalset, serializar
from investmentsys.tools.estado import CLAVE_FECHA_DECISION

CARPETA = RAIZ_PROYECTO / "tests" / "eval"
CASOS = cargar_casos(CARPETA / "casos_market_analyst.yaml")
EVALSET = CARPETA / "market_analyst.evalset.json"
APP = "market_analyst"
MINIMO_DE_CASOS = 8
CATEGORIAS = {
    "alcista_clara",
    "bajista_clara",
    "ambigua",
    "contradictoria",
    "trampa",
    "sin_material",
}


def test_el_json_versionado_es_el_que_genera_el_yaml() -> None:
    generado = serializar(construir_evalset(CASOS, APP))
    assert EVALSET.read_text(encoding="utf-8") == generado, "desactualizado: corre `make evalset`"


def test_adk_lo_carga_sin_conversion_de_formato() -> None:
    evalset = load_eval_set_from_file(str(EVALSET), "ignorado")
    assert evalset.eval_set_id == CASOS.eval_set_id
    assert len(evalset.eval_cases) == len(CASOS.casos)


def test_cobertura_de_categorias() -> None:
    por_categoria = Counter(c.categoria for c in CASOS.casos)
    assert len(CASOS.casos) >= MINIMO_DE_CASOS
    assert set(por_categoria) == CATEGORIAS


def test_cada_caso_tiene_criterios_propios_validos_sobre_el_universo() -> None:
    universo = set(cargar_config().portafolio.activos)
    for caso in CASOS.casos:
        criterios = CASOS.criterios(caso)
        propios = criterios.model_dump(exclude_defaults=True, exclude={"fecha_decision"})
        assert propios, f"{caso.id}: solo tiene criterios universales"
        mencionados = (
            set(criterios.direccion)
            | set(criterios.direccion_prohibida)
            | set(criterios.sin_conviccion)
            | set(criterios.confianza_max)
        )
        assert mencionados <= universo, f"{caso.id}: activos fuera del universo"


def test_los_criterios_viajan_en_la_respuesta_esperada_con_la_fecha_de_la_sesion() -> None:
    evalset = load_eval_set_from_file(str(EVALSET), "ignorado")
    for caso in evalset.eval_cases:
        assert caso.conversation is not None and caso.session_input is not None
        (invocacion,) = caso.conversation
        assert invocacion.final_response is not None and invocacion.final_response.parts
        criterios = CriteriosCaso.model_validate_json(invocacion.final_response.parts[0].text or "")
        fecha_sesion = caso.session_input.state[CLAVE_FECHA_DECISION]
        assert criterios.fecha_decision.isoformat() == fecha_sesion
        assert caso.session_input.app_name == APP


def test_las_trampas_contienen_la_instruccion_maliciosa_y_prohiben_su_rastro() -> None:
    trampas = [c for c in CASOS.casos if c.categoria == "trampa"]
    for caso in trampas:
        criterios = CASOS.criterios(caso)
        assert criterios.texto_prohibido, f"{caso.id}: sin canario"
        canario = criterios.texto_prohibido[0]
        assert caso.noticias is not None
        assert canario in caso.noticias, f"{caso.id}: el canario no está en la noticia"
