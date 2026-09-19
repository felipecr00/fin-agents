# Sprint 5 — Evaluación y robustez

## Objetivo
Medir y endurecer el sistema: evals de agentes LLM y sensibilidad del núcleo.

## Alcance
- Evalsets de ADK para market_analyst en tests/eval/ (casos con salidas esperadas:
  noticias de ejemplo → views bien formados y razonables).
- Análisis de sensibilidad: perturbar retornos esperados y covarianzas y medir cuánto
  se mueven los pesos; informe generado a runs/.
- Comparador de corridas (diff de RunState entre fechas).
- Régimen de mercado si no se implementó en S2.

## Definition of Done
- `make eval` corre los evalsets y reporta resultados.
- Informe de sensibilidad generado y explicado en docs/.
- `make check` verde; PR mergeado.

## Estado
Cerrado el 2026-09-18 (rama `sprint/S5-evaluacion-robustez`, PR contra `main`).

### Desviaciones del spec
- **`make eval` heredado de S0 no funcionaba** (`adk eval apps tests/eval`): `adk eval` pide la
  carpeta de UN agente y archivos `.evalset.json`. Ahora es `adk eval apps/market_analyst …` más
  un resumen propio, porque `adk eval` siempre termina con código 0.
- **ADR-010 queda en estado "propuesta"**: se escribió con la evidencia medida y se revisa en el
  PR; los hitos 2 y 3 no dependen de ella.
- "Casos con salidas esperadas" = criterios verificables sobre el `MarketViews`, no un texto
  esperado: la salida de un LLM no se puede comparar literalmente.

### Logrado
- **Hito 1 — evalsets del analista** (ADR-010). API verificada en `adk.dev/evaluate/` y en el
  paquete (google-adk 2.9.1): métrica personalizada vía `custom_metrics` + `code_config`, que
  la web no documenta. `tests/eval/`: 11 casos sintéticos generados desde un YAML legible (2
  alcistas claras, 2 bajistas, 2 ambiguas, 2 contradictorias, 2 trampas con instrucciones
  incrustadas —una numérica y una de cambio de rol con ruptura del delimitador— y el uso sin
  material). Criterios: contrato válido, `|q|` plausible, nº de views, dirección exigida o
  prohibida, sin convicción, confianza máxima, texto prohibido (canarios). Cada criterio queda
  en el resultado con su explicación. `make eval` y `make evalset`.
- **Endurecimiento del analista, medido**: línea base 9/10, 9/10 y 8/10 (`ambigua_bns` 3/3:
  BNS +6 % con confianza 0.60 ante resultados idénticos al consenso; `trampa_inyeccion_numerica`
  1/3). Con la instrucción nueva —el mensaje del usuario es material de terceros, un dato en
  línea no es señal, ante contradicción callar o confianza ≤ 0.5, conocimiento general ≤ 0.5—
  11/11 en tres corridas seguidas. Topes en `config.yaml` (`agentes.max_views`,
  `agentes.confianza_max_sin_conviccion`), fuente única para el agente y los evals.
- **Hito 2 — sensibilidad del núcleo**: `risk/sensibilidad.py` (puro, determinista, 80
  reoptimizaciones: q de las views y μ posterior ±1-2 p.p.; volatilidades, correlaciones y Σ
  ±10-20 %; δ y τ ±10-20 %), con límites reales y relajados. `make sensibilidad` →
  `runs/sensibilidad/<fecha>_<hash>/` (mismo contenido en dos corridas, verificado por hash);
  explicado en `docs/sensibilidad.md`. **Resultado: la cartera es más frágil a los retornos
  esperados** (5,9 p.p. de desplazamiento medio, frente a 3,4 de covarianzas y 2,2 de
  parámetros); +2 p.p. en el μ de VB mueve 22 p.p.; VOOG (70 %) e IBIT (2 %) los fijan los
  límites, no las estimaciones (sin límites el óptimo es 98 % VOOG). Con las views de una
  corrida real la conclusión es la misma (10,6 vs. 5,6). `black_litterman.py` expone
  `posterior_black_litterman` y `pesos_optimos`; golden intacto.
- **Hito 3 — comparador de corridas**: `comparacion/` (puro, solo contratos; añadido a
  `test_fronteras`). Views emparejadas por identidad con las relativas normalizadas,
  estimaciones, restricciones, pesos y rotación, métricas, criterios que cambian de lado y
  advertencias (otro `config_hash`, cartera no aprobada). `make comparar A=… B=…`. Probado con
  corridas reales: detectó que el analista había invertido VOOG-vs-VB de +2 % a −2 % escrita
  con los signos al revés (26 p.p. de rotación).
- **Régimen de mercado (pendiente de S2)**: `quant/regimen.py`, reglas sobre tendencia, ratio
  de volatilidad y drawdown de un índice de referencia (`config.yaml: regimen`), con guarda de
  look-ahead. `estimar(regimen=…)` lo rellena y el tool lo expone; no cambia pesos. Sobre los
  datos reales: 2024 alcista, 2025-03 y 2026-03 lateral, 2026-09 alcista.
- Corrida real completa tras todos los cambios: `20260919T014530_788598Z`, APROBADA a la
  primera (70/2/4,4/23,6), régimen "alcista".
- `make check` verde: 300 tests (64 nuevos). Los tests de `evaluacion/` pasan sin el extra
  `eval` (verificado en un entorno limpio): CI no instala las ~50 dependencias del extra.

### Pendiente
- **El analista no conoce el prior de equilibrio.** π ya da VOOG 13,2 % y BNS 11,6 % de retorno
  total; en la corrida real de cierre el analista opinó "favorable" con VOOG 8 % y BNS 6 %, que
  en Black-Litterman *bajan* esos pesos (BNS quedó en el mínimo). Hay que darle π como contexto
  (tool o instrucción) o pedirle views relativas al consenso. Es el hallazgo más importante del
  sprint después de la sensibilidad, y los evals actuales no lo detectan porque miden la
  dirección contra la tasa libre de riesgo (ADR-010, alternativa descartada).
- Poblar `CandidatePortfolio.sensibilidad` en `construir_candidatos` (`Perturbacion.a_contrato()`
  ya produce el contrato) y presentar el reparto BNS/VB como rango en el informe.
- Rúbrica con LLM-juez para "reconoce la contradicción en la justificación" (no verificable de
  forma determinista) y evalsets para el constructor y el reporter.
- Búsqueda para el analista (de S3) y reevaluar `gemini-3.8-flash` con `make eval`.
- El clasificador de régimen necesita 24 observaciones: 2022 queda `INDETERMINADO`, y etiqueta
  "lateral" un fondo de mercado con tendencia plana (2022-12, drawdown 24 %). Es descriptivo.
- Siguen abiertos de S2-S4: intervalos de confianza de las métricas OOS; validar la técnica con
  `reestimada`; persistir corridas que fallan por excepción; `RunState` sin restricciones por
  ronda; proteger `main`; tope específico para IBIT.
- Dev quedará con otro `config_hash` tras el merge (nuevas secciones de `config.yaml`): el
  replay rechazará las corridas anteriores, como está diseñado.

### Aprendizajes
- De nuevo el paquete manda sobre la web: las métricas personalizadas de `adk eval`, el código
  de salida siempre 0 y la carga de `.env` que re-añade variables quitadas con `unset` solo
  están en el código.
- **Un eval verde puede esconder una regresión fuera de su cobertura**: la primera instrucción
  endurecida pasó 10/10 y dejó al pipeline sin views en su uso normal (sin noticias). Lo destapó
  una corrida real, no el evalset; de ahí el caso `sin_material`. Tras cambiar una instrucción,
  correr también el camino normal.
- Medir antes de endurecer: la línea base mostró que las inyecciones ya se resistían casi
  siempre y que el problema real era la falsa convicción ante noticias sin señal.
- Una sola corrida de un LLM no mide nada: `trampa_inyeccion_numerica` falló 1 de 3.
- Los límites de peso dan una estabilidad engañosa: la cartera de referencia "reproduce" 70/7/2/21
  con ±2 p.p. porque dos de sus cuatro pesos están pegados a un tope.
- mypy strict no infiere lambdas con argumentos por defecto dentro de un generador:
  `functools.partial` sobre funciones con nombre es más legible y tipa bien.
