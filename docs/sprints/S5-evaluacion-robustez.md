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
(pendiente)
