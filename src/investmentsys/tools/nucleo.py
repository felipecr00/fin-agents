"""FunctionTools de ADK sobre el núcleo puro (``quant/``, ``portfolio/``, ``risk/``).

Reglas (CLAUDE.md):
- Aquí no hay matemática: cada tool lee contratos del estado de sesión, llama a una función
  pura y escribe el contrato resultante. Las cifras salen del núcleo, nunca del LLM.
- Los argumentos que decide un LLM son pocos y pequeños (qué candidato recomendar, qué
  límite endurecer); los contratos grandes viajan por el estado (ver ``estado.py``).
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

from investmentsys.config import Config
from investmentsys.contracts import (
    CandidatePortfolio,
    CandidatePortfolios,
    MarketViews,
    PortfolioConstraints,
    QuantEstimates,
    ValidationReport,
)
from investmentsys.data import PriceProvider
from investmentsys.portfolio import (
    OptimizacionFallidaError,
    optimizar_black_litterman,
    optimizar_hrp,
    optimizar_min_varianza,
)
from investmentsys.quant import LookAheadError, MuestraInsuficienteError, estimar
from investmentsys.risk import validar
from investmentsys.tools.estado import (
    CLAVE_CANDIDATOS,
    CLAVE_FECHA_DECISION,
    CLAVE_MARKET_VIEWS,
    CLAVE_QUANT_ESTIMATES,
    CLAVE_RESTRICCIONES,
    CLAVE_VALIDACIONES,
    Estado,
    FaltaEnEstadoError,
    agregar,
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
        activos = self.config.portafolio.activos
        fecha = leer_fecha(estado) or self._ultimo_cierre()
        estimaciones = estimar(
            self.provider.retornos_log(activos, hasta=fecha),
            fecha_decision=fecha,
            periodos_por_anio=self.provider.periodos_por_anio,
            ventana_meses=self.config.datos.ventana_covarianza_meses,
            metodos=(self.config.optimizacion.metodo_covarianza,),
            nivel_confianza=self.config.estimacion.nivel_confianza,
            regimen=self.config.regimen,
        )
        estado[CLAVE_FECHA_DECISION] = fecha.isoformat()
        estado[CLAVE_QUANT_ESTIMATES] = volcar(estimaciones)
        cov = estimaciones.covarianza(self.config.optimizacion.metodo_covarianza)
        return {
            "status": "success",
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
        límites salen de config.yaml; ``peso_max_por_activo`` solo puede ENDURECER el máximo
        de un activo (p. ej. tras un rechazo del validador por concentración o drawdown).

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
        estimaciones = leer(estado, CLAVE_QUANT_ESTIMATES, QuantEstimates)
        views = leer(estado, CLAVE_MARKET_VIEWS, MarketViews)
        rondas = leer_lista(estado, CLAVE_CANDIDATOS, CandidatePortfolios)
        validadas = leer_lista(estado, CLAVE_VALIDACIONES, ValidationReport)
        maximo = self.config.validacion.max_iteraciones_constructor
        if len(rondas) > len(validadas):
            raise ValueError(f"la iteración {len(rondas)} aún no se ha validado")
        if len(rondas) >= maximo:
            raise ValueError(f"se alcanzó el máximo de {maximo} iteraciones del constructor")

        restricciones = self._restricciones(peso_max_por_activo)
        opt = self.config.optimizacion
        candidatos: tuple[CandidatePortfolio, ...] = (
            optimizar_black_litterman(
                estimaciones, views, restricciones, opt, self.config.prior_equilibrio
            ),
            optimizar_hrp(estimaciones, restricciones, opt),
            optimizar_min_varianza(estimaciones, restricciones, opt),
        )
        ronda = CandidatePortfolios(
            fecha_decision=estimaciones.fecha_decision,
            activos=estimaciones.activos,
            iteracion=len(rondas) + 1,
            candidatos=candidatos,
            recomendado=recomendado,
        )
        estado[CLAVE_RESTRICCIONES] = volcar(restricciones)
        agregar(estado, CLAVE_CANDIDATOS, ronda)
        return {
            "status": "success",
            "iteracion": ronda.iteracion,
            "recomendado": ronda.recomendado,
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

    def _restricciones(self, peso_max_por_activo: dict[str, float]) -> PortfolioConstraints:
        opt = self.config.optimizacion
        relajados = {a: m for a, m in peso_max_por_activo.items() if m > opt.peso_max}
        if relajados:
            raise ValueError(
                f"peso_max_por_activo solo puede endurecer peso_max={opt.peso_max}: {relajados}"
            )
        return PortfolioConstraints(
            activos=self.config.portafolio.activos,
            peso_min=opt.peso_min,
            peso_max=opt.peso_max,
            permitir_cortos=opt.permitir_cortos,
            limites_por_activo={a: (opt.peso_min, m) for a, m in peso_max_por_activo.items()},
        )

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
        reporte = validar(
            ronda.portafolio_recomendado,
            self.provider.precios(ronda.activos, hasta=ronda.fecha_decision),
            fecha_decision=ronda.fecha_decision,
            iteracion=ronda.iteracion,
            validacion=self.config.validacion,
            optimizacion=self.config.optimizacion,
            periodos_por_anio=self.provider.periodos_por_anio,
            semilla=self.config.reproducibilidad.semilla,
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
        }

    # ------------------------------------------------------------------ Común
    def _ultimo_cierre(self) -> date:
        indice = self.provider.precios(self.config.portafolio.activos).index
        ultimo: date = indice[-1].date()
        return ultimo

    def funciones(self) -> tuple[Callable[..., dict[str, Any]], ...]:
        return (self.estimar_mercado, self.construir_candidatos, self.validar_candidato)

    def function_tools(self) -> list[FunctionTool]:
        return [FunctionTool(f) for f in self.funciones()]
