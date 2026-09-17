# ADR 005: Versión de google-adk, modelo Gemini y API de orquestación

- Fecha: 2026-09-17
- Sprint: S3
- Estado: propuesta (pendiente de aprobación del usuario en el checkpoint del hito 1)

## Contexto
S3 introduce ADK. El release es semanal y la API cambia, así que se verificó el 2026-09-17
contra la documentación oficial (`google.github.io/adk-docs` redirige con 301 a `adk.dev`) y
contra el paquete instalado (`uv.lock`: google-adk 2.9.1, última versión en PyPI;
google-genai 2.24.0):

| Pieza | Nombre real verificado |
|---|---|
| Agente LLM | `google.adk.agents.LlmAgent` (`Agent` es alias). Campos usados: `model`, `instruction`, `tools`, `output_schema`, `output_key`, `include_contents`, `generate_content_config`, `retry_config`, callbacks `before/after_model`, `on_model_error`. |
| Agente a medida | `google.adk.agents.BaseAgent` con `_run_async_impl(ctx: InvocationContext)`. |
| Workflow agents | `SequentialAgent`, `ParallelAgent`, `LoopAgent(max_iterations=…)`; el bucle se corta con `EventActions(escalate=True)`. **Los tres están marcados `@deprecated` en 2.9.1** ("in favor of Workflow and will be removed in a future version"). La documentación web todavía no lo menciona. |
| Grafo | `google.adk.workflow.Workflow(edges=[…])`, `JoinNode`, `START`, rutas con `Event(route=…)`, `RetryConfig`. Nodos: agentes, funciones `(ctx: Context)` o workflows. Los ciclos **no** se acotan solos. |
| Function tools | Función Python con type hints y docstring, envuelta por `google.adk.tools.function_tool.FunctionTool`; `ToolContext` (alias de `google.adk.agents.context.Context`) se inyecta por anotación y da acceso a `state` y `actions`. Retorno preferido: `dict` con `status`. |
| `output_schema` + `tools` | Solo nativo en Gemini vía Vertex (`gemini_output_schema_and_tools`); con API key ADK cae a un tool `set_model_response` "que puede no ser fiable". |
| Autenticación | Variables de entorno: `GOOGLE_API_KEY` (Gemini API) o `GOOGLE_CLOUD_PROJECT` + `GOOGLE_CLOUD_LOCATION` + `GOOGLE_GENAI_USE_ENTERPRISE=True` (Google Cloud; 2.9.1 aún acepta `GOOGLE_GENAI_USE_VERTEXAI`). |

Modelos Gemini de texto estables hoy (página de modelos y changelog de la Gemini API):
`gemini-3.8-flash` (GA 2026-09-02), `3.7-flash`, `3.6-flash`, `3.5-flash`, `3.5-flash-lite`,
`2.5-flash`, `2.5-pro`. El único Pro de la serie 3 es `gemini-3.1-pro-preview` (preview).
`gemini-2.0-flash` está apagado.

Spike (fuera del repo, LLM falso, 2.9.1): la topología de S3
`[analista ∥ quant] → constructor ⇄ validador (máx. 2) → reporter` se ejecutó con ambas
APIs y dejó el mismo estado final. La versión clásica emite 3 `DeprecationWarning` y obliga
a escribir un `BaseAgent` por cada paso determinista; con `Workflow` los pasos deterministas
son funciones `(ctx)` y no hay avisos.

## Decisión
1. **Versión**: fijar `google-adk==2.9.1` en `pyproject.toml` (hoy `>=2.9,<3`). Subir de
   versión es un cambio deliberado con su PR, no un efecto de `uv lock`.
2. **Modelo**: `gemini-3.5-flash`, como id fijo en `config.yaml` (`agentes.modelo`), nunca
   un alias `-latest`.
3. **Orquestación**: construir el orquestador con `Workflow` en lugar de
   `SequentialAgent`/`ParallelAgent`/`LoopAgent`. El tope de iteraciones
   (`validacion.max_iteraciones_constructor`) lo aplica el router del validador y, como
   segunda barrera, el tool `construir_candidatos`.
4. El `market_analyst` no lleva `tools` en S3: `output_schema=MarketViews` sin tools es el
   camino nativo con API key y con Vertex.

Justificación del modelo: el LLM no produce cifras (CLAUDE.md); sus tareas son emitir un
JSON que valide contra `MarketViews` y redactar el informe, trabajo de gama Flash. Dentro de
Flash, 3.5 es el `DEFAULT_MODEL` de ADK 2.9.1 —la combinación que el framework prueba—,
es GA y tiene id fijo, requisito de reproducibilidad y de los endpoints regionales de S4
(donde el alias `-latest` "may not work").

## Alternativas descartadas
- **`gemini-3.8-flash`**: más nuevo, pero con 15 días en GA y sin referencias en ADK 2.9.1.
  Cambiarlo es una línea de `config.yaml`; se reevalúa en S5 con evalsets.
- **`gemini-3.1-pro-preview` / `gemini-2.5-pro`**: un preview no se fija en un sistema
  reproducible; 2.5-pro es una generación anterior y más caro para una tarea que no lo pide.
- **`gemini-flash-latest`**: el modelo cambiaría sin que cambie el repo.
- **Workflow agents clásicos** (lo que dice literalmente el spec de S3): funcionan hoy, pero
  nacerían deprecados y habría que migrarlos antes de S4. Se mantiene la topología del spec;
  cambia la clase que la ejecuta.
- **Rango `>=2.9,<3`**: con release semanal, una deprecación como esta puede convertirse en
  eliminación dentro del mismo major.

## Consecuencias
- El spec de S3 nombra clases deprecadas; su sección Estado documentará la sustitución.
- `Workflow` "cannot yet be used as an LlmAgent sub-agent": no nos afecta (es la raíz).
- Riesgos a verificar en los hitos 2-3: que `adk web` cargue un `root_agent` de tipo
  `Workflow` y, en S4, que Agent Engine lo despliegue. Si alguno falla, el plan B son los
  workflow agents clásicos con la misma topología (el spike ya los ejerció).
- Sin credenciales en CI: los tests de integración usan un `BaseLlm` falso (patrón validado
  en el spike); la corrida real se documenta en el PR.
