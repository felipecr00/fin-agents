# ADR 019: Personas thin (Estadístico, Escéptico): voz propia, una tool y custodias en código

- Fecha: 2026-09-20
- Sprint: S10
- Estado: aceptada (2026-09-20, checkpoint de S10: aprobadas las dos alternativas recomendadas)

## Contexto
S10 desdobla al Estadístico y al Escéptico como `LlmAgent` thin (`single_turn`, una tool cada
uno) bajo el Director. Hasta S9 eran FunctionTools del Director: el Director veía el dict de la
herramienta, narraba las cifras y un callback suyo armaba la ficha de origen (ADR-017).

Un spike sobre el ADK instalado (2.9.1; Runner real, LLM guionado, sin red) midió qué cambia al
poner un LLM entre el Director y la herramienta:

1. **El Director recibe solo el TEXTO de la persona** (`{'result': '<texto>'}`), no el dict de
   su tool. `recoger_anexos` del Director deja de ver `validado`, el sello y las cifras: tal
   como está, la ficha de origen y el prefijo `⚠ NO VALIDADO ·` desaparecerían.
2. **Estado e `invocation_id` son los del turno**: la tool de la persona escribe en el mismo
   estado de sesión y su `after_tool_callback` ve el mismo `invocation_id` que el Director. El
   gate del comité (un `invocation_id` por turno del usuario) no se ve afectado.
3. **La persona ya le habla al usuario**: su respuesta es un evento propio
   (`author=estadistico`, final, en una rama aislada `estadistico@<fc_id>`). Si además el
   Director la re-narra, el usuario lee dos veces las cifras, la segunda pasada por otro LLM.
4. **La persona solo ve su encargo** (los argumentos de la llamada, como mensaje de usuario),
   no la conversación. Con `input_schema` el encargo es tipado, y un `before_tool_callback` del
   Director ve esos argumentos antes de que corra la persona.
5. ADK le declara `transfer_to_agent` a un sub-agente aunque sea `single_turn`: sin
   deshabilitarlo, la persona tiene dos tools, no una.

## Decisión
1. **La respuesta de la persona ES la respuesta al usuario.** El Estadístico y el Escéptico
   hablan en primera persona en su propio evento. El Director recibe ese texto (lo necesita
   para coordinar y señalar desacuerdos) con la regla de cableado: no repetir sus cifras;
   cerrar con lo que coordina (siguiente paso, desacuerdo con otro especialista). La atribución
   de una cifra dicha por la persona es su autoría del evento.
2. **La ficha la recoge la persona, no el Director.** `recoger_anexos` pasa a ser también el
   `after_tool_callback` de cada persona: misma ficha, mismo estado, mismo `invocation_id`; el
   Director la anexa al cerrar el turno como hoy (ADR-017 no cambia). `validado: false` sigue
   viviendo en el dato (`exploratorio(...)` envuelve la tool de la persona igual que antes).
3. **Una tool de verdad**: `disallow_transfer_to_parent` y `disallow_transfer_to_peers` en las
   personas; un test fija que el modelo de cada persona recibe exactamente una declaración.
4. **Los pesos del usuario no pasan por el LLM de la persona.** El Escéptico declara
   `input_schema` (`pregunta`, `pesos` opcional). Un `before_tool_callback` del Director deja
   los pesos en el estado y `diagnosticar_cartera` los lee de ahí: la tool de la persona no
   tiene argumentos numéricos. Sin `pesos`, diagnostica la cartera recomendada que esté vigente
   sobre la mesa; si no hay ninguna, responde `rechazado` con el motivo. El Estadístico recibe
   solo `pregunta`.
5. **Prompts de rol** según el diagrama aprobado: el Estadístico reporta SIEMPRE la confianza
   de su estimación (intervalo, observaciones, ventana corta) y qué método es más defendible; el
   Escéptico busca grietas y nunca emite veredicto fuera del comité. Ambos: toda cifra idéntica
   a la de su tool, sin aritmética propia, disclaimer al cierre. Nivel y temperatura desde
   `config.yaml` (`inferencia.asignaciones`, `agentes.temperatura_personas`).
6. **Evaluación**: `cifras_respaldadas` y el arnés pasan a leer también los eventos de las ramas
   de las personas (su texto y la salida de su tool). Criterio nuevo `habla`: en el turno hay
   texto con autoría de la persona indicada. `cifras_atribuidas` se sigue exigiendo al texto del
   Director (que ya no debería traer cifras de las personas).

## Alternativas descartadas
- **El Director re-narra a la persona (comportamiento por defecto de ADK).** Duplica las cifras
  y añade un segundo LLM entre la herramienta y el usuario: más superficie para el error que
  S8-S9 cerraron ("toda cifra idéntica a la de una herramienta").
- **Entregar el texto de la persona como bloque anexado por código** y darle al Director solo
  una nota. Independiente de la interfaz, pero el Director pierde el contenido y no puede
  señalar desacuerdos entre especialistas (modo B del spec). Queda como plan B si la demo
  muestra que alguna interfaz no presenta los eventos de la rama de la persona.
- **`AgentTool` clásico / sesión anidada por persona.** Aísla el estado: la tool no escribiría
  en la mesa ni en el mismo turno, y la ficha no llegaría al cierre.
- **Pesos como argumento del LLM de la persona.** Dos saltos de LLM para una cifra del usuario;
  la frontera del proyecto es que las cifras no viajan por argumentos de LLM cuando hay
  alternativa.

## Consecuencias
- Dos contextos de LLM más por consulta a persona (costo aceptado: ver la nota del spec). La
  latencia de una consulta pasa de 2 a 4 llamadas al modelo.
- La persona no ve la conversación: lo que necesite debe ir en `pregunta` o estar en la mesa.
- La ficha, el prefijo y la mesa siguen siendo del código; ninguna custodia se mueve al prompt.
- El arnés de evaluación cambia (lee ramas); los 22 casos existentes se re-corren sobre él.
