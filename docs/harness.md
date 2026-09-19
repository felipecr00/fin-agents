# Harness del Proyecto: Sistema Multi-Agente de Inversiones (Google ADK + GCP)

> Este documento siembra el repositorio. Cada sección indica el archivo destino.
> Orden de creación: primero la estructura y los archivos del harness (Sprint 0),
> luego el desarrollo por sprints. La regla de oro: **la IA nunca trabaja sin un
> sprint activo definido y sin tests que la arbitren.**

---

## 1. Estructura del repositorio

```
inversiones-agentes/
├── CLAUDE.md                     # contexto raíz permanente (sección 2)
├── Makefile                      # bucles de feedback (sección 5)
├── pyproject.toml                # deps: google-adk, pydantic, pandas, scipy, etc.
├── config.yaml                   # parámetros del sistema, cero números mágicos
├── .github/
│   ├── workflows/ci.yaml         # lint + tests en cada PR (sección 6)
│   ├── workflows/deploy.yaml     # despliegue a GCP en merge a main (Sprint 4)
│   └── PULL_REQUEST_TEMPLATE.md
├── docs/
│   ├── adr/                      # Architecture Decision Records (NNN-titulo.md)
│   └── sprints/                  # spec de cada sprint (sección 4)
│       ├── S0-harness.md
│       ├── S1-nucleo-cuantitativo.md
│       ├── S2-validacion-riesgo.md
│       ├── S3-agentes-adk.md
│       ├── S4-despliegue-gcp.md
│       └── S5-evaluacion-robustez.md
├── data/
│   ├── series/<TICKER>.csv       # una serie mensual ajustada por activo (S7)
│   └── universo.json             # universo vigente: diagnósticos y caps congeladas (S7)
├── src/investmentsys/
│   ├── contracts/                # esquemas Pydantic: la columna vertebral
│   ├── data/                     # PriceProvider (CSV primero, mercado después)
│   ├── quant/                    # covarianzas, regímenes (código puro, sin LLM)
│   ├── portfolio/                # BL, HRP, min-var (código puro, sin LLM)
│   ├── risk/                     # backtest walk-forward, stress tests (puro)
│   ├── tools/                    # wrappers FunctionTool de ADK sobre quant/portfolio/risk
│   ├── agents/                   # LlmAgent de ADK: market_analyst, reporter
│   ├── orchestrator/             # composición ADK: Parallel + Sequential + Loop
│   └── app.py                    # entrypoint (adk web local / Agent Engine en prod)
├── tests/
│   ├── golden/                   # tests de regresión con valores del ejercicio BL
│   ├── unit/
│   └── eval/                     # evalsets de ADK para los agentes LLM (S5)
└── runs/                         # rastro auditable de cada corrida (gitignored salvo ejemplos)
```

---

## 2. CLAUDE.md (raíz del repo — contexto permanente de la IA)

```markdown
# Sistema Multi-Agente de Inversiones — Contexto del proyecto

## Qué es
Sistema de análisis y optimización de portafolios con 4 agentes (Analista de Mercados,
Quant, Constructor de Portafolios, Riesgo/Validación) sobre Google ADK, desplegado en GCP.
Portafolio de referencia: VOOG, BNS, IBIT, VB (~US$10.000).

## Flujo de trabajo — OBLIGATORIO
1. Trabaja SOLO en el sprint activo: lee `docs/sprints/<sprint-activo>.md` antes de tocar
   código. Si no hay sprint activo indicado por el usuario, pregunta.
2. Todo cambio va en una rama `sprint/SN-descripcion`, commits convencionales
   (`feat:`, `fix:`, `test:`, `docs:`, `chore:`), y termina en un PR contra `main`.
3. Antes de declarar terminada cualquier tarea: `make check` (lint + tipos + tests)
   debe salir verde. Nunca presentes código sin haberlo ejecutado.
4. Decisiones de arquitectura no triviales → escribe un ADR en `docs/adr/` en el
   mismo PR (formato: contexto, decisión, alternativas descartadas, consecuencias).
5. Al cerrar un sprint: actualiza la sección "Estado" del spec del sprint con lo
   logrado, lo pendiente y los aprendizajes. Ese archivo es la memoria del proyecto.

## Fronteras arquitectónicas — NUNCA violar
- La matemática financiera (covarianzas, optimización, backtest) vive en módulos
  puros (`quant/`, `portfolio/`, `risk/`) SIN dependencia de ADK ni de ningún LLM.
  Los agentes acceden a ella solo vía `tools/` (FunctionTools de ADK).
- Un LlmAgent nunca produce cifras finales: razona, decide qué herramienta llamar
  y redacta. Los números salen de las herramientas.
- Comunicación entre agentes solo con los esquemas Pydantic de `contracts/`.
  Cambiar un contrato requiere: ADR + actualizar todos los consumidores + tests.
- Todo parámetro en `config.yaml`. Ningún número mágico en el código.
- Reproducibilidad: semillas fijas; misma entrada = misma salida en los módulos puros.
- Sin look-ahead bias: ninguna estimación usa datos posteriores a la fecha de
  decisión. Los tests de `risk/` lo verifican explícitamente.

## Stack
Python 3.11+, google-adk (verificar API vigente en https://google.github.io/adk-docs/
antes de usar clases — el release es semanal y la API evoluciona), pydantic v2,
pandas/numpy/scipy, PyPortfolioOpt o riskfolio-lib (decidir vía ADR en S1),
pytest, ruff, mypy. GCP: Cloud Run (dev) → Vertex AI Agent Engine (prod).

## Referencia de calidad
`tests/golden/test_black_litterman.py` codifica el ejercicio de referencia: con
`data/precios.csv`, views {IBIT neutral 3% total, VOOG>VB +3%, BNS 10% total},
δ=2.5, τ=0.05, rf=4%, límites 2%-70% → pesos ≈ VOOG 70%, BNS 7%, IBIT 2%, VB 21%
(tolerancia ±2 p.p.). Si este test se rompe, el núcleo está mal: no lo "ajustes"
para que pase.

## Disclaimer
Herramienta de análisis. Ninguna salida constituye asesoría financiera; todo
reporte generado debe incluir esta advertencia.
```

---

## 3. Mapeo de la arquitectura a primitivas ADK

| Pieza | Primitiva ADK | Nota |
|---|---|---|
| Agente 1: Analista de Mercados | `LlmAgent` + herramienta de búsqueda + `output_schema` (MarketViews) | La salida se valida contra el contrato; si no valida, reintenta |
| Agente 2: Quant | `FunctionTool`s sobre `quant/` invocadas por el orquestador | No necesita LLM: es determinista |
| Agente 3: Constructor | `FunctionTool`s sobre `portfolio/` | Ídem |
| Agente 4: Riesgo/Validación | `FunctionTool`s sobre `risk/` + `LlmAgent` liviano que redacta el veredicto | El veto lo decide código; el LLM solo lo explica |
| Iteración 3↔4 (máx. 2 reintentos) | `LoopAgent` con condición de salida (APROBADA o límite) | |
| [1 ∥ 2] en paralelo | `ParallelAgent` | |
| Pipeline completo | `SequentialAgent` raíz | |
| Reporte final | `LlmAgent` reporter que consume el estado de sesión | |

Verificar nombres exactos de clases contra la documentación vigente de ADK al
implementar (S3) — no asumir de memoria.

---

## 4. Plan de sprints (cada spec vive en docs/sprints/)

Formato de cada spec — la IA lo lee completo antes de empezar:
**Objetivo · Alcance · Fuera de alcance · Entregables · Definition of Done ·
Estado (se actualiza al cerrar)**

### S0 — Harness (este sprint construye el andamiaje, no el sistema)
- Entregables: estructura del repo, CLAUDE.md, Makefile, CI verde en un PR de
  prueba, contratos Pydantic completos (`MarketViews`, `QuantEstimates`,
  `CandidatePortfolios`, `ValidationReport`, `RunState`), `CSVPriceProvider` con
  tests, y el golden test escrito y **fallando** (aún no hay implementación).
- DoD: `make check` corre en CI; el golden test falla por `NotImplementedError`,
  no por errores de importación; PR mergeado a main.

### S1 — Núcleo cuantitativo (determinista)
- Entregables: `quant/` (covarianza histórica + Ledoit-Wolf, ventana común para
  IBIT), `portfolio/` (Black-Litterman, HRP, mínima varianza), ADR de la librería
  elegida.
- DoD: golden test en verde; tests unitarios de cada estimador; cero llamadas LLM.

### S2 — Validación y riesgo
- Entregables: `risk/` con backtest walk-forward (rebalanceo y costos
  configurables), stress tests (2020, 2022, corrección cripto 2025-26), métricas
  (Sharpe OOS, max drawdown, turnover), veredicto con umbrales de `config.yaml`.
- DoD: test que demuestra detección de look-ahead bias inyectado a propósito;
  el validador rechaza una cartera diseñada para violar umbrales.

### S3 — Agentes ADK y orquestación
- Entregables: `tools/` (FunctionTools), `agents/` (market_analyst con
  output_schema, reporter), `orchestrator/` (Sequential/Parallel/Loop), corrida
  end-to-end local con `adk web`, escritura de `RunState` en `runs/`.
- DoD: una corrida completa local produce el reporte Markdown con cartera
  aprobada por el validador; los views del LLM validan contra el contrato.

### S4 — Despliegue GCP
- Entregables: contenedor + despliegue a Cloud Run (entorno dev),
  despliegue a Vertex AI Agent Engine (prod) con sesiones administradas,
  `deploy.yaml` en GitHub Actions con Workload Identity Federation (sin llaves
  de servicio en el repo), secretos vía Secret Manager.
- DoD: merge a main despliega automáticamente a dev; promoción manual a prod;
  una corrida remota reproduce el resultado local.

### S5 — Evaluación y robustez
- Entregables: evalsets de ADK para el analista de mercados (casos con salidas
  esperadas), análisis de sensibilidad de pesos a perturbaciones de inputs,
  comparador de corridas en `runs/`, documentación de operación.
- DoD: `make eval` corre los evalsets; informe de sensibilidad generado.

---

## 5. Makefile (bucles de feedback de un solo comando)

```makefile
.PHONY: install lint type test check run-local eval clean

install:        ## dependencias con uv
	uv sync

lint:
	uv run ruff check src tests && uv run ruff format --check src tests

type:
	uv run mypy src

test:
	uv run pytest tests/unit tests/golden -q

check: lint type test   ## puerta obligatoria antes de todo commit final

run-local:      ## UI de desarrollo de ADK
	uv run adk web src/investmentsys

eval:           ## evalset del analista contra Gemini real (S5, ADR-010); ver el Makefile
	uv run --group eval adk eval apps/market_analyst tests/eval/market_analyst.evalset.json \
		--config_file_path tests/eval/test_config.json

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
```

---

## 6. CI — .github/workflows/ci.yaml

```yaml
name: ci
on:
  pull_request:
  push:
    branches: [main]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv python install 3.11
      - run: uv sync
      - run: make lint
      - run: make type
      - run: make test
```

Regla de repositorio (configurar en GitHub): `main` protegida, merge solo vía PR
con CI verde. Así la IA físicamente no puede integrar código roto.

`PULL_REQUEST_TEMPLATE.md`:
```markdown
## Sprint
<!-- SN — nombre -->
## Qué cambia
## Cómo se verificó
<!-- salida de make check, corridas relevantes -->
## ADRs nuevos o afectados
## Checklist
- [ ] make check verde localmente
- [ ] Spec del sprint actualizado si cerró alcance
- [ ] Sin números mágicos nuevos fuera de config.yaml
```

---

## 7. Prompt de arranque para Claude Code (primera sesión, Sprint 0)

> Lee CLAUDE.md completo. El sprint activo es S0 (docs/sprints/S0-harness.md).
> Ejecuta el Sprint 0 en este orden: (1) estructura de carpetas y pyproject con
> uv; (2) contratos Pydantic — muéstramelos y espera mi aprobación antes de
> seguir, son la columna vertebral; (3) CSVPriceProvider + tests; (4) golden test
> escrito y fallando limpiamente; (5) Makefile y CI; (6) abre el PR. No avances a
> S1 bajo ninguna circunstancia. Si la API de google-adk difiere de lo que
> esperas, consulta https://google.github.io/adk-docs/ y documenta la diferencia.

---

## 8. Principios del harness (por qué está diseñado así)

1. **Specs por sprint = contexto acotado.** La IA rinde mejor con un objetivo
   estrecho y criterios de cierre explícitos que con el proyecto entero en la
   cabeza. El archivo del sprint es el único backlog que necesita.
2. **Tests antes que implementación.** El golden test convierte "optimiza bien"
   en una afirmación verificable. La IA puede refactorizar con agresividad
   porque hay un árbitro.
3. **CI como barrera física.** No es una convención social: main protegida hace
   imposible integrar sin verificación.
4. **ADRs como memoria.** Las conversaciones se pierden; los ADRs no. Cada
   decisión no obvia queda escrita con sus alternativas descartadas, y las
   sesiones futuras de la IA las leen en segundos.
5. **Determinismo donde importa.** Separar núcleo puro de capa agéntica hace que
   el 80% del sistema sea testeable sin tokens, rápido y barato de iterar.
6. **Estado de sprint actualizado al cerrar.** Es el traspaso entre sesiones de
   IA: la próxima sesión arranca leyendo dónde quedó todo, sin reconstruir
   contexto desde el historial de chat.
```
