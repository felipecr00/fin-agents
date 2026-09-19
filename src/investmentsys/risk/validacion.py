"""Veredicto del agente de Riesgo sobre un candidato. Código puro: el LLM solo lo redacta.

``validar`` encadena verificación de look-ahead, backtest walk-forward, métricas OOS,
stress histórico y criterios contra ``config.yaml``; devuelve un ``ValidationReport`` cuyo
veredicto es APROBADA solo si todo se cumple (el contrato lo revalida).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import pandas as pd

from investmentsys.config import OptimizacionConfig, ValidacionConfig
from investmentsys.contracts import (
    CandidatePortfolio,
    Criterio,
    MetricasOOS,
    ResultadoStress,
    ValidationReport,
    Veredicto,
)
from investmentsys.contracts.common import TOLERANCIA_NUMERICA
from investmentsys.quant import LookAheadError
from investmentsys.risk.backtest import Estrategia, ResultadoBacktest, backtest_walk_forward
from investmentsys.risk.cobertura import advertencias_de_validacion
from investmentsys.risk.estrategias import pesos_fijos
from investmentsys.risk.look_ahead import LookAheadDetectadoError, verificar_look_ahead
from investmentsys.risk.metricas import concentracion_hhi, drawdown_por_activo, metricas_oos
from investmentsys.risk.stress import stress_historico


def validar(
    candidato: CandidatePortfolio,
    precios: pd.DataFrame,
    *,
    fecha_decision: date,
    iteracion: int,
    validacion: ValidacionConfig,
    optimizacion: OptimizacionConfig,
    periodos_por_anio: int,
    semilla: int,
    estrategia: Estrategia | None = None,
    fecha_inicio_oos: date | None = None,
    inicio_datos: Mapping[str, date] | None = None,
    universe_version: str | None = None,
) -> ValidationReport:
    """Evalúa ``candidato`` con precios hasta ``fecha_decision`` y emite el veredicto.

    - ``estrategia`` (por defecto, los pesos fijos del candidato) es lo que se simula en el
      backtest walk-forward; el stress siempre usa los pesos propuestos.
    - ``precios`` no puede contener filas posteriores a ``fecha_decision``: eso es un error
      del que llama (``LookAheadError``), no una propiedad del candidato.
    - ``inicio_datos`` (primer precio de cada activo, del ``Universe``) activa la degradación
      explícita por historia corta: ``advertencias`` dice qué ventana mide a cada activo.
    - Un look-ahead detectado en la estrategia no interrumpe: se registra
      ``look_ahead_verificado=False`` y el veredicto es RECHAZADA con la evidencia.
    """
    indice = pd.DatetimeIndex(precios.index)
    if (indice > pd.Timestamp(fecha_decision)).any():
        raise LookAheadError(
            f"look-ahead: hay precios hasta {indice.max().date()}, posteriores a la fecha de "
            f"decisión {fecha_decision}"
        )
    faltan = sorted(set(candidato.pesos) - {str(c) for c in precios.columns})
    if faltan:
        raise ValueError(f"el panel de precios no tiene los activos del candidato: {faltan}")
    estrategia = estrategia if estrategia is not None else pesos_fijos(candidato.pesos)

    fechas = indice[indice >= pd.Timestamp(fecha_inicio_oos)] if fecha_inicio_oos else indice
    look_ahead_detalle: str | None = None
    try:
        verificar_look_ahead(estrategia, precios, (f.date() for f in fechas[:-1]), semilla=semilla)
    except LookAheadDetectadoError as exc:
        look_ahead_detalle = str(exc)

    resultado = backtest_walk_forward(
        precios,
        estrategia,
        costo_transaccion_bps=validacion.costo_transaccion_bps,
        rebalanceo=validacion.rebalanceo,
        fecha_inicio=fecha_inicio_oos,
        fecha_fin=fecha_decision,
    )
    metricas = metricas_oos(
        resultado,
        periodos_por_anio=periodos_por_anio,
        tasa_libre_riesgo=optimizacion.tasa_libre_riesgo,
    )
    stress = stress_historico(
        candidato.pesos,
        precios,
        validacion.escenarios_stress,
        fecha_decision=fecha_decision,
        max_drawdown_tolerado=validacion.max_drawdown_tolerado,
        costo_transaccion_bps=validacion.costo_transaccion_bps,
        rebalanceo=validacion.rebalanceo,
    )
    criterios = _criterios(candidato, resultado, metricas, validacion, optimizacion)
    sugerencias = _sugerencias(candidato, precios, resultado, criterios, stress, look_ahead_detalle)
    aprobada = (
        look_ahead_detalle is None
        and all(c.cumple for c in criterios)
        and all(s.superado for s in stress)
    )
    return ValidationReport(
        fecha_decision=fecha_decision,
        iteracion=iteracion,
        candidato_evaluado=candidato.nombre,
        pesos_evaluados=dict(candidato.pesos),
        metricas_oos=metricas,
        stress=stress,
        criterios=criterios,
        look_ahead_verificado=look_ahead_detalle is None,
        veredicto=Veredicto.APROBADA if aprobada else Veredicto.RECHAZADA,
        sugerencias=sugerencias,
        advertencias=advertencias_de_validacion(
            inicio_datos,
            candidato.pesos,
            metricas.fecha_inicio,
            validacion.escenarios_stress,
            fecha_decision,
        )
        if inicio_datos is not None
        else (),
        universe_version=universe_version,
    )


def _criterios(
    candidato: CandidatePortfolio,
    resultado: ResultadoBacktest,
    metricas: MetricasOOS,
    validacion: ValidacionConfig,
    optimizacion: OptimizacionConfig,
) -> tuple[Criterio, ...]:
    tol = TOLERANCIA_NUMERICA
    hhi = float(sum(p * p for p in candidato.pesos.values()))
    hhi_aplicado, fecha_hhi = concentracion_hhi(resultado.pesos)
    activo_max, peso_max = max(candidato.pesos.items(), key=lambda kv: kv[1])
    activo_min, peso_min = min(candidato.pesos.items(), key=lambda kv: kv[1])
    sharpe, caida, turnover = metricas.sharpe_oos, metricas.max_drawdown, metricas.turnover_anual
    return (
        Criterio(
            nombre="sharpe_oos_minimo",
            valor=sharpe,
            umbral=validacion.sharpe_oos_minimo,
            cumple=sharpe >= validacion.sharpe_oos_minimo - tol,
            detalle=f"Sharpe OOS sobre {resultado.n_periodos} períodos",
        ),
        Criterio(
            nombre="max_drawdown_tolerado",
            valor=caida,
            umbral=validacion.max_drawdown_tolerado,
            cumple=caida <= validacion.max_drawdown_tolerado + tol,
            detalle="caída máxima del capital neto de costos en el backtest",
        ),
        Criterio(
            nombre="turnover_maximo_anual",
            valor=turnover,
            umbral=validacion.turnover_maximo_anual,
            cumple=turnover <= validacion.turnover_maximo_anual + tol,
            detalle=f"Σ|Δw| anualizado con rebalanceo {validacion.rebalanceo}",
        ),
        Criterio(
            nombre="concentracion_hhi_maxima",
            valor=hhi,
            umbral=validacion.concentracion_hhi_maxima,
            cumple=hhi <= validacion.concentracion_hhi_maxima + tol,
            detalle=(
                f"HHI de los pesos propuestos; máximo aplicado en el backtest "
                f"{hhi_aplicado:.4f} ({fecha_hhi.date()})"
            ),
        ),
        Criterio(
            nombre="peso_max",
            valor=peso_max,
            umbral=optimizacion.peso_max,
            cumple=peso_max <= optimizacion.peso_max + tol,
            detalle=f"mayor peso propuesto: {activo_max}",
        ),
        Criterio(
            nombre="peso_min",
            valor=peso_min,
            umbral=optimizacion.peso_min,
            cumple=peso_min >= optimizacion.peso_min - tol,
            detalle=f"menor peso propuesto: {activo_min}",
        ),
    )


def _sugerencias(
    candidato: CandidatePortfolio,
    precios: pd.DataFrame,
    resultado: ResultadoBacktest,
    criterios: tuple[Criterio, ...],
    stress: tuple[ResultadoStress, ...],
    look_ahead_detalle: str | None,
) -> tuple[str, ...]:
    """Una indicación concreta al Constructor por cada criterio incumplido."""
    sugerencias: list[str] = []
    if look_ahead_detalle is not None:
        sugerencias.append(f"corregir la estrategia: {look_ahead_detalle}")
    ventana = precios.loc[resultado.valor.index, list(candidato.pesos)]
    caidas = drawdown_por_activo(ventana)
    peor = max(candidato.pesos, key=lambda a: candidato.pesos[a] * caidas[a])
    activo_max = max(candidato.pesos, key=lambda a: candidato.pesos[a])
    activo_min = min(candidato.pesos, key=lambda a: candidato.pesos[a])
    textos = {
        "sharpe_oos_minimo": "Sharpe OOS {valor:.2f} < {umbral}: revisar retornos esperados o "
        "reducir volatilidad (mayor caída propia ponderada: " + peor + ")",
        "max_drawdown_tolerado": "drawdown {valor:.1%} > {umbral:.0%}: reducir el peso de "
        + f"{peor} (caída propia {caidas[peor]:.0%})",
        "turnover_maximo_anual": "turnover {valor:.2f}/año > {umbral}: suavizar los cambios "
        "de pesos entre decisiones",
        "concentracion_hhi_maxima": "HHI {valor:.3f} > {umbral}: repartir el peso de "
        + f"{activo_max} ({candidato.pesos[activo_max]:.1%})",
        "peso_max": f"{activo_max}" + "={valor:.2%} supera peso_max={umbral}",
        "peso_min": f"{activo_min}" + "={valor:.2%} está por debajo de peso_min={umbral}",
    }
    sugerencias += [
        textos[c.nombre].format(valor=c.valor, umbral=c.umbral) for c in criterios if not c.cumple
    ]
    for s in stress:
        if not s.superado:
            tramo = precios.loc[
                (pd.DatetimeIndex(precios.index) >= pd.Timestamp(s.fecha_inicio))
                & (pd.DatetimeIndex(precios.index) <= pd.Timestamp(s.fecha_fin)),
                list(candidato.pesos),
            ]
            caidas_tramo = drawdown_por_activo(tramo)
            culpable = max(candidato.pesos, key=lambda a: candidato.pesos[a] * caidas_tramo[a])
            sugerencias.append(
                f"stress {s.escenario}: drawdown {s.max_drawdown:.1%} no tolerado; reducir "
                f"{culpable} (caída propia {caidas_tramo[culpable]:.0%} en el escenario)"
            )
    return tuple(sugerencias)
