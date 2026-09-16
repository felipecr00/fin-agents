# Sprint 3 — Agentes ADK y orquestación

## Objetivo
Pipeline completo corriendo end-to-end en local con `adk web`.

## Alcance
- `tools/`: FunctionTools de ADK envolviendo quant/, portfolio/ y risk/.
- `agents/`: market_analyst (LlmAgent con output_schema=MarketViews; si la salida no
  valida contra el contrato, reintenta) y reporter (redacta el informe final desde RunState).
- `orchestrator/`: ParallelAgent [analista ∥ quant] → constructor → LoopAgent con el
  validador (máx. 2 iteraciones, corta en APROBADA) → reporter. SequentialAgent raíz.
- Escritura de RunState y reporte Markdown en runs/<timestamp>/.
- Verificar la API vigente de ADK en https://google.github.io/adk-docs/ antes de codificar.

## Definition of Done
- Una corrida local completa produce reporte con cartera aprobada por el validador.
- Los views del LLM validan contra MarketViews (test de integración con LLM mockeado
  para CI; corrida real documentada en el PR).
- `make check` verde; PR mergeado.

## Estado
(pendiente)
