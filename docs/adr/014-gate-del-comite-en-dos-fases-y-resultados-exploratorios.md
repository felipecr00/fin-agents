# ADR 014: Gate del comité en dos fases con token, y resultados exploratorios no validados en el dato

- Fecha: 2026-09-19
- Sprint: S8 (PR 1 de 2)
- Estado: propuesta

## Contexto
S8 añade un Director conversacional (LlmAgent) sobre el comité formal de S3-S7. Dos riesgos
nuevos nacen de poner un LLM entre el usuario y el pipeline:

1. **Escalada sin consentimiento.** El spec exige que el comité (único modo que produce
   RECOMENDACIÓN y acta) solo corra con confirmación explícita del usuario. Un parámetro
   `confirmacion_usuario: bool` lo rellena el propio LLM: no custodia nada.
2. **Confusión entre exploratorio y validado.** El Director también consulta especialistas
   sueltos (modos A/B) y evalúa carteras que trae el usuario. Si esa evaluación se guardara
   como `ValidationReport`, un acta podría confundir una medición exploratoria con un veto.

Hechos verificados antes de decidir (google-adk 2.9.1 instalado, docs en adk.dev):
- `crear_pipeline` devuelve un `Workflow`, que no es un `BaseAgent`: no puede ser `sub_agent`
  ni envolverse en `AgentTool` (cuyo uso directo, además, la propia clase desaconseja en 2.x
  a favor de `sub_agents` con `mode`). Correrlo desde un tool exige un `Runner(node=...)`
  anidado, que es el mismo patrón que usa `AgentTool` por dentro.
- `ToolContext.invocation_id` identifica el turno del usuario: dos llamadas a tools dentro de
  una misma respuesta del LLM comparten `invocation_id`; tras un mensaje nuevo, cambia.
- Las 8 actas pre-S7 de `runs/` no validan contra el `RunState` vigente; la de S7 sí, y debe
  seguir haciéndolo.

## Decisión
**Gate en dos fases** (`orchestrator/comite.py`, tool `convocar_comite(fase, token, material)`):
- `solicitar` verifica en el estado de sesión las dos condiciones objetivas —universo válido
  con diagnósticos, prior resuelto (`estado_prior ≠ pendiente`)— y devuelve un `ResumenComite`
  (universo, procedencias del prior, restricciones con su origen, fecha, views de partida,
  material del usuario) más un token de un solo uso. Guarda la `SolicitudComite` en la sesión.
- `ejecutar` exige ese token **en una invocación distinta** de la que lo emitió (entre ambas
  hubo, por construcción, un mensaje del usuario), lo invalida si cambió `universe_version` o
  cualquier cosa de lo resumido (se re-resume y se compara), lo consume pase lo que pase, y
  corre `crear_pipeline` sin modificarlo en una sesión anidada y aislada.
- El acta registra la evidencia: `RunState.aprobacion: AprobacionComite | None` (resumen
  presentado, marcas de tiempo y las dos invocaciones). `None` = modo comando (apps/pipeline,
  scripts) y actas de S7: el campo es opcional y no rompe nada existente. El contrato rechaza
  una aprobación de otro universo, de otras restricciones o confirmada en el turno de la
  solicitud. El informe añade la sección "Aprobación del usuario".

**Exploratorio en el dato**: contrato nuevo `DiagnosticoCartera` con `etiqueta="diagnostico"`
y `validado: Literal[False]`, sin campo `veredicto` ni sugerencias al Constructor. Se guarda en
una clave propia (`diagnosticos_cartera`) que `armar_run_state` no lee; un `RunState` no lo
admite como validación. `diagnosticar_cartera` comparte con `validar_candidato` el mismo
`_evaluar` (mismas métricas, verificado por test) y valida los pesos antes de calcular, en
código puro (`portfolio/cartera_usuario.py`), sin renormalizar.

## Alternativas descartadas
- **`confirmacion_usuario: bool`**: descartada por el spec; el LLM la pone en `true` solo.
- **Token sin exigir otro turno**: el LLM puede encadenar `solicitar` → `ejecutar` en una
  misma respuesta; la secuencia sería tan débil como el booleano. El chequeo de
  `invocation_id` cuesta una comparación y lo cierra.
- **Confirmación nativa de ADK** (`require_confirmation` / `tool_confirmation`): pausa el tool
  con un diálogo genérico del cliente; no deja en el acta QUÉ se aprobó, depende de que cada
  cliente (adk web, Agent Engine, evals) implemente el diálogo, y no verifica el gate objetivo.
  Puede sumarse después como segunda barrera; no sustituye al resumen auditable.
- **Pipeline como `sub_agent`/`AgentTool`**: imposible (no es `BaseAgent`) y, aunque lo fuera,
  una transferencia no pasa por ningún gate.
- **Propagar todo el estado del comité a la sesión del Director** (como hace `AgentTool`):
  mezclaría candidatos y validaciones del comité con lo exploratorio. Solo suben el RunState,
  el informe y la ruta del acta (ADR-009 sigue valiendo para corridas remotas).
- **Reusar `ValidationReport` con un flag `exploratorio`**: mantiene el campo `veredicto`
  a un descuido de distancia de un acta. Un tipo distinto lo hace imposible, no improbable.
- **Renormalizar pesos que no suman 1**: la herramienta alteraría lo que dijo el usuario; el
  spec exige distinguir lo dicho por el usuario de lo que quedó por default.

## Consecuencias
- `RunState` cambia (campo opcional `aprobacion`): consumidores actualizados — `armar_run_state`
  (lee `aprobacion_comite` del estado), el informe del reporter, y tests. El comparador y el
  replay no lo usan: la aprobación no es un input del cálculo.
- Los eventos internos del comité no se ven en la conversación del Director (corre anidado):
  el usuario ve la salida del tool y el acta. Si se quiere streaming del comité en adk web,
  sigue existiendo apps/pipeline.
- Las views exploratorias NO se inyectan al comité como views: viajan al Analista como
  material citado y él emite las suyas (el pipeline no se modifica). Si se quisiera "correr el
  comité con exactamente estas views", hace falta tocar `crear_pipeline`: fuera de este PR.
- Cualquier tool que ejecute `_sesion` o `estimar_mercado` entre las fases cambia lo resumido
  (p. ej. fija la fecha de decisión) e invalida el token: estricto a propósito; el costo es
  repetir `solicitar`.
- Para `validado: false` en las salidas de `estimar_mercado` y `construir_candidatos` (que no
  se modifican), el Director las expone con un envoltorio que añade la marca: hito (b).
