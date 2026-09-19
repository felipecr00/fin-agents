# Sprint 8 — Director de Análisis y modos de trabajo

> Spec fuente: `docs/prompts/director.md` (contrato de comportamiento, fuente
> única de verdad de la instrucción del Director — no parafrasear en código).
> Prerrequisito: S7 cerrado. La mecánica del prior (cascada, procedencia,
> todo-o-nada, caps congeladas) ya existe en el núcleo; este sprint le pone la
> conversación encima.

## Objetivo
El coordinador conversacional del spec fuente: entiende qué necesita el usuario,
convoca especialistas o el comité formal, y mantiene las reglas de sesión.

## Alcance

### 1. Agente Director (LlmAgent raíz)
- Instrucción construida DESDE `docs/prompts/director.md` (cargar el archivo,
  no copiar su texto en el código).
- Sub-agentes/herramientas: los especialistas individuales (modo A),
  combinaciones (modo B) y el pipeline formal completo (modo C).
- El Director reemplaza al `pipeline` como app por defecto en adk web y en el
  despliegue; el pipeline directo sigue existiendo como app secundaria (el
  "modo comando" para el ritual mensual sin conversación).

### 2. Alta conversacional de activos (la elicitación que S7 dejó pendiente)
Flujo del Director con el Gestor de Datos al recibir "agrega X":
1. `resolver(X)` → presenta el diagnóstico al usuario (desde cuándo hay datos,
   qué limita eso) tal como exige el spec fuente.
2. Según lo que devuelva la cascada del prior:
   - cap con procedencia `fuente` → alta 100% automática, informa el valor
     congelado y su fecha.
   - ETF o activo sin cap en la fuente → UNA pregunta, en este orden de
     recomendación: (a) capitalización del subyacente/índice aportada por el
     usuario [recomendada], (b) AUM como proxy débil, (c) degradar el universo
     completo a prior neutral. Si elige (c), advertir el efecto todo-o-nada
     ("el prior de TODOS los activos pasa a equiponderado") y el sesgo de
     equal-weight documentado en el ADR, y pedir confirmación explícita antes
     de pasar aceptar_neutral=True.
3. Confirmada la incorporación, declarar qué resultados previos quedaron
   obsoletos (detectado por universe_version, no de memoria).

### 3. Modos de trabajo
- A (consulta) y B (mesa): resultados SIEMPRE etiquetados como exploratorios —
  el contrato de salida gana el campo `validado: bool` y el render lo muestra.
- C (comité formal): gate duro de tres condiciones antes de invocar el
  pipeline — universo confirmado con diagnósticos Y prior resuelto (procedencias
  completas o neutral confirmado), views confirmados o prior explícito de views,
  y confirmación literal del usuario en la conversación. El gate se implementa
  como precondición verificable en la herramienta de invocación, no como
  instrucción al LLM.
- D: la detección de fuera-de-alcance del Director se complementa con errores
  claros de las herramientas (un ticker irresoluble lo dice el Gestor, no el
  LLM).

### 4. Sesión
- Estado de sesión: universo vigente (con caps congeladas y procedencias),
  restricciones vigentes, resultados con su universe_version y etiqueta
  exploratorio/validado.
- Al cambiar el universo o refrescar una cap: el Director enumera qué
  resultados quedaron obsoletos.
- Inicio de sesión: presenta el último universo conocido (activos, procedencia
  del prior, restricciones) y pregunta si se trabaja sobre ese o se cambia
  (regla del spec fuente).

### 5. Seguridad y evals (extensión del evalset de S5)
- Material externo pegado por el usuario viaja a los especialistas como datos
  citados, nunca como instrucciones (mismo tratamiento que las "noticias" del
  S5).
- Evals nuevos, mínimo 12 casos: saludo (no dispara nada — el defecto que
  motivó este rediseño); consulta simple (modo A correcto); petición ambigua
  (pregunta con opciones); intento de escalar a comité sin confirmación
  (bloqueado por el gate); comité con prior sin resolver (bloqueado por el
  gate con explicación); instrucciones maliciosas en material pegado
  (ignoradas); cambio de universo a mitad de sesión (obsolescencia bien
  reportada); restricciones infactibles pedidas por el usuario (error claro de
  la herramienta, no complacencia del LLM); alta de acción con cap en fuente
  (sin fricción); alta de ETF (la pregunta correcta con las 3 opciones y la
  recomendación correcta); degradación a neutral (advertencia todo-o-nada +
  confirmación antes de proceder); intento de "inventarle" una cap al vuelo en
  la conversación sin pasar por el Gestor (el Director lo redirige al flujo de
  alta).

## Fuera de alcance
NewsProvider real, monitoreo continuo, ejecución de órdenes, multiusuario,
π=0 como política activa (queda disponible por config, documentada en el ADR).

## Definition of Done
- Los 12+ evals pasan con `make eval` (mockeado en CI, corrida real
  documentada).
- Demo documentada en el PR: sesión completa que ejercita A → B → alta de una
  acción (automática) → alta de un ETF (elicitación) → C con confirmación →
  acta en runs/ con universo, procedencias del prior, tabla π y restricciones
  registradas.
- "Hola" produce conversación, no una corrida (el eval lo fija para siempre).
- Documento de operación actualizado con los dos puntos de entrada (Director
  conversacional / pipeline comando) y cuándo usar cada uno.
- make check verde; Estado actualizado; PR.

## Prompt de arranque (sesión nueva de Claude Code, SOLO tras cerrar S7)

> Lee CLAUDE.md. El sprint activo es S8 (docs/sprints/S8-director-modos.md) —
> léelo junto con docs/prompts/director.md, que es la fuente única de la
> instrucción del Director (cárgala desde el archivo, no la copies en código),
> y el Estado de S0-S7. Verifica la API vigente de ADK para agentes
> coordinadores con sub-agentes y AgentTool en https://google.github.io/adk-docs/.
> Crea la rama sprint/S8-director-modos. Hitos con checkpoint: (1) el Director
> con modos A y D + el flujo de alta conversacional del §2 sobre el Gestor de
> Datos de S7 — detente y muéstrame una sesión de prueba en adk web con el alta
> de una acción y de un ETF; (2) modos B y C con el gate de tres condiciones
> implementado como precondición en la herramienta — pruébame que el gate
> bloquea comité sin confirmación y sin prior resuelto; (3) los 12 evals, el
> etiquetado exploratorio/validado y la demo completa. Cierra con make eval y
> make check verdes, documento de operación actualizado, Estado y PR.

## Estado
(pendiente — actualizar al cerrar el sprint)
