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
from investmentsys.tools.estado import CLAVE_SOLICITUD_NEUTRAL
from investmentsys.tools.gestor import GestorTools
from tests.almacen import (
    FuenteFalsa,
    cap_fuente,
    diagnosticar,
    panel_referencia,
    sembrar_gestor,
    serie_sintetica,
)
from tests.unit.tools.conftest import Turnos

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
        rechazo = diagnosticar(tools, {"AAPL": 1.0}, ctx)
        assert rechazo["tipo"] == "ResultadoObsoletoError"

    def test_sin_resultados_previos_no_hay_nada_obsoleto(
        self, gestor_tools: GestorTools, ctx: ToolContext
    ) -> None:
        assert gestor_tools.incorporar("AAPL", ctx)["resultados_obsoletos"] == []

    def test_retirar_declara_obsoletos_y_conserva_la_serie_como_cache(
        self, gestor_tools: GestorTools, tools: NucleoTools, ctx: ToolContext
    ) -> None:
        assert tools.estimar_mercado(ctx)["status"] == "success"
        serie = gestor_tools.gestor.directorio_series / "BNS.csv"
        contenido = serie.read_bytes()

        salida = gestor_tools.retirar("bns", ctx)
        assert salida["status"] == "success"
        assert [a["ticker"] for a in salida["activos"]] == ["VOOG", "IBIT", "VB"]
        assert ctx.state[CLAVE_UNIVERSO]["version"] == salida["universe_version"]
        assert _resultados(salida) == ["estimaciones del Estadístico"]
        assert serie.read_bytes() == contenido, "la serie se conserva como caché"
        historial = gestor_tools.gestor.ruta_historial.read_text("utf-8").splitlines()
        assert '"accion": "retirar"' in historial[-1] and '"ticker": "BNS"' in historial[-1]
        assert tools.estimar_mercado(ctx)["status"] == "success"  # el universo nuevo se estima

    def test_retirar_lo_que_no_esta_es_un_error_del_gestor(
        self, gestor_tools: GestorTools, ctx: ToolContext
    ) -> None:
        salida = gestor_tools.retirar("NVDA", ctx)
        assert salida["status"] == "error" and "no está en el universo" in salida["mensaje"]

    def test_almacen_de_solo_lectura_es_un_error_de_dominio_que_dice_que_hacer(
        self, gestor_tools: GestorTools, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """En el contenedor ``data/`` es de root: el tool se explica en vez de reventar."""

        def sin_permiso(*_: object, **__: object) -> None:
            raise PermissionError(13, "Permission denied", "/app/data/universo.json")

        monkeypatch.setattr("investmentsys.data_manager.gestor._escribir_atomico", sin_permiso)
        previa = ctx.state[CLAVE_UNIVERSO]["version"]
        salida = gestor_tools.retirar("BNS", ctx)
        assert salida["status"] == "error" and salida["tipo"] == "GestorError"
        assert "no admite cambios de universo" in salida["mensaje"]
        assert "en local" in salida["mensaje"]
        assert ctx.state[CLAVE_UNIVERSO]["version"] == previa


class TestCustodiaDelPriorNeutral:
    """ADR-015 §A: degradar TODO el prior exige un turno del usuario tras la advertencia."""

    def test_secuencia_mala_todo_en_un_turno_no_degrada(
        self, gestor_tools: GestorTools, turnos: Turnos
    ) -> None:
        ctx = turnos("inv-1")
        assert gestor_tools.incorporar("QQQ", ctx)["estado_prior"] == "pendiente"
        for _ in range(3):  # insistir en el mismo turno no cambia nada
            salida = gestor_tools.aceptar_prior_neutral(ctx)
            assert salida["status"] == "rechazado"
            assert salida["motivo"].startswith(
                "degradar el prior requiere confirmación explícita en un turno posterior; "
                "presenta la advertencia todo-o-nada y espera"
            )
            assert "VOOG, BNS, IBIT, VB, QQQ" in salida["motivo"]
        assert not gestor_tools.gestor.universo().prior_neutral_aceptado

    def test_secuencia_buena_advertencia_y_confirmacion_en_otro_turno(
        self, gestor_tools: GestorTools, turnos: Turnos
    ) -> None:
        primero = turnos("inv-1")
        gestor_tools.incorporar("QQQ", primero)
        assert gestor_tools.aceptar_prior_neutral(primero)["status"] == "rechazado"
        segundo = turnos("inv-2")  # el usuario vio la advertencia y confirmó
        salida = gestor_tools.aceptar_prior_neutral(segundo)
        assert salida["status"] == "success" and salida["estado_prior"] == "neutral"
        assert segundo.state[CLAVE_UNIVERSO]["prior_neutral_aceptado"] is True
        assert segundo.state[CLAVE_SOLICITUD_NEUTRAL] is None

    def test_sin_advertencia_previa_un_turno_nuevo_tampoco_basta(
        self, gestor_tools: GestorTools, turnos: Turnos
    ) -> None:
        """ "Sí, neutral" sin haber visto la advertencia: la primera llamada siempre advierte."""
        gestor_tools.incorporar("QQQ", turnos("inv-1"))
        assert gestor_tools.aceptar_prior_neutral(turnos("inv-2"))["status"] == "rechazado"
        assert gestor_tools.aceptar_prior_neutral(turnos("inv-3"))["status"] == "success"

    def test_si_el_universo_cambia_tras_la_advertencia_hay_que_advertir_de_nuevo(
        self, gestor_tools: GestorTools, turnos: Turnos
    ) -> None:
        gestor_tools.incorporar("QQQ", turnos("inv-1"))
        assert gestor_tools.aceptar_prior_neutral(turnos("inv-1"))["status"] == "rechazado"
        gestor_tools.retirar("BNS", turnos("inv-2"))
        salida = gestor_tools.aceptar_prior_neutral(turnos("inv-3"))
        assert salida["status"] == "rechazado" and "BNS" not in salida["motivo"]
        assert gestor_tools.aceptar_prior_neutral(turnos("inv-4"))["status"] == "success"

    def test_sin_caps_pendientes_el_error_es_el_del_gestor(
        self, gestor_tools: GestorTools, turnos: Turnos
    ) -> None:
        gestor_tools.aceptar_prior_neutral(turnos("inv-1"))
        salida = gestor_tools.aceptar_prior_neutral(turnos("inv-2"))
        assert salida["status"] == "error" and "nada que degradar" in salida["mensaje"]


class TestOtrosCambios:
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
