# Sprint 0 — Harness

## Objetivo
Dejar el andamiaje completo y verificable ANTES de escribir el sistema: contratos,
capa de datos, golden test fallando limpiamente, CI verde.

## Alcance
- `pyproject.toml` con uv: google-adk, pydantic v2, pandas, numpy, scipy, pytest, ruff, mypy.
- Contratos Pydantic en `src/investmentsys/contracts/`:
  `MarketViews` (views BL: P absolutos/relativos, Q anual, confianza, justificación y fuente),
  `QuantEstimates` (covarianza por método, régimen, retornos con intervalo),
  `PortfolioConstraints`, `CandidatePortfolios` (pesos, técnica, métricas, sensibilidad),
  `ValidationReport` (métricas OOS, stress, veredicto APROBADA/RECHAZADA con razones),
  `RunState` (estado serializable de una corrida completa).
- `CSVPriceProvider` en `src/investmentsys/data/` implementando la interfaz abstracta
  `PriceProvider`, con tests unitarios (lectura de data/precios.csv, manejo del inicio
  tardío de IBIT, retornos logarítmicos).
- Golden test en `tests/golden/test_black_litterman.py`: escrito completo, fallando por
  `NotImplementedError` (la implementación llega en S1).

## Fuera de alcance
Cualquier lógica de optimización, backtest, agentes o despliegue.

## Entregables
Estructura poblada, contratos aprobados por el usuario, `make check` corriendo en CI,
PR mergeado a main.

## Definition of Done
- `make check` verde en CI (el golden test se marca xfail o skip explícito con razón).
- El golden test falla por NotImplementedError al quitarle el marcador, no por imports.
- Contratos revisados y aprobados explícitamente por el usuario en la sesión.

## Estado
(pendiente — actualizar al cerrar el sprint)
