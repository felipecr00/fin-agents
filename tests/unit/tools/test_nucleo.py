"""Los FunctionTools no añaden matemática: mismo resultado que el núcleo, vía estado de ADK."""

from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest
from google.adk.tools import ToolContext

from investmentsys.config import Config, hash_config
from investmentsys.contracts import (
    CandidatePortfolios,
    DiagnosticoCartera,
    EtapaCorrida,
    MarketViews,
    PortfolioConstraints,
    QuantEstimates,
    RunState,
    Universe,
    ValidationReport,
    Veredicto,
)
from investmentsys.portfolio import optimizar_black_litterman
from investmentsys.quant import estimar
from investmentsys.tools import (
    CLAVE_CANDIDATOS,
    CLAVE_DIAGNOSTICOS_CARTERA,
    CLAVE_FECHA_DECISION,
    CLAVE_MARKET_VIEWS,
    CLAVE_PRIOR,
    CLAVE_QUANT_ESTIMATES,
    CLAVE_RESTRICCIONES,
    CLAVE_RESTRICCIONES_SESION,
    CLAVE_UNIVERSO,
    CLAVE_VALIDACIONES,
    NucleoTools,
)
from tests.almacen import universo_referencia
from tests.conftest import ACTIVOS, FECHA

PESOS_GOLDEN = {"VOOG": 0.70, "BNS": 0.07, "IBIT": 0.02, "VB": 0.21}
TOLERANCIA_GOLDEN = 0.02


def _universo_con_otra_cap() -> Universe:
    """Mismos activos y datos, otra cap congelada: otra ``universe_version`` (ADR-012)."""
    referencia = universo_referencia()
    primero, *resto = referencia.diagnosticos
    assert primero.prior_cap is not None
    recapitalizado = primero.model_copy(update={"prior_cap": primero.prior_cap * 2})
    return Universe.crear((recapitalizado, *resto), referencia.origenes)


def _con_views(ctx: ToolContext, views: MarketViews) -> ToolContext:
    ctx.state[CLAVE_MARKET_VIEWS] = views.model_dump(mode="json")
    return ctx


def _hasta_candidatos(tools: NucleoTools, ctx: ToolContext, views: MarketViews) -> ToolContext:
    assert tools.estimar_mercado(ctx)["status"] == "success"
    assert tools.construir_candidatos(_con_views(ctx, views))["status"] == "success"
    return ctx


class TestDeclaraciones:
    def test_nombres_y_parametros_visibles_para_el_llm(self, tools: NucleoTools) -> None:
        declaraciones = {t.name: t._get_declaration() for t in tools.function_tools()}
        assert list(declaraciones) == [
            "estimar_mercado",
            "construir_candidatos",
            "validar_candidato",
        ]
        construir = declaraciones["construir_candidatos"]
        assert construir is not None
        parametros = construir.parameters_json_schema["properties"]
        assert set(parametros) == {"recomendado", "peso_max_por_activo"}
        assert "required" not in construir.parameters_json_schema

    def test_toda_declaracion_lleva_descripcion(self, tools: NucleoTools) -> None:
        for tool in tools.function_tools():
            declaracion = tool._get_declaration()
            assert declaracion is not None and declaracion.description


class TestEstimarMercado:
    def test_sin_fecha_usa_el_ultimo_cierre_y_escribe_el_contrato(
        self, tools: NucleoTools, ctx: ToolContext
    ) -> None:
        salida = tools.estimar_mercado(ctx)
        assert salida["status"] == "success"
        assert ctx.state[CLAVE_FECHA_DECISION] == FECHA.isoformat()
        estimaciones = QuantEstimates.model_validate(ctx.state[CLAVE_QUANT_ESTIMATES])
        assert estimaciones.activos == ACTIVOS
        assert estimaciones.fecha_decision == FECHA

    def test_mismas_cifras_que_el_nucleo(
        self, tools: NucleoTools, config: Config, ctx: ToolContext
    ) -> None:
        salida = tools.estimar_mercado(ctx)
        directo = estimar(
            tools.provider.retornos_log(ACTIVOS, hasta=FECHA),
            fecha_decision=FECHA,
            periodos_por_anio=tools.provider.periodos_por_anio,
            ventana_meses=config.datos.ventana_covarianza_meses,
            metodos=(config.optimizacion.metodo_covarianza,),
            nivel_confianza=config.estimacion.nivel_confianza,
            regimen=config.regimen,
            universe_version=universo_referencia().version,
        )
        assert QuantEstimates.model_validate(ctx.state[CLAVE_QUANT_ESTIMATES]) == directo
        assert salida["regimen"] == directo.regimen.value != "indeterminado"
        cov = directo.covarianza(config.optimizacion.metodo_covarianza)
        for activo in ACTIVOS:
            assert salida["por_activo"][activo]["volatilidad_anual"] == cov.volatilidad(activo)

    def test_sin_look_ahead_respeta_la_fecha_de_la_corrida(
        self, tools: NucleoTools, ctx: ToolContext
    ) -> None:
        fecha = date(2025, 6, 30)
        ctx.state[CLAVE_FECHA_DECISION] = fecha.isoformat()
        assert tools.estimar_mercado(ctx)["status"] == "success"
        estimaciones = QuantEstimates.model_validate(ctx.state[CLAVE_QUANT_ESTIMATES])
        assert estimaciones.fecha_fin_muestra <= fecha
        assert ctx.state[CLAVE_FECHA_DECISION] == fecha.isoformat()

    def test_la_salida_y_el_estado_son_json(self, tools: NucleoTools, ctx: ToolContext) -> None:
        json.dumps(tools.estimar_mercado(ctx))
        json.dumps(ctx.state.to_dict())


class TestConstruirCandidatos:
    def test_sin_estimaciones_devuelve_error_y_no_lanza(
        self, tools: NucleoTools, ctx: ToolContext, views_golden: MarketViews
    ) -> None:
        salida = tools.construir_candidatos(_con_views(ctx, views_golden))
        assert salida["status"] == "error"
        assert salida["tipo"] == "FaltaEnEstadoError"
        assert CLAVE_QUANT_ESTIMATES in salida["mensaje"]

    def test_sin_views_devuelve_error(self, tools: NucleoTools, ctx: ToolContext) -> None:
        tools.estimar_mercado(ctx)
        salida = tools.construir_candidatos(ctx)
        assert salida["status"] == "error"
        assert CLAVE_MARKET_VIEWS in salida["mensaje"]
        assert ctx.state.get(CLAVE_CANDIDATOS) is None

    def test_views_golden_reproducen_la_referencia(
        self, tools: NucleoTools, config: Config, ctx: ToolContext, views_golden: MarketViews
    ) -> None:
        _hasta_candidatos(tools, ctx, views_golden)
        (ronda,) = (CandidatePortfolios.model_validate(c) for c in ctx.state[CLAVE_CANDIDATOS])
        assert ronda.iteracion == 1
        assert ronda.recomendado == "black_litterman"
        assert [c.nombre for c in ronda.candidatos] == ["black_litterman", "hrp", "min_varianza"]
        pesos = ronda.portafolio_recomendado.pesos
        for activo, esperado in PESOS_GOLDEN.items():
            assert pesos[activo] == pytest.approx(esperado, abs=TOLERANCIA_GOLDEN)

        restricciones = PortfolioConstraints.model_validate(ctx.state[CLAVE_RESTRICCIONES])
        directo = optimizar_black_litterman(
            QuantEstimates.model_validate(ctx.state[CLAVE_QUANT_ESTIMATES]),
            views_golden,
            restricciones,
            config.optimizacion,
            config.prior_equilibrio,
        )
        assert ronda.portafolio_recomendado == directo

    def test_recomendar_otra_tecnica(
        self, tools: NucleoTools, ctx: ToolContext, views_golden: MarketViews
    ) -> None:
        tools.estimar_mercado(ctx)
        salida = tools.construir_candidatos(_con_views(ctx, views_golden), recomendado="hrp")
        assert salida["recomendado"] == "hrp"

    def test_recomendado_desconocido_es_error_de_contrato(
        self, tools: NucleoTools, ctx: ToolContext, views_golden: MarketViews
    ) -> None:
        tools.estimar_mercado(ctx)
        salida = tools.construir_candidatos(_con_views(ctx, views_golden), recomendado="momentum")
        assert salida["status"] == "error"
        assert "momentum" in salida["mensaje"]
        assert ctx.state.get(CLAVE_CANDIDATOS) is None

    def test_endurecer_un_maximo_lo_respeta_el_optimizador(
        self, tools: NucleoTools, ctx: ToolContext, views_golden: MarketViews
    ) -> None:
        tools.estimar_mercado(ctx)
        salida = tools.construir_candidatos(
            _con_views(ctx, views_golden), peso_max_por_activo={"VOOG": 0.6}
        )
        assert salida["status"] == "success"
        assert salida["limites"]["VOOG"] == [0.02, 0.6]
        for candidato in salida["candidatos"].values():
            assert candidato["pesos"]["VOOG"] <= 0.6 + 1e-6

    def test_relajar_un_maximo_se_rechaza(
        self, tools: NucleoTools, ctx: ToolContext, views_golden: MarketViews
    ) -> None:
        tools.estimar_mercado(ctx)
        salida = tools.construir_candidatos(
            _con_views(ctx, views_golden), peso_max_por_activo={"VOOG": 0.8}
        )
        assert salida["status"] == "error"
        assert "solo puede ENDURECER" in salida["mensaje"]


class TestValidarCandidato:
    def test_sin_candidatos_devuelve_error(self, tools: NucleoTools, ctx: ToolContext) -> None:
        salida = tools.validar_candidato(ctx)
        assert salida["status"] == "error"
        assert CLAVE_CANDIDATOS in salida["mensaje"]

    def test_la_referencia_queda_aprobada_y_el_estado_arma_un_run_state(
        self, tools: NucleoTools, config: Config, ctx: ToolContext, views_golden: MarketViews
    ) -> None:
        _hasta_candidatos(tools, ctx, views_golden)
        salida = tools.validar_candidato(ctx)
        assert salida["veredicto"] == Veredicto.APROBADA.value
        assert salida["criterios_incumplidos"] == []
        assert salida["look_ahead_verificado"] is True
        json.dumps(salida)

        estado = ctx.state.to_dict()
        corrida = RunState.model_validate(
            {
                "run_id": "test",
                "creado_en": "2026-09-30T00:00:00",
                "fecha_decision": estado[CLAVE_FECHA_DECISION],
                "semilla": config.reproducibilidad.semilla,
                "config_hash": hash_config(),
                "activos": ACTIVOS,
                "universo": estado[CLAVE_UNIVERSO],
                "restricciones_sesion": estado[CLAVE_RESTRICCIONES_SESION],
                "prior": estado[CLAVE_PRIOR],
                "etapa": EtapaCorrida.VALIDACION,
                "restricciones": estado[CLAVE_RESTRICCIONES],
                "market_views": estado[CLAVE_MARKET_VIEWS],
                "quant_estimates": estado[CLAVE_QUANT_ESTIMATES],
                "candidatos": estado[CLAVE_CANDIDATOS],
                "validaciones": estado[CLAVE_VALIDACIONES],
            }
        )
        assert corrida.aprobado
        assert corrida.portafolio_final is not None

    def test_no_se_valida_dos_veces_la_misma_iteracion(
        self, tools: NucleoTools, ctx: ToolContext, views_golden: MarketViews
    ) -> None:
        _hasta_candidatos(tools, ctx, views_golden)
        tools.validar_candidato(ctx)
        salida = tools.validar_candidato(ctx)
        assert salida["status"] == "error"
        assert len(ctx.state[CLAVE_VALIDACIONES]) == 1

    def test_bucle_constructor_validador_respeta_el_maximo_de_iteraciones(
        self, tools: NucleoTools, config: Config, ctx: ToolContext, views_golden: MarketViews
    ) -> None:
        _hasta_candidatos(tools, ctx, views_golden)
        sin_validar = tools.construir_candidatos(ctx)
        assert sin_validar["status"] == "error" and "validado" in sin_validar["mensaje"]

        maximo = config.validacion.max_iteraciones_constructor
        tools.validar_candidato(ctx)
        for iteracion in range(2, maximo + 1):
            assert tools.construir_candidatos(ctx)["iteracion"] == iteracion
            assert tools.validar_candidato(ctx)["iteracion"] == iteracion
        agotado = tools.construir_candidatos(ctx)
        assert agotado["status"] == "error" and "máximo" in agotado["mensaje"]
        reportes = [ValidationReport.model_validate(v) for v in ctx.state[CLAVE_VALIDACIONES]]
        assert [r.iteracion for r in reportes] == list(range(1, maximo + 1))


class TestDiagnosticarCartera:
    def test_pesos_validos_dan_un_diagnostico_etiquetado_y_sin_veredicto(
        self, tools: NucleoTools, ctx: ToolContext
    ) -> None:
        salida = tools.diagnosticar_cartera(PESOS_GOLDEN, ctx)
        assert salida["status"] == "success"
        assert salida["etiqueta"] == "diagnostico" and salida["validado"] is False
        assert salida["universe_version"] == universo_referencia().version
        assert salida["pesos_evaluados"] == PESOS_GOLDEN
        volcado = json.dumps(salida)
        assert "veredicto" not in volcado
        assert "APROBADA" not in volcado and "RECHAZADA" not in volcado

        (crudo,) = ctx.state[CLAVE_DIAGNOSTICOS_CARTERA]
        diagnostico = DiagnosticoCartera.model_validate(crudo)
        assert diagnostico.validado is False and "veredicto" not in crudo
        assert salida["metricas_oos"]["sharpe_oos"] == diagnostico.metricas_oos.sharpe_oos
        # Exploratorio: nada que un RunState lea como validación del comité.
        assert ctx.state.get(CLAVE_VALIDACIONES) is None
        assert ctx.state.get(CLAVE_CANDIDATOS) is None

    def test_mide_lo_mismo_que_el_validador_del_comite(
        self, tools: NucleoTools, ctx: ToolContext, views_golden: MarketViews
    ) -> None:
        """Envoltorio fino: mismos pesos → mismas métricas que ``validar_candidato``."""
        _hasta_candidatos(tools, ctx, views_golden)
        comite = tools.validar_candidato(ctx)
        ronda = CandidatePortfolios.model_validate(ctx.state[CLAVE_CANDIDATOS][-1])
        salida = tools.diagnosticar_cartera(dict(ronda.portafolio_recomendado.pesos), ctx)
        for metrica, valor in comite["metricas_oos"].items():
            assert salida["metricas_oos"][metrica] == valor
        assert len(ctx.state[CLAVE_VALIDACIONES]) == 1  # el diagnóstico no añade validaciones

    def test_un_activo_omitido_pesa_cero(self, tools: NucleoTools, ctx: ToolContext) -> None:
        salida = tools.diagnosticar_cartera({"VOOG": 0.6, "VB": 0.4}, ctx)
        assert salida["pesos_evaluados"] == {"VOOG": 0.6, "BNS": 0.0, "IBIT": 0.0, "VB": 0.4}

    def test_pesos_que_no_suman_uno_son_un_error_descriptivo(
        self, tools: NucleoTools, ctx: ToolContext
    ) -> None:
        salida = tools.diagnosticar_cartera({"VOOG": 0.5, "BNS": 0.3}, ctx)
        assert salida["status"] == "error" and salida["tipo"] == "CarteraInvalidaError"
        assert "suman 0.800000" in salida["mensaje"] and "No se renormalizan" in salida["mensaje"]
        assert ctx.state.get(CLAVE_DIAGNOSTICOS_CARTERA) is None
        assert ctx.state.get(CLAVE_QUANT_ESTIMATES) is None  # validó ANTES de calcular

    def test_activo_fuera_del_universo_es_un_error_descriptivo(
        self, tools: NucleoTools, ctx: ToolContext
    ) -> None:
        salida = tools.diagnosticar_cartera({"VOOG": 0.5, "NVDA": 0.5}, ctx)
        assert salida["status"] == "error" and salida["tipo"] == "CarteraInvalidaError"
        assert "['NVDA']" in salida["mensaje"] and "Gestor de Datos" in salida["mensaje"]
        assert ctx.state.get(CLAVE_DIAGNOSTICOS_CARTERA) is None

    def test_posicion_corta_es_un_error_descriptivo(
        self, tools: NucleoTools, ctx: ToolContext
    ) -> None:
        salida = tools.diagnosticar_cartera({"VOOG": 1.2, "IBIT": -0.2}, ctx)
        assert salida["status"] == "error" and "cortas" in salida["mensaje"]

    def test_sello_obsoleto_es_un_rechazo_que_dice_que_recalcular(
        self, tools: NucleoTools, ctx: ToolContext
    ) -> None:
        assert tools.estimar_mercado(ctx)["status"] == "success"
        ctx.state[CLAVE_UNIVERSO] = _universo_con_otra_cap().model_dump(mode="json")
        salida = tools.diagnosticar_cartera(PESOS_GOLDEN, ctx)
        assert salida["status"] == "error" and salida["tipo"] == "ResultadoObsoletoError"
        assert "estimaciones del Quant: obsoleto" in salida["mensaje"]
        assert ctx.state.get(CLAVE_DIAGNOSTICOS_CARTERA) is None

    def test_no_es_un_tool_del_pipeline(self, tools: NucleoTools) -> None:
        """El comité no diagnostica carteras sueltas: solo el Director recibe este tool."""
        assert tools.diagnosticar_cartera not in tools.funciones()


class TestAjustarRestricciones:
    def test_el_ajuste_del_usuario_queda_en_la_sesion_con_su_origen(
        self, tools: NucleoTools, ctx: ToolContext
    ) -> None:
        salida = tools.ajustar_restricciones(
            ctx, peso_max=0.8, limites_por_activo={"IBIT": [0.0, 0.1]}
        )
        assert salida["status"] == "success"
        assert salida["peso_max"] == {"valor": 0.8, "origen": "ajuste_usuario"}
        assert salida["peso_min"]["origen"] == "default_config"  # lo no pedido no cambia
        assert salida["limites_vigentes"]["IBIT"] == [0.0, 0.1]
        assert salida["limites_vigentes"]["VOOG"] == [0.02, 0.8]
        sesion = ctx.state[CLAVE_RESTRICCIONES_SESION]
        assert sesion["universe_version"] == universo_referencia().version
        assert sesion["limites_por_activo"]["IBIT"]["origen"] == "ajuste_usuario"

    def test_el_constructor_usa_las_restricciones_ajustadas(
        self, tools: NucleoTools, ctx: ToolContext, views_golden: MarketViews
    ) -> None:
        assert tools.ajustar_restricciones(ctx, peso_max=0.4)["status"] == "success"
        _hasta_candidatos(tools, ctx, views_golden)
        ronda = CandidatePortfolios.model_validate(ctx.state[CLAVE_CANDIDATOS][-1])
        assert max(ronda.portafolio_recomendado.pesos.values()) <= 0.4 + 1e-9

    @pytest.mark.parametrize(
        ("args", "fragmento"),
        [
            ({"peso_min": 0.3}, "los pisos suman 120.00% > 100 %"),
            ({"peso_max": 0.2}, "los techos suman 80.00% < 100 %"),
            ({"peso_min": 0.5, "peso_max": 0.4}, "peso_min mayor que peso_max"),
            ({"limites_por_activo": {"NVDA": [0.0, 0.5]}}, "tickers fuera del universo"),
            ({"limites_por_activo": {"IBIT": [0.3, 0.1]}}, "límite inferior mayor"),
            ({"limites_por_activo": {"IBIT": [0.1]}}, "[mínimo, máximo]"),
            ({}, "nada que ajustar"),
        ],
    )
    def test_pedido_infactible_es_un_error_claro_y_las_vigentes_no_cambian(
        self, tools: NucleoTools, ctx: ToolContext, args: dict[str, object], fragmento: str
    ) -> None:
        assert tools.ajustar_restricciones(ctx, peso_max=0.6)["status"] == "success"
        previa = dict(ctx.state[CLAVE_RESTRICCIONES_SESION])
        salida = tools.ajustar_restricciones(ctx, **args)  # type: ignore[arg-type]
        assert salida["status"] == "error" and fragmento in salida["mensaje"]
        assert "validation error" not in salida["mensaje"]  # sin ruido de pydantic
        assert ctx.state[CLAVE_RESTRICCIONES_SESION] == previa

    def test_restablecer_vuelve_a_las_de_config(
        self, tools: NucleoTools, config: Config, ctx: ToolContext
    ) -> None:
        tools.ajustar_restricciones(ctx, peso_max=0.5)
        salida = tools.ajustar_restricciones(ctx, restablecer=True)
        assert salida["peso_max"] == {
            "valor": config.optimizacion.peso_max,
            "origen": "default_config",
        }
        assert salida["limites_propios"] == {}


def test_por_function_tool_los_cambios_viajan_en_el_state_delta(
    tools: NucleoTools, ctx: ToolContext
) -> None:
    """Camino real de ADK: ``run_async`` inyecta el contexto y el delta queda en las acciones."""
    (estimar_tool, *_) = tools.function_tools()
    salida = asyncio.run(estimar_tool.run_async(args={}, tool_context=ctx))
    assert salida["status"] == "success"
    assert set(ctx.actions.state_delta) == {CLAVE_FECHA_DECISION, CLAVE_QUANT_ESTIMATES}
