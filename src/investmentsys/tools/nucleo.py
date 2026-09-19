"""FunctionTools de ADK sobre el núcleo puro (``quant/``, ``portfolio/``, ``risk/``).

Reglas (CLAUDE.md):
- Aquí no hay matemática: cada tool lee contratos del estado de sesión, llama a una función
  pura y escribe el contrato resultante. Las cifras salen del núcleo, nunca del LLM.
- Los argumentos que decide un LLM son pocos y pequeños (qué candidato recomendar, qué
  límite endurecer); los contratos grandes viajan por el estado (ver ``estado.py``).
- S7: los tools operan sobre el ``Universe`` y las ``SessionConstraints`` del estado (nunca
  sobre listas de tickers), SELLAN su salida con ``universe_version`` y rechazan todo input
  sin sello o sellado con otra versión (ADR-012).
- Un error de dominio no lanza: devuelve ``{"status": "error", ...}`` para que el agente
  pueda corregir y reintentar. Todo lo demás es un bug y sí se propaga.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext
from pydantic import ValidationError

from investmentsys.config import Config, RegimenConfig
from investmentsys.contracts import (
    CandidatePortfolio,
    CandidatePortfolios,
    DiagnosticoCartera,
    MarketViews,
    PriorSnapshot,
    QuantEstimates,
    SessionConstraints,
    TecnicaOptimizacion,
    Universe,
    ValidationReport,
)
from investmentsys.data import PriceProvider
from investmentsys.portfolio import (
    OptimizacionFallidaError,
    PriorNoDisponibleError,
    cartera_del_usuario,
    optimizar_black_litterman,
    optimizar_hrp,
    optimizar_min_varianza,
    resolver_prior,
    restricciones_de_iteracion,
    sesion_ajustada,
    sesion_por_defecto,
    validar_pesos_usuario,
)
from investmentsys.portfolio.black_litterman import NOMBRE_CANDIDATO as NOMBRE_BL
from investmentsys.portfolio.hrp import NOMBRE_CANDIDATO as NOMBRE_HRP
from investmentsys.quant import LookAheadError, MuestraInsuficienteError, estimar
from investmentsys.risk import validar
from investmentsys.tools.estado import (
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
    Estado,
    FaltaEnEstadoError,
    agregar,
    exigir_sello,
    leer,
    leer_fecha,
    leer_lista,
    volcar,
)

ERRORES_DE_DOMINIO = (
    FaltaEnEstadoError,
    LookAheadError,
    MuestraInsuficienteError,
    OptimizacionFallidaError,
    ValidationError,
    ValueError,
)


def _error(exc: Exception) -> dict[str, Any]:
    return {"status": "error", "tipo": type(exc).__name__, "mensaje": str(exc)}


@dataclass(frozen=True)
class NucleoTools:
    """Los tools comparten ``config.yaml`` y el proveedor de precios; nada más."""

    config: Config
    provider: PriceProvider

    # ------------------------------------------------------------------ Quant
    def estimar_mercado(self, tool_context: ToolContext) -> dict[str, Any]:
        """Estima covarianzas y retornos históricos con datos hasta la fecha de decisión.

        Usa la fecha de decisión de la corrida (o el último cierre disponible si no hay una)
        y guarda las estimaciones completas en el estado. Devuelve un resumen por activo:
        volatilidad anual, retorno histórico anual con su intervalo y observaciones usadas.
        """
        try:
            return self._estimar_mercado(tool_context.state)
        except ERRORES_DE_DOMINIO as exc:
            return _error(exc)

    def _estimar_mercado(self, estado: Estado) -> dict[str, Any]:
        universo = self._universo(estado)
        activos = universo.activos
        fecha = leer_fecha(estado) or self._ultimo_cierre(activos)
        estimaciones = estimar(
            self.provider.retornos_log(activos, hasta=fecha),
            fecha_decision=fecha,
            periodos_por_anio=self.provider.periodos_por_anio,
            ventana_meses=self.config.datos.ventana_covarianza_meses,
            metodos=(self.config.optimizacion.metodo_covarianza,),
            nivel_confianza=self.config.estimacion.nivel_confianza,
            regimen=self._regimen(activos),
            universe_version=universo.version,
        )
        estado[CLAVE_FECHA_DECISION] = fecha.isoformat()
        estado[CLAVE_QUANT_ESTIMATES] = volcar(estimaciones)
        cov = estimaciones.covarianza(self.config.optimizacion.metodo_covarianza)
        return {
            "status": "success",
            "universe_version": universo.version,
            "fecha_decision": fecha.isoformat(),
            "muestra": [
                estimaciones.fecha_inicio_muestra.isoformat(),
                estimaciones.fecha_fin_muestra.isoformat(),
            ],
            "metodo_covarianza": str(cov.metodo),
            "regimen": estimaciones.regimen.value,
            "por_activo": {
                r.activo: {
                    "observaciones": cov.observaciones_por_activo[r.activo],
                    "volatilidad_anual": cov.volatilidad(r.activo),
                    "retorno_historico_anual": r.media_anual,
                    "intervalo": [r.intervalo_inferior, r.intervalo_superior],
                    "nivel_confianza": r.nivel_confianza,
                }
                for r in estimaciones.retornos_historicos
            },
        }

    # ------------------------------------------------------------ Constructor
    def construir_candidatos(
        self,
        tool_context: ToolContext,
        recomendado: str = "black_litterman",
        peso_max_por_activo: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Optimiza los candidatos de esta iteración (Black-Litterman, HRP, mínima varianza).

        Requiere las estimaciones del Quant y las views del Analista en el estado. Los
        límites son los de la sesión; ``peso_max_por_activo`` solo puede ENDURECER el máximo
        de un activo (p. ej. tras un rechazo del validador por concentración o drawdown) y
        nunca por debajo de su piso. Si el prior de equilibrio está pendiente (falta la
        capitalización de algún activo), Black-Litterman no está disponible: se construyen
        HRP y mínima varianza y la respuesta explica qué falta.

        Args:
            recomendado: candidato que se someterá a validación: "black_litterman", "hrp"
                o "min_varianza".
            peso_max_por_activo: máximos más estrictos por activo, como fracción
                (p. ej. {"VOOG": 0.6}). Omitir para usar los límites de config.yaml.
        """
        try:
            return self._construir_candidatos(
                tool_context.state, recomendado, peso_max_por_activo or {}
            )
        except ERRORES_DE_DOMINIO as exc:
            return _error(exc)

    def _construir_candidatos(
        self, estado: Estado, recomendado: str, peso_max_por_activo: dict[str, float]
    ) -> dict[str, Any]:
        universo = self._universo(estado)
        sesion = self._sesion(estado, universo)
        estimaciones = leer(estado, CLAVE_QUANT_ESTIMATES, QuantEstimates)
        exigir_sello(estimaciones.universe_version, universo.version, "estimaciones del Quant")
        views = leer(estado, CLAVE_MARKET_VIEWS, MarketViews)
        if views.activos != universo.activos:
            raise ValueError(
                f"las views son de otro universo ({list(views.activos)}); el vigente es "
                f"{list(universo.activos)}: vuelve a pedirlas al analista"
            )
        rondas = leer_lista(estado, CLAVE_CANDIDATOS, CandidatePortfolios)
        validadas = leer_lista(estado, CLAVE_VALIDACIONES, ValidationReport)
        for i, previa in enumerate(rondas, start=1):
            exigir_sello(previa.universe_version, universo.version, f"candidatos de la ronda {i}")
        maximo = self.config.validacion.max_iteraciones_constructor
        if len(rondas) > len(validadas):
            raise ValueError(f"la iteración {len(rondas)} aún no se ha validado")
        if len(rondas) >= maximo:
            raise ValueError(f"se alcanzó el máximo de {maximo} iteraciones del constructor")

        restricciones = restricciones_de_iteracion(sesion, peso_max_por_activo)
        opt = self.config.optimizacion
        no_disponibles: dict[TecnicaOptimizacion, str] = {}
        prior: PriorSnapshot | None = None
        candidatos: list[CandidatePortfolio] = []
        try:
            prior = resolver_prior(universo, estimaciones, opt, self.config.prior_equilibrio)
            candidatos.append(
                optimizar_black_litterman(estimaciones, views, restricciones, opt, prior)
            )
        except PriorNoDisponibleError as exc:
            no_disponibles[TecnicaOptimizacion.BLACK_LITTERMAN] = str(exc)
        candidatos += [
            optimizar_hrp(estimaciones, restricciones, opt),
            optimizar_min_varianza(estimaciones, restricciones, opt),
        ]
        avisos: list[str] = []
        if recomendado == NOMBRE_BL and TecnicaOptimizacion.BLACK_LITTERMAN in no_disponibles:
            avisos.append(
                f"se pidió recomendar '{NOMBRE_BL}' pero no está disponible; se recomienda "
                f"'{NOMBRE_HRP}' en su lugar"
            )
            recomendado = NOMBRE_HRP
        if prior is not None and prior.advertencia:
            avisos.append(prior.advertencia)
        ronda = CandidatePortfolios(
            fecha_decision=estimaciones.fecha_decision,
            activos=estimaciones.activos,
            iteracion=len(rondas) + 1,
            candidatos=tuple(candidatos),
            recomendado=recomendado,
            no_disponibles=no_disponibles,
            universe_version=universo.version,
        )
        estado[CLAVE_RESTRICCIONES] = volcar(restricciones)
        estado[CLAVE_PRIOR] = volcar(prior) if prior is not None else None
        agregar(estado, CLAVE_CANDIDATOS, ronda)
        return {
            "status": "success",
            "universe_version": universo.version,
            "iteracion": ronda.iteracion,
            "recomendado": ronda.recomendado,
            "no_disponibles": {t.value: m for t, m in no_disponibles.items()},
            "avisos": avisos,
            "prior": None
            if prior is None
            else {
                "metodo": prior.metodo.value,
                "procedencias": {a: p.value for a, p in prior.procedencias.items()},
                "retornos_implicitos_totales": {a.activo: a.pi_total for a in prior.activos},
            },
            "limites": {a: list(restricciones.limites(a)) for a in restricciones.activos},
            "candidatos": {
                c.nombre: {
                    "pesos": dict(c.pesos),
                    "retorno_esperado_anual": c.metricas.retorno_esperado_anual,
                    "volatilidad_anual": c.metricas.volatilidad_anual,
                    "sharpe": c.metricas.sharpe,
                    "concentracion_hhi": c.metricas.concentracion_hhi,
                }
                for c in candidatos
            },
        }

    # ----------------------------------------------------------------- Riesgo
    def validar_candidato(self, tool_context: ToolContext) -> dict[str, Any]:
        """Valida el candidato recomendado de la última iteración y emite el veredicto.

        Backtest walk-forward con costos, métricas fuera de muestra, stress históricos,
        verificación de look-ahead y criterios de config.yaml. Devuelve el veredicto
        (APROBADA o RECHAZADA), los criterios incumplidos y una sugerencia concreta por cada
        uno. Guarda el reporte completo en el estado.
        """
        try:
            return self._validar_candidato(tool_context.state)
        except ERRORES_DE_DOMINIO as exc:
            return _error(exc)

    def _validar_candidato(self, estado: Estado) -> dict[str, Any]:
        rondas = leer_lista(estado, CLAVE_CANDIDATOS, CandidatePortfolios)
        validadas = leer_lista(estado, CLAVE_VALIDACIONES, ValidationReport)
        if not rondas:
            raise FaltaEnEstadoError(f"falta '{CLAVE_CANDIDATOS}' en el estado: construye antes")
        if len(validadas) >= len(rondas):
            raise ValueError(f"la iteración {len(rondas)} ya fue validada")
        ronda = rondas[-1]
        universo = self._universo(estado)
        exigir_sello(ronda.universe_version, universo.version, "candidatos a validar")
        reporte = self._evaluar(
            estado, universo, ronda.portafolio_recomendado, ronda.fecha_decision, ronda.iteracion
        )
        agregar(estado, CLAVE_VALIDACIONES, reporte)
        m = reporte.metricas_oos
        return {
            "status": "success",
            "iteracion": reporte.iteracion,
            "candidato_evaluado": reporte.candidato_evaluado,
            "veredicto": reporte.veredicto.value,
            "look_ahead_verificado": reporte.look_ahead_verificado,
            "metricas_oos": {
                "sharpe_oos": m.sharpe_oos,
                "retorno_anualizado": m.retorno_anualizado,
                "volatilidad_anualizada": m.volatilidad_anualizada,
                "max_drawdown": m.max_drawdown,
                "turnover_anual": m.turnover_anual,
            },
            "criterios_incumplidos": [c.nombre for c in reporte.criterios if not c.cumple],
            "stress_no_superados": [s.escenario for s in reporte.stress if not s.superado],
            "razones_rechazo": list(reporte.razones_rechazo),
            "sugerencias": list(reporte.sugerencias),
            "advertencias": list(reporte.advertencias),
        }

    # ---------------------------------------------------- Restricciones de sesión
    def ajustar_restricciones(
        self,
        tool_context: ToolContext,
        peso_min: float | None = None,
        peso_max: float | None = None,
        limites_por_activo: dict[str, list[float]] | None = None,
        restablecer: bool = False,
    ) -> dict[str, Any]:
        """Cambia las restricciones de la SESIÓN (piso y techo generales, o por activo).

        Solo con lo que pidió el usuario: lo que no se indique queda como está. Si el pedido
        es infactible (p. ej. los pisos suman más de 100 %), devuelve el error y las vigentes
        no cambian. Los cortos no se pueden habilitar. Las carteras ya construidas no se
        recalculan solas: vuelve a construirlas.

        Args:
            peso_min: piso general por activo, como fracción (0.05 = 5 %).
            peso_max: techo general por activo, como fracción.
            limites_por_activo: excepciones [mínimo, máximo] por activo, p. ej.
                {"IBIT": [0.0, 0.10]}.
            restablecer: true para volver a las de config.yaml (ignora los demás argumentos).
        """
        try:
            return self._ajustar_restricciones(
                tool_context.state, peso_min, peso_max, limites_por_activo or {}, restablecer
            )
        except ERRORES_DE_DOMINIO as exc:
            return _error(exc)

    def _ajustar_restricciones(
        self,
        estado: Estado,
        peso_min: float | None,
        peso_max: float | None,
        limites_por_activo: dict[str, list[float]],
        restablecer: bool,
    ) -> dict[str, Any]:
        universo = self._universo(estado)
        if restablecer:
            nueva = sesion_por_defecto(universo, self.config.optimizacion)
        else:
            if peso_min is None and peso_max is None and not limites_por_activo:
                raise ValueError("nada que ajustar: indica peso_min, peso_max o limites_por_activo")
            mal_formados = sorted(a for a, par in limites_por_activo.items() if len(par) != 2)
            if mal_formados:
                raise ValueError(
                    f"limites_por_activo: se espera [mínimo, máximo] en {mal_formados}"
                )
            nueva = sesion_ajustada(
                self._sesion(estado, universo),
                peso_min,
                peso_max,
                {a: (par[0], par[1]) for a, par in limites_por_activo.items()},
            )
        estado[CLAVE_RESTRICCIONES_SESION] = volcar(nueva)
        return {
            "status": "success",
            "universe_version": universo.version,
            "peso_min": {"valor": nueva.peso_min.valor, "origen": nueva.peso_min.origen.value},
            "peso_max": {"valor": nueva.peso_max.valor, "origen": nueva.peso_max.origen.value},
            "limites_vigentes": {a: list(nueva.limites(a)) for a in nueva.activos},
            "limites_propios": {
                a: {"limites": [x.minimo, x.maximo], "origen": x.origen.value}
                for a, x in nueva.limites_por_activo.items()
            },
            "aviso": "las carteras construidas antes de este cambio no lo reflejan",
        }

    # ------------------------------------------------------- Riesgo, exploratorio
    def diagnosticar_cartera(
        self, pesos: dict[str, float], tool_context: ToolContext
    ) -> dict[str, Any]:
        """Mide una cartera que trae el usuario: diagnóstico EXPLORATORIO, nunca un veredicto.

        Mismas mediciones que el validador del comité (backtest walk-forward con costos,
        métricas fuera de muestra, stress históricos, look-ahead) sobre los pesos indicados y
        el universo vigente. No aprueba ni rechaza: la salida lleva ``etiqueta="diagnostico"``
        y ``validado=false``, y no entra en ningún acta. Los pesos se validan antes de
        calcular: suman 1, sin negativos y solo activos del universo; no se renormalizan.

        Args:
            pesos: peso de cada activo como fracción, p. ej. {"VOOG": 0.5, "BNS": 0.5}. Un
                activo del universo que se omita pesa 0.
        """
        try:
            return self._diagnosticar_cartera(tool_context.state, pesos)
        except ERRORES_DE_DOMINIO as exc:
            return _error(exc)

    def _diagnosticar_cartera(self, estado: Estado, pesos: dict[str, float]) -> dict[str, Any]:
        universo = self._universo(estado)
        validar_pesos_usuario(pesos, universo.activos)  # antes de calcular nada
        if estado.get(CLAVE_QUANT_ESTIMATES) is None:
            self._estimar_mercado(estado)
        estimaciones = leer(estado, CLAVE_QUANT_ESTIMATES, QuantEstimates)
        exigir_sello(estimaciones.universe_version, universo.version, "estimaciones del Quant")
        cartera = cartera_del_usuario(pesos, estimaciones, self.config.optimizacion)
        reporte = self._evaluar(estado, universo, cartera, estimaciones.fecha_decision, 1)
        diagnostico = DiagnosticoCartera.desde_reporte(reporte, cartera.metricas)
        agregar(estado, CLAVE_DIAGNOSTICOS_CARTERA, diagnostico)
        m, x = diagnostico.metricas_oos, diagnostico.metricas_ex_ante
        return {
            "status": "success",
            "etiqueta": diagnostico.etiqueta,
            "validado": diagnostico.validado,
            "universe_version": diagnostico.universe_version,
            "fecha_decision": diagnostico.fecha_decision.isoformat(),
            "pesos_evaluados": dict(diagnostico.pesos_evaluados),
            "look_ahead_verificado": diagnostico.look_ahead_verificado,
            "metricas_ex_ante": {
                "retorno_historico_anual": x.retorno_esperado_anual,
                "volatilidad_anual": x.volatilidad_anual,
                "sharpe": x.sharpe,
                "concentracion_hhi": x.concentracion_hhi,
            },
            "metricas_oos": {
                "periodo": [m.fecha_inicio.isoformat(), m.fecha_fin.isoformat()],
                "sharpe_oos": m.sharpe_oos,
                "retorno_anualizado": m.retorno_anualizado,
                "volatilidad_anualizada": m.volatilidad_anualizada,
                "max_drawdown": m.max_drawdown,
                "turnover_anual": m.turnover_anual,
            },
            "stress": {
                s.escenario: {"retorno_periodo": s.retorno_periodo, "max_drawdown": s.max_drawdown}
                for s in diagnostico.stress
            },
            "umbrales_del_comite_como_referencia": {
                c.nombre: {"valor": c.valor, "umbral": c.umbral, "dentro_del_umbral": c.cumple}
                for c in diagnostico.criterios_de_referencia
            },
            "advertencias": list(diagnostico.advertencias),
        }

    # ------------------------------------------------------------------ Común
    def _evaluar(
        self,
        estado: Estado,
        universo: Universe,
        cartera: CandidatePortfolio,
        fecha: date,
        iteracion: int,
    ) -> ValidationReport:
        """La evaluación del Escéptico: la misma para el comité y para un diagnóstico."""
        sesion = self._sesion(estado, universo)
        # Los criterios peso_min/peso_max se evalúan contra los límites de la SESIÓN.
        optimizacion = self.config.optimizacion.model_copy(
            update={"peso_min": sesion.peso_min.valor, "peso_max": sesion.peso_max.valor}
        )
        return validar(
            cartera,
            self.provider.precios(universo.activos, hasta=fecha),
            fecha_decision=fecha,
            iteracion=iteracion,
            validacion=self.config.validacion,
            optimizacion=optimizacion,
            periodos_por_anio=self.provider.periodos_por_anio,
            semilla=self.config.reproducibilidad.semilla,
            inicio_datos={d.ticker: d.fecha_inicio_datos for d in universo.diagnosticos},
            universe_version=universo.version,
        )

    def _universo(self, estado: Estado) -> Universe:
        """El universo vigente de la sesión: con diagnósticos, nunca una lista de tickers."""
        return leer(estado, CLAVE_UNIVERSO, Universe)

    def _sesion(self, estado: Estado, universo: Universe) -> SessionConstraints:
        """Restricciones de la sesión; si no hay, las de config.yaml sobre este universo."""
        if estado.get(CLAVE_RESTRICCIONES_SESION) is None:
            estado[CLAVE_RESTRICCIONES_SESION] = volcar(
                sesion_por_defecto(universo, self.config.optimizacion)
            )
        sesion = leer(estado, CLAVE_RESTRICCIONES_SESION, SessionConstraints)
        exigir_sello(sesion.universe_version, universo.version, "restricciones de la sesión")
        return sesion

    def _regimen(self, activos: tuple[str, ...]) -> RegimenConfig | None:
        """Sin los activos de referencia en el universo no hay índice: régimen indeterminado."""
        referencia = self.config.regimen.activos_referencia
        return self.config.regimen if set(referencia) <= set(activos) else None

    def _ultimo_cierre(self, activos: tuple[str, ...]) -> date:
        indice = self.provider.precios(activos).index
        ultimo: date = indice[-1].date()
        return ultimo

    def funciones(self) -> tuple[Callable[..., dict[str, Any]], ...]:
        return (self.estimar_mercado, self.construir_candidatos, self.validar_candidato)

    def function_tools(self) -> list[FunctionTool]:
        return [FunctionTool(f) for f in self.funciones()]
