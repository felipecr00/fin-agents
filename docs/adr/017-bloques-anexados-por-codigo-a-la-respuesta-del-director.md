# ADR 017: Ficha de origen, mesa y orden del comité se anexan por código a la respuesta

- Fecha: 2026-09-20
- Sprint: S9
- Estado: propuesta (pendiente de aprobación en el checkpoint 2 de S9)

## Contexto
S9 pide que cada respuesta lleve una ficha de origen determinista (especialista, herramienta,
cifras clave, sello, etiqueta EXPLORATORIO), un prefijo automático para todo dato con
`validado: false` —"la advertencia sobrevive a la narración porque no depende de ella"— y que
`solicitar` renderice la Orden Preparatoria de Sesión. Desde S8 `validado: false` ya vive en el
dato, pero llega al usuario solo si el Director lo redacta: el aprendizaje de S8 fue que "la
custodia que vive en el prompt no custodia". Evidencia en este sprint (modelo real, caso
`consulta_simple`): el Director citó la correlación sin decir "exploratorio"; la ficha anexada
fue lo único que lo dijo.

## Decisión
Los bloques para el usuario los redacta y los ENTREGA el código, con dos callbacks de ADK sobre
el Director (`agents/director/anexos.py`):
- `after_tool_callback`: tras cada herramienta (también el sub-agente `market_analyst`, que ADK
  expone como tool) construye la ficha de todo resultado con `validado` (`tools/ficha.py`) y
  RETIRA de la salida el bloque ya redactado (`anexo_usuario`: la mesa, el roster, la orden). El
  LLM recibe los datos estructurados y una nota; no recibe nada que pueda copiar mal.
- `after_model_callback`: cuando el modelo cierra el turno (respuesta final, sin llamadas a
  herramientas, no parcial) pega los bloques del turno al final del texto, una sola vez.

El especialista de la ficha sale de `ATIENDE` (la misma tabla que arma el roster). Solo una
corrida del comité con `validado: true` va sin el prefijo `⚠ NO VALIDADO ·`. La orden se
renderiza desde el `ResumenComite`, el mismo contrato que el acta guarda como lo aprobado: el
contrato NO cambia.

## Alternativas descartadas
- **Que la tool devuelva el bloque y la instrucción pida copiarlo "tal cual".** Es la custodia en
  el prompt: el LLM resume, reordena u omite, y un eval de texto solo lo detecta después.
- **Un agente envoltorio que reescriba el evento final.** Más código y otra capa de eventos para
  el mismo efecto; los callbacks son la extensión prevista por ADK (verificada en el paquete
  2.9.1: `after_tool_callback` también corre para `_SingleTurnAgentTool`).
- **Prefijar cada cifra dentro de la salida de la herramienta.** Ensucia los datos que leen las
  demás herramientas y los evals de cifras, y el LLM puede quitar el prefijo al narrar.

## Consecuencias
- La etiqueta, el prefijo, la tabla de la mesa y la orden del comité llegan SIEMPRE, con
  cualquier modelo y cualquier redacción. Los evals lo fijan con un guion que narra mal a
  propósito (`tests/integration/test_visibilidad.py`).
- La respuesta es más larga: una ficha por herramienta con resultado en el turno.
- El texto final ya no es solo del LLM: queda en el historial de la sesión con los bloques, y el
  modelo los ve en turnos posteriores (son cifras de herramienta: respaldadas).
- Con streaming (SSE) los fragmentos parciales no llevan el anexo; lo lleva la respuesta final
  agregada. Verificar en `adk web` con el interruptor de streaming si se usa.
- Un canal nuevo (p. ej. el plan de compra de S11) se anexa devolviendo `anexo_usuario`.
