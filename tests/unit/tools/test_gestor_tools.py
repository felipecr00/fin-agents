"""``GestorTools``: el Gestor de S7 como FunctionTools; cada cambio declara lo que deja obsoleto."""

from __future__ import annotations

from pathlib import Path

import pytest
from google.adk.tools import ToolContext

from investmentsys.config import Config
from investmentsys.orchestrator import CLAVE_SOLICITUD
from investmentsys.tools import (
    CLAVE_QUANT_ESTIMATES,
    CLAVE_RESTRICCIONES_SESION,
    CLAVE_UNIVERSO,
    NucleoTools,
)
from investmentsys.tools.gestor import GestorTools
from tests.almacen import FuenteFalsa, cap_fuente, panel_referencia, sembrar_gestor, serie_sintetica

FIN = panel_referencia().index[-1]


@pytest.fixture
def fuente() -> FuenteFalsa:
    return FuenteFalsa(
        series={
            "AAPL": serie_sintetica("AAPL", 80, FIN),
            "QQQ": serie_sintetica("QQQ", 80, FIN, semilla=11),
            "SAN": serie_sintetica("SAN", 80, FIN, semilla=13),
        },
        bolsas={"SAN": "BME"},
        caps={"AAPL": cap_fuente()},
    )


@pytest.fixture
def gestor_tools(tmp_path: Path, config: Config, fuente: FuenteFalsa) -> GestorTools:
    return GestorTools(sembrar_gestor(tmp_path, config, fuente))


def _resultados(salida: dict[str, object]) -> list[str]:
    obsoletos = salida["resultados_obsoletos"]
    assert isinstance(obsoletos, list)
    return [o["resultado"] for o in obsoletos]


def test_declaraciones_visibles_para_el_llm(gestor_tools: GestorTools) -> None:
    declaraciones = {t.name: t._get_declaration() for t in gestor_tools.function_tools()}
    assert list(declaraciones) == [
        "resolver",
        "incorporar",
        "aceptar_prior_neutral",
        "refrescar_cap",
        "diagnosticar",
    ]
    incorporar = declaraciones["incorporar"]
    assert incorporar is not None and incorporar.description
    esquema = incorporar.parameters_json_schema
    assert set(esquema["properties"]) == {"ticker", "prior_cap", "prior_metodologia"}
    assert esquema["required"] == ["ticker"]  # degradar a neutral NO es un argumento del alta


class TestResolver:
    def test_accion_con_cap_en_la_fuente(self, gestor_tools: GestorTools) -> None:
        activo = gestor_tools.resolver("aapl")["activo"]
        assert activo["ticker"] == "AAPL" and activo["apto"]
        assert activo["prior"]["tiene_cap"] and activo["prior"]["procedencia"] == "fuente"
        assert "10^12" in activo["prior"]["unidad_cap"]

    def test_etf_sin_cap_pide_resolver_el_prior(self, gestor_tools: GestorTools) -> None:
        prior = gestor_tools.resolver("QQQ")["activo"]["prior"]
        assert prior == {**prior, "tiene_cap": False, "cap_usd_billones": None}

    @pytest.mark.parametrize(("ticker", "fragmento"), [("ZZZZ", "inexistente"), ("SAN", "moneda")])
    def test_ticker_no_resoluble_es_un_error_de_la_herramienta(
        self, gestor_tools: GestorTools, ticker: str, fragmento: str
    ) -> None:
        salida = gestor_tools.resolver(ticker)
        assert salida["status"] == "error" and fragmento in salida["mensaje"]


class TestCambiosDeUniverso:
    def test_incorporar_actualiza_la_sesion_y_declara_los_obsoletos_por_sello(
        self, gestor_tools: GestorTools, tools: NucleoTools, ctx: ToolContext
    ) -> None:
        assert tools.estimar_mercado(ctx)["status"] == "success"
        tools._sesion(ctx.state, tools._universo(ctx.state))  # restricciones por defecto
        ctx.state[CLAVE_SOLICITUD] = {"token": "t"}
        previa = ctx.state[CLAVE_UNIVERSO]["version"]

        salida = gestor_tools.incorporar("AAPL", ctx)
        assert salida["status"] == "success" and salida["universe_version"] != previa
        assert ctx.state[CLAVE_UNIVERSO]["version"] == salida["universe_version"]
        assert [a["ticker"] for a in salida["activos"]][-1] == "AAPL"
        assert _resultados(salida) == [
            "estimaciones del Estadístico",
            "restricciones de la sesión",
            "solicitud al comité (resumen y token)",
        ]
        # Lo sellado se queda y las herramientas lo rechazan; lo demás se retira.
        assert ctx.state[CLAVE_QUANT_ESTIMATES]["universe_version"] == previa
        assert ctx.state[CLAVE_RESTRICCIONES_SESION] is None
        assert ctx.state[CLAVE_SOLICITUD] is None
        rechazo = tools.diagnosticar_cartera({"AAPL": 1.0}, ctx)
        assert rechazo["tipo"] == "ResultadoObsoletoError"

    def test_sin_resultados_previos_no_hay_nada_obsoleto(
        self, gestor_tools: GestorTools, ctx: ToolContext
    ) -> None:
        assert gestor_tools.incorporar("AAPL", ctx)["resultados_obsoletos"] == []

    def test_etf_sin_cap_entra_con_el_prior_pendiente_y_neutral_es_todo_o_nada(
        self, gestor_tools: GestorTools, ctx: ToolContext
    ) -> None:
        alta = gestor_tools.incorporar("QQQ", ctx)
        assert alta["estado_prior"] == "pendiente" and "QQQ" in alta["mensaje_prior"]
        neutral = gestor_tools.aceptar_prior_neutral(ctx)
        assert neutral["estado_prior"] == "neutral"
        assert ctx.state[CLAVE_UNIVERSO]["prior_neutral_aceptado"] is True

    def test_cap_del_usuario_exige_metodologia(
        self, gestor_tools: GestorTools, ctx: ToolContext
    ) -> None:
        previa = ctx.state[CLAVE_UNIVERSO]["version"]
        salida = gestor_tools.incorporar("QQQ", ctx, prior_cap=22.0)
        assert salida["status"] == "error" and "prior_metodologia" in salida["mensaje"]
        assert ctx.state[CLAVE_UNIVERSO]["version"] == previa
        ok = gestor_tools.incorporar("QQQ", ctx, 22.0, "capitalización del Nasdaq-100")
        assert ok["estado_prior"] == "capitalizacion"
        assert ok["activos"][-1]["prior"]["procedencia"] == "usuario"

    def test_refrescar_cap_cambia_la_version(
        self, gestor_tools: GestorTools, ctx: ToolContext
    ) -> None:
        previa = ctx.state[CLAVE_UNIVERSO]["version"]
        salida = gestor_tools.refrescar_cap("bns", ctx, 0.12, "cap bursátil")
        assert salida["status"] == "success" and salida["universe_version"] != previa

    def test_diagnosticar_describe_el_universo_sin_modificarlo(
        self, gestor_tools: GestorTools, ctx: ToolContext
    ) -> None:
        previa = ctx.state[CLAVE_UNIVERSO]["version"]
        salida = gestor_tools.diagnosticar(ctx)
        assert salida["status"] == "success" and salida["resultados_obsoletos"] == []
        assert salida["universo"]["universe_version"] == previa
        assert salida["universo"]["activo_mas_corto"] == "IBIT"
