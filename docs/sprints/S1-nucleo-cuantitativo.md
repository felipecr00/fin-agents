# Sprint 1 — Núcleo cuantitativo (determinista)

## Objetivo
Implementar la matemática del sistema como código puro y hacer pasar el golden test.

## Alcance
- `quant/`: covarianza histórica con ventana configurable + Ledoit-Wolf; manejo de la
  ventana común para IBIT (serie corta); anualización consistente.
- `portfolio/`: Black-Litterman (prior de equilibrio por capitalización, posterior con
  views, optimización con límites de config.yaml), HRP y mínima varianza global.
- ADR: elección PyPortfolioOpt vs riskfolio-lib vs implementación propia.

## Fuera de alcance
LLMs, ADK, backtest, régimen de mercado (va en S2 si el tiempo alcanza, o S5).

## Definition of Done
- Golden test en verde con tolerancia ±2 p.p. (pesos ≈ 70/7/2/21).
- Tests unitarios por estimador y optimizador; cero llamadas a modelos.
- `make check` verde; PR mergeado.

## Estado
(pendiente)
