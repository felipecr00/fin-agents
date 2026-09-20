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
Cerrado el 2026-09-17 (rama `sprint/S3-agentes-adk`, PR contra `main`).

### Desviaciones del spec (aprobadas en sesión)
- **`Workflow` en lugar de `SequentialAgent`/`ParallelAgent`/`LoopAgent`**: en google-adk
  2.9.1 los tres están `@deprecated`. Misma topología, otra clase (ADR-005, ADR-007).
- **`output_schema=MarketViewsBorrador`, no `MarketViews`**: google-genai rechaza el contrato
  (`exclusiveMinimum`, `patternProperties`) y la API de AI Studio rechaza `additionalProperties`.
  El LLM emite un borrador y el código construye y valida el contrato (ADR-006).

### Logrado
- ADR-005: `google-adk==2.9.1` fijo, el modelo de Nivel 1 con id fijo en `config.yaml`
  (`agentes.*`), credenciales solo por entorno/`.env` (`.env.example`).
- `tools/`: `NucleoTools` con `estimar_mercado`, `construir_candidatos(recomendado,
  peso_max_por_activo)` y `validar_candidato`. Contratos por el estado de sesión, errores de
  dominio como `status=error`, los máximos solo se pueden endurecer.
- `agents/market_analyst`: `LlmAgent` + envoltorio `BaseAgent` que valida contra
  `MarketViews` y reintenta con el error en la instrucción (`agentes.max_intentos_analista`).
  Fallos del modelo (credenciales, red) no se reintentan.
- `agents/constructor` (LLM con tool), `agents/reporter` (narrativa por LLM; tablas y cifras
  por código, con delator de cifras no verificadas).
- `orchestrator/`: `Workflow` iniciar → [analista ∥ quant] → constructor ⇄ validador →
  reporter → cerrar; `RunState` + `reporte.md` en `runs/<run_id>/`.
- `apps/` para `adk web` (`market_analyst`, `pipeline`); `make run-local` apunta ahí y el
  Makefile encuentra `uv` aunque no esté en el PATH. `scripts/probar_analista.py` y
  `scripts/run_pipeline.py` para corridas reales por CLI.
- Tests: 220 (44 nuevos). `tests/integration` usa LLM falsos sobre el `Runner` real de ADK y
  entra en `make test`/CI: reintento del analista (5 tipos de salida inválida), corrida
  aprobada a la primera con los pesos del golden, rechazo → segunda iteración aprobada,
  iteraciones agotadas → informe sin cartera, red de seguridad del constructor. Además
  `test_fronteras.py`: el núcleo puro no importa ADK ni capas de agentes.
- DoD: dos corridas reales completas con el modelo de Nivel 1 (documentadas en el PR): una
  aprobada a la primera (70/2/5/23) y otra, vía `adk web`, rechazada por HHI en la
  iteración 1 y aprobada en la 2 tras bajar el constructor el máximo de VOOG a 50 %.

### Pendiente
- S4: comprobar que Agent Engine despliega un `Workflow` raíz (plan B: workflow agents
  clásicos, ejercidos en el spike de ADR-005). Persistir corridas que fallan por excepción.
- S5: búsqueda para el analista (hoy `fuente` = "conocimiento general del modelo, sin
  verificar"); reevaluar la versión siguiente del modelo de Nivel 1 con evalsets; validar la técnica con `reestimada`.
- A decidir por el usuario: con los umbrales actuales el validador APRUEBA una cartera con
  62 % en IBIT (view IBIT +90 %): HHI 0.50 < 0.55 y drawdown < 35 % porque IBIT solo cotiza
  desde 2024 (limitación ya anotada en S2). Un tope específico para IBIT o un HHI más
  estricto lo evitaría.

### Aprendizajes
- Verificar la API en el paquete instalado, no solo en la web: la deprecación de los workflow
  agents solo aparecía en el código.
- El conversor local de google-genai no es la última palabra: `additionalProperties` pasó en
  local y dio 400 en la API. Solo la corrida real lo destapó.
- Probar sin credenciales también encuentra bugs: el `except ValueError` del analista se
  tragaba el "No API key" y lo reintentaba como salida inválida.
- Un LLM inventa lo que el esquema le deja inventar (fechas de fuente): mejor pedir `null`
  explícito y dejar fuera del esquema lo que no debe decidir (fecha de decisión, universo).
- `data/precios.csv` termina en 2026-09-30, posterior a la fecha real de las corridas
  (2026-09-17): es el dato de referencia, pero conviene saberlo al leer los informes.
