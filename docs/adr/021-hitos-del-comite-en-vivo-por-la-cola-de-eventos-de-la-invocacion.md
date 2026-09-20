# ADR 021: Hitos del comité en vivo por la cola de eventos de la invocación

- Fecha: 2026-09-20
- Sprint: S11
- Estado: aceptada (2026-09-20, checkpoint 1 de S11)

## Contexto
S11 pide que el comité deje de ser una caja negra: `pipeline.py` emite hitos
(`contracts/hitos_comite.py`) y, **si ADK lo permite**, el chat los muestra durante la llamada a
`convocar_comite`; si no, la garantía mínima es bitácora en paralelo + cronología al cierre.

El comité corre en una sesión ANIDADA y aislada (ADR-014) dentro de una FunctionTool del
Director: mientras la tool no retorna, el Runner de la sesión principal no emite nada.

Lo verificado (google-adk 2.9.1, fijado por ADR-005):
- **Documentación (adk.dev, "Live → Tools")**: las *streaming tools* (tools generadoras
  asíncronas) solo existen en modo live/bidi (`run_live`, modelo Live). No hay ningún mecanismo
  público para que una tool emita eventos intermedios en `run_async`/SSE.
- **Paquete instalado**: un `LlmAgent` raíz corre por el camino de nodos
  (`Runner._run_node_async`), con UNA cola por invocación (`InvocationContext._event_queue`) cuyo
  único consumidor es el bucle del Runner: añade el evento a la sesión y lo entrega al cliente.
  Los nodos de ADK y su propio `_emit_streaming_tool_event` escriben ahí con
  `InvocationContext._enqueue_event`. Una tool tiene ese contexto a mano
  (`tool_context._invocation_context`).
- **Spike medido** (Runner real + LLM falso; luego servidor `adk web` real por `/run_sse` y en la
  interfaz): una tool que encola un evento cada 2 s durante una llamada de 12 s → los eventos
  llegan al cliente a los 2, 4, 6, 8 y 10 s; la respuesta de la tool, a los 12 s.
  - Evento normal (autor `comite`): una burbuja propia por hito en la interfaz, persistido en la
    sesión; en los turnos siguientes el modelo lo ve («[comite] said: …»).
  - Evento `partial=True`: llega en vivo, no se persiste y el modelo no lo ve; pero la interfaz
    concatena los parciales en una sola burbuja que DESAPARECE cuando llega el evento final.

## Decisión
Transmisión **en vivo con eventos persistidos**, más la cronología al cierre SIEMPRE.

- `convocar_comite` reenvía cada hito nuevo de la sesión anidada a la cola de la invocación del
  Director (`tools/hitos_en_vivo.py`): evento normal, autor `comite`, rama
  `convocar_comite@<function_call_id>`, texto redactado por código desde el `HitoComite`.
- **El modelo no ve los hitos** (lección de S9: lo que ve en su historial, lo imita):
  el texto lleva una marca invisible propia y `ocultar_anexos_al_modelo` retira del historial los
  contenidos que la llevan. El Director conoce el resultado por la salida de la tool, como antes.
- **La cronología narrada** (fases, rondas, vetos con motivo, tiempos) se anexa por código a la
  respuesta de cierre (ADR-017), haya habido transmisión o no: es la garantía mínima del spec, y
  lo único que ven los clientes sin SSE (`/run`) o un despliegue que no entregue en vivo.
- **La API es privada, así que se usa con tres cercos**: (1) `tests/test_hitos_en_vivo.py` fija
  sobre el Runner real la semántica de la que dependemos (el evento llega ANTES de que la tool
  retorne, queda en la sesión, no llega al modelo), igual que `test_gate_security.py` con
  `invocation_id`; (2) si el atributo falta o encolar falla, la transmisión se apaga sola para esa
  corrida y el comité sigue: nunca tumba una corrida; (3) interruptor en `config.yaml`
  (`corridas.transmitir_hitos_en_vivo`).
- Los hitos NO entran en `RunState`: llevan la hora del reloj y el acta debe seguir siendo
  reproducible por replay (ADR-009). Viven en `pipeline_milestones`, en
  `runs/<run_id>/bitacora.jsonl` (una línea por hito, escrita mientras corre; `make bitacora`) y
  en los eventos de la sesión del Director.

## Alternativas descartadas
- **Eventos parciales**: sin rastro en la sesión ni recorte del historial, pero la interfaz los
  amontona y los borra al cierre: el usuario pierde la deliberación justo cuando termina.
- **Solo la garantía mínima** (bitácora + cronología al cierre), sin tocar API privada: cumple el
  spec, pero deja mudo el chat durante la llamada más larga del sistema cuando el mecanismo
  existe y está medido. Queda como modo degradado automático.
- **`NodeTool` / `ctx.run_node` sobre el `Workflow`** (correr el pipeline como nodo en la sesión
  del Director): los eventos subirían solos, pero rompe el aislamiento de ADR-014 (el estado
  exploratorio y el del comité se mezclarían), inunda el chat con los eventos internos de cuatro
  agentes y mete todo eso en el historial del Director. Además `_node_tool` también es privado.
- **Streaming tool (generadora asíncrona)**: solo en `run_live`; exige un modelo Live.
- **Sondeo desde el cliente** (que la interfaz lea la bitácora): `adk web` no es nuestra.

## Consecuencias
- El chat muestra la deliberación mientras ocurre; la sesión guarda los hitos como eventos del
  autor `comite`, fuera de lo que el modelo lee y de lo que los evals cuentan como voz del
  Director o de una persona.
- Dependemos de `_invocation_context._enqueue_event`. Al subir la versión de ADK, el test de
  semántica es el primer aviso; si rompe, el sistema sigue funcionando en modo degradado y se
  decide entonces (¿hay ya API pública?). Revisar en cada bump de ADK (ADR-005).
- Un evento normal BLOQUEA a quien lo encola hasta que el Runner lo procesa: el reenvío ocurre
  en el bucle de `convocar_comite`, no dentro del pipeline, que no sabe nada de la transmisión.
- No verificado: que Agent Engine (prod) entregue el SSE en vivo. La cronología al cierre lo
  cubre. `config_hash` cambia por la clave nueva: el replay rechazará corridas anteriores, como
  está diseñado.
