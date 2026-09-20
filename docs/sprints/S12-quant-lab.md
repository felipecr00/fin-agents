# Sprint 12 — Quant Lab (Doc: Sprint 4 + enmiendas §1 y §3)

> Fuentes: `docs/propuestas/arquitectura_v2.md` y `docs/propuestas/enmienda_v2.md`
> (la enmienda prevalece ante conflicto).
> Reglas globales de los sprints S9-S12:
> - Ningún documento ni código menciona modelos comerciales: los specs hablan de
>   Nivel 1 (Frontier LLM), Nivel 2 (Edge/cuantizado) y Nivel 3 (determinista);
>   la asignación real vive SOLO en config.yaml.
> - Las fronteras existentes son intocables: núcleo puro sin ADK/LLM, contratos
>   sellados con universe_version, custodias en código, cifras jamás por
>   argumentos de LLM. test_fronteras.py se extiende a fintual/ y research_lab/.
> - Todo output operativo lleva el disclaimer: estimación algorítmica, no
>   asesoría tributaria ni financiera.

## Prerrequisito innegociable (PR 0 del sprint)
Migración a DATOS DIARIOS: extender el provider Tiingo a EOD diario,
almacén `data/series_diarias/`, validaciones de S6 aplicadas, y decisión
documentada de qué capa consume qué frecuencia (la capa real puede seguir
mensual; el Lab exige diario). Sin esto, ningún componente del Lab se
implementa.

## PR 1 — Investigación disciplinada
1. `contracts/strategy_spec.py`: StrategySpec declarativo (universe,
   signal_logic, rebalance_frequency, cost_assumptions_bps, risk_limits).
   Ningún código se ejecuta hasta aprobación conceptual del spec.
2. Agente Investigador (Nivel 1): paper-to-spec — produce SOLO StrategySpec.
3. `research_lab/backtester.py`: motor vectorbt estandarizado sobre datos
   diarios; BacktestReport tipado.
4. `research_lab/overfitting_audit.py`: Deflated Sharpe Ratio con REGISTRO
   OBLIGATORIO del número de pruebas (el contador de trials es parte del
   contrato — sin él, el DSR es teatro), más tests de ruido blanco.

## PR 2 — Simulador Gen 1 y Gate de Promoción
5. Simulador Generación 1 (Nivel 3, enmienda §1): block-bootstrap que preserva
   autocorrelación + simulación paramétrica con cópulas empíricas y t-Student
   multivariada de colas pesadas. 10k trayectorias sobre datos diarios.
   Generación 2 (VAEs secuenciales / Normalizing Flows): FUERA DE ALCANCE;
   solo se habilita con evidencia documentada de que la Gen 1 no captura
   asimetrías extremas o cambios de régimen, y siempre sobre el dataset diario.
6. Gate de Promoción Lab → Real (enmienda §3): artefacto `PromotionAct.json`.
   Para que una señal del Lab toque la capa real: el Orquestador inicia la
   fase de promoción → el usuario recibe lógica de la señal + DSR + desempeño
   bajo estrés Gen 1 + solicitud formal → solo con confirmación explícita el
   acta se sella y la señal pasa. Misma familia de custodia que el comité:
   secuencia verificable en herramienta, no booleano, registrado en runs/.
7. Señales NLP (transcripción + clasificador de sentimiento locales, Nivel 2): FUERA DE ALCANCE de S12; queda
   como candidato a S13 con su propio caso de uso demostrado — es un stack de
   infraestructura completo que no debe colarse de polizón.

## Definition of Done
PR 0: series diarias validadas y empalmadas. PR 1: un paper de ejemplo
convertido en StrategySpec, backtesteado con vectorbt y auditado con DSR
(contador de trials en el reporte). PR 2: la estrategia sometida a 10k mundos
Gen 1; un intento de promoción sin confirmación → bloqueado; promoción
confirmada → PromotionAct sellado en runs/. test_fronteras extendido a
research_lab/. make check verde; Estado; PR.

## Estado
(pendiente — actualizar al cerrar el sprint)
