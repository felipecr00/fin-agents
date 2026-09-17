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
Cerrado el 2026-09-16 (rama `sprint/S0-harness`, PR contra `main`).

### Logrado
- `pyproject.toml` con uv: google-adk 2.9.1, pydantic 2.13, pandas 3.0, numpy 2.4,
  scipy 1.17; dev con pytest, ruff, mypy strict + plugin pydantic. Python 3.11 fijado.
- Contratos en `contracts/` (aprobados por el usuario en sesión): MarketViews,
  QuantEstimates, PortfolioConstraints, CandidatePortfolios, ValidationReport, RunState.
  Inmutables, con validadores de coherencia y guardas de look-ahead. ADR-001.
- `data/`: `PriceProvider` abstracto y `CSVPriceProvider` con validación del CSV y
  soporte de inicio tardío (IBIT). 19 tests.
- `config.py`: carga tipada de `config.yaml` y hash para reproducibilidad. Se añadieron a
  `config.yaml` las claves que el ejercicio de referencia necesitaba (`metodo_omega`,
  `metodo_covarianza`, `prior_equilibrio`).
- Golden test completo (covarianza, pesos, posterior y métricas) sobre stubs de S1;
  `xfail(raises=NotImplementedError, strict=True)`. Sin marcador falla por
  `NotImplementedError` (verificado). ADR-002.
- `make check` verde en local: 85 tests pasan, 3 xfail. CI actualizado
  (`setup-uv@v6`, `uv sync --locked`).

### Pendiente
- Proteger `main` en GitHub (merge solo vía PR con CI verde): lo configura el usuario.
- S1 debe implementar `quant.estimar_covarianza`, `quant.estimar` y
  `portfolio.optimizar_black_litterman` con las firmas de los stubs y retirar los xfail.
- `nivel_confianza` de los intervalos de `RetornoEsperado` aún no está en `config.yaml`;
  S1 lo añade cuando implemente `estimar`.

### Aprendizajes
- La API de google-adk 2.9.1 importa las clases previstas para S3 (LlmAgent,
  SequentialAgent, ParallelAgent, LoopAgent, FunctionTool); no se usaron en S0, así que
  no hubo diferencias que documentar. Verificar de nuevo al empezar S3.
- El script de referencia tenía números fuera de `config.yaml` (capitalizaciones y el
  método de Ω). Cualquier "ejercicio de referencia" futuro debe revisarse con ese filtro
  antes de codificarlo en un test.
- Homebrew no puede instalar en esta máquina (Xcode 14.2 desactualizado); `uv` se instaló
  con `pip install --user uv` y un enlace en `~/.local/bin`.
- pandas 3.0 cambia detalles (copy-on-write, `freq="ME"`); los tests de `data/` lo cubren.
