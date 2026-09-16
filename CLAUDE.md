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
delta=2.5, tau=0.05, rf=4%, límites 2%-70% → pesos ≈ VOOG 70%, BNS 7%, IBIT 2%, VB 21%
(tolerancia ±2 p.p.). Si este test se rompe, el núcleo está mal: no lo "ajustes"
para que pase.

## Disclaimer
Herramienta de análisis. Ninguna salida constituye asesoría financiera; todo
reporte generado debe incluir esta advertencia.
