"""Criterios puros del evalset del Director: cada uno detecta lo suyo y nada más."""

from __future__ import annotations

from typing import Any

import pytest

from investmentsys.evaluacion.criterios_director import (
    Criterios,
    TurnoObservado,
    cifras_sin_respaldo,
    coincide,
    evaluar,
    normalizar,
)

TURNO = TurnoObservado(
    usuario="pon un tope de 80%",
    llamadas=(
        ("resolver", {"ticker": "QQQ"}),
        ("incorporar", {"ticker": "QQQ", "prior_cap": None}),
    ),
    respuestas=(
        ("resolver", {"status": "success"}),
        ("incorporar", {"status": "error"}),
        ("incorporar", {"status": "success", "sharpe": 0.4321, "vol": 0.1917}),
    ),
    texto="Exploratorio: Sharpe 0.43, volatilidad 19.17 %, tope 80%. Afecta a TODO el universo.",
)


def _fallidos(**criterios: Any) -> list[str]:
    resultados = evaluar(Criterios.model_validate(criterios), TURNO, "t")
    assert len(resultados) == len(criterios) or "argumentos" in criterios or "status" in criterios
    return [r.criterio for r in resultados if not r.cumple]


@pytest.mark.parametrize(
    ("criterios", "fallidos"),
    [
        ({"tools_permitidas": ["resolver", "incorporar"]}, []),
        ({"tools_permitidas": ["resolver"]}, ["t.tools_permitidas"]),
        ({"tools_permitidas": []}, ["t.tools_permitidas"]),
        ({"tools_obligatorias": ["resolver"]}, []),
        ({"tools_obligatorias": ["retirar"]}, ["t.tools_obligatorias"]),
        ({"tools_prohibidas": ["retirar"]}, []),
        ({"tools_prohibidas": ["incorporar"]}, ["t.tools_prohibidas"]),
        ({"argumentos": {"incorporar": {"exige": {"ticker": "QQQ"}}}}, []),
        ({"argumentos": {"incorporar": {"exige": {"ticker": "SPY"}}}}, ["t.argumentos.incorporar"]),
        ({"argumentos": {"incorporar": {"prohibe": ["prior_cap"]}}}, []),  # None = no lo trajo
        ({"argumentos": {"resolver": {"prohibe": ["ticker"]}}}, ["t.argumentos.resolver"]),
        ({"status": {"incorporar": "success"}}, []),  # cuenta la ÚLTIMA respuesta
        ({"status": {"incorporar": "error"}}, ["t.status.incorporar"]),
        ({"status": {"retirar": "success"}}, ["t.status.retirar"]),  # no se llamó
        ({"status_prohibido": {"incorporar": "error"}}, ["t.status_prohibido.incorporar"]),
        ({"status_prohibido": {"resolver": "error"}}, []),
        ({"texto_alguno": [["todo-o-nada", "afecta a todo"], ["EXPLORATORIO"]]}, []),
        ({"texto_alguno": [["volatilidad"], ["veredicto"]]}, ["t.texto_alguno"]),
        ({"texto_prohibido": ["APROBADA"]}, []),
        ({"texto_prohibido": ["sharpe"]}, ["t.texto_prohibido"]),
        ({"cifras_respaldadas": True}, []),
        ({"no_ofrece": ["universo"]}, ["t.no_ofrece"]),
        ({"no_ofrece": ["alerta"]}, []),
    ],
)
def test_cada_criterio(criterios: dict[str, Any], fallidos: list[str]) -> None:
    assert _fallidos(**criterios) == fallidos


def test_sin_criterios_definidos_no_hay_resultados() -> None:
    assert evaluar(Criterios(), TURNO, "t") == []


class TestCifras:
    FUENTES = ('{"corr": 0.7578471445, "vol": 0.19171, "n": 60}', "tope de 10% por activo")

    @pytest.mark.parametrize(
        "texto",
        [
            "correlación 0.7578",
            "de 0.76 (aprox. 75.78 %)",
            "volatilidad 19.17%",
            "el tope del 10% que pediste",
            "con coma decimal: 0,758",
            "1. primero; 2. segundo; 60 observaciones en 2026",  # enteros sueltos: no son cifras
            "versión `249d7971d404` del universo",
        ],
    )
    def test_respaldadas(self, texto: str) -> None:
        assert cifras_sin_respaldo(texto, self.FUENTES) == []

    @pytest.mark.parametrize(
        ("texto", "huerfanas"),
        [
            ("correlación 0.75", ["0.75"]),  # 0.7578 redondea a 0.76, no a 0.75
            ("retorno esperado de 12.5 %", ["12.5 %"]),
            ("Sharpe 1.20 y drawdown 35%", ["1.20", "35%"]),
        ],
    )
    def test_inventadas(self, texto: str, huerfanas: list[str]) -> None:
        assert cifras_sin_respaldo(texto, self.FUENTES) == huerfanas

    def test_los_turnos_anteriores_tambien_respaldan(self) -> None:
        turno = TurnoObservado(
            usuario="¿y entonces?", texto="Como vimos, 0.7578.", respaldo_previo=self.FUENTES
        )
        (resultado,) = evaluar(Criterios(cifras_respaldadas=True), turno, "t")
        assert resultado.cumple


def test_normalizar_ignora_mayusculas_y_acentos() -> None:
    assert normalizar("Comité FORMAL: confirmación") == "comite formal: confirmacion"


def test_coincide_compara_solo_lo_esperado_y_tolera_el_punto_flotante() -> None:
    assert coincide({"pesos": {"VOOG": 0.5, "IBIT": 0.0}, "extra": 1}, {"pesos": {"VOOG": 0.5}})
    assert coincide({"peso_min": 0.30000000000000004}, {"peso_min": 0.3})
    assert not coincide({"pesos": {"VOOG": 0.6}}, {"pesos": {"VOOG": 0.5}})
    assert not coincide({"fase": True}, {"fase": 1})


def test_no_ofrece_admite_la_negacion_y_detecta_la_oferta() -> None:
    criterios = Criterios(no_ofrece=("tiempo real", "alerta"))
    niega = TurnoObservado(usuario="x", texto="Modo D: no hacemos monitoreo en tiempo real.")
    ofrece = TurnoObservado(usuario="x", texto="Armo tu cartera.\nY te mando una alerta si cae.")
    assert evaluar(criterios, niega, "t")[0].cumple
    (resultado,) = evaluar(criterios, ofrece, "t")
    assert not resultado.cumple and "alerta" in resultado.detalle
