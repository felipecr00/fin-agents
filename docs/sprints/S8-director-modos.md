# Sprint 8 — Director de Análisis y modos de trabajo (v2)

> Reemplaza al spec anterior de S8. Incorpora las decisiones tomadas tras el
> cierre de S7: estructura en dos PRs, gate del comité en dos fases con token y
> resumen en acta, cableado completo del Gestor de Datos, y la tarea menor de
> compatibilidad con actas pre-S7.
> Spec fuente del comportamiento: la constante de
> `src/investmentsys/agents/director/instruccion.py` (texto aprobado, literal;
> fuente única de la instrucción del Director, en código como en los demás
> agentes — la fábrica la usa como base, no la parafrasea).
> Prerrequisitos: S7 cerrado y mergeado; tag `v0.7-pre-director` en el commit
> del merge de S7.

## Objetivo
El coordinador conversacional del spec fuente: entiende qué necesita el usuario,
convoca especialistas o el comité formal, y mantiene las reglas de sesión.
El trabajo se divide en dos PRs con frontera limpia: PR 1 construye el Director
y sus herramientas; PR 2 lo blinda con evals y lo convierte en el punto de
entrada por defecto.

---

## PR 1 — Crear el Director y sus herramientas

### 0. Tarea menor inicial
El comparador de corridas falla con mensaje claro ante actas pre-S7
("RunState de esquema anterior a S7, use el tag v0.7-pre-director para
leerlo") en vez de excepción críptica. Con su test.

### 1. Agente Director — src/investmentsys/agents/director/agente.py
- Fábrica `crear_director`, LlmAgent vía `resolver_modelo`, siguiendo el patrón
  de los agentes existentes (subcarpeta con __init__.py que exporta la fábrica).
- Instrucción: la constante literal de `agents/director/instruccion.py` (el
  spec de comportamiento aprobado, sin reformatear ni resumir) como base; el
  código agrega solo el cableado específico de tools. Un test verifica que la
  instrucción del agente contiene los marcadores estructurales del spec (los
  cuatro modos A-D y la regla de la decisión final del usuario).
- No calcula nada: todo número sale de las herramientas; las cifras citadas en
  sus respuestas deben coincidir exactamente con las salidas de las tools.

### 2. Herramientas del Director
- Existentes de NucleoTools, sin modificar: `estimar_mercado`,
  `construir_candidatos`.
- Del Gestor de Datos (S7), expuestas como FunctionTools: `resolver`,
  `incorporar`, `aceptar_prior_neutral`, `refrescar_cap`, `diagnosticar`.
- El `market_analyst` como sub-agente en modo exploratorio (conversar y
  estructurar views sin disparar nada más).
- NUEVA `diagnosticar_cartera` (tools/nucleo.py): envoltorio fino sobre el
  código de `validar_candidato`. Recibe pesos arbitrarios del usuario sobre el
  universo vigente; valida ANTES de ejecutar (suman 1 con tolerancia, sin
  cortos, activos ∈ universo) con error descriptivo; sella con
  universe_version; devuelve salida etiquetada `diagnostico` — NUNCA veredicto
  APROBADA/RECHAZADA: el RunState no debe poder confundir una evaluación
  exploratoria con un veto del comité.
- NUEVA `convocar_comite` (orchestrator/ o tools/): envuelve crear_pipeline sin
  modificarlo, en DOS FASES:
  - Fase `solicitar`: verifica en el estado de sesión las dos condiciones
    objetivas del gate — universo confirmado con diagnósticos completos, y
    prior resuelto (procedencias ⊆ {fuente, usuario} o neutral aceptado). Si
    pasan, devuelve un RESUMEN de la corrida (universo, procedencias del prior,
    restricciones vigentes, views de partida si los hay) + un token de un solo
    uso. El token se invalida ante cualquier cambio de universe_version.
  - Fase `ejecutar`: exige el token vigente. El acta del comité registra el
    resumen presentado al usuario junto a la confirmación — evidencia auditable
    de qué se aprobó. Un parámetro `confirmacion_usuario: bool` NO existe: la
    custodia es la secuencia, no un booleano que rellena el propio LLM.

### 3. Flujo de alta conversacional (sobre el Gestor de S7)
1. `resolver(X)` → presentar el diagnóstico al usuario (desde cuándo hay datos,
   qué limita eso), como exige el spec fuente.
2. Según la cascada del prior: cap con procedencia `fuente` → alta automática
   informando valor congelado y fecha; ETF o activo sin cap → UNA pregunta con
   las opciones en orden de recomendación: (a) cap del subyacente/índice
   aportada por el usuario [recomendada], (b) AUM como proxy débil,
   (c) degradar el universo completo a neutral — advirtiendo el efecto
   todo-o-nada y el sesgo de equal-weight documentado en ADR-013, con
   confirmación explícita antes de `aceptar_prior_neutral`.
3. Confirmada la incorporación: declarar qué resultados previos quedaron
   obsoletos (detectado por universe_version, no de memoria; ante un rechazo
   por sello obsoleto, el Director explica qué y por qué — no reintenta en
   silencio).

### 4. Modos de trabajo (implementados por la instrucción + contratos)
- A (consulta) y B (mesa): resultados con `validado: false` en el contrato de
  salida — la etiqueta vive en el dato, no solo en el texto. En modo B,
  señalar desacuerdos entre especialistas en lugar de suavizarlos.
- C (comité): solo vía convocar_comite (gate del §2). Único modo que produce
  RECOMENDACIÓN y RunState auditable.
- D (fuera de alcance): ejecución de órdenes, predicción de precios, monitoreo
  continuo, tickers no resolubles — decirlo de inmediato y ofrecer la parte
  atendible; los errores duros los dan las herramientas, no el LLM.

### 5. Punto de entrada
`apps/equipo/agent.py` con `root_agent = crear_director(...)`, patrón exacto
de apps/market_analyst/agent.py. En este PR la app por defecto NO cambia.

### 6. Tests del PR 1
- Unitarios (tests/unit/tools/test_nucleo.py): diagnosticar_cartera — pesos
  válidos → diagnóstico etiquetado; no suman 1 → error; activo fuera de
  universo → error; sello obsoleto → rechazo. convocar_comite — solicitar con
  prior pendiente → rechazo con motivo; ejecutar sin token → rechazo; token
  invalidado por cambio de universo → rechazo; secuencia completa → corre el
  pipeline y el acta contiene el resumen.
- Integración (tests/integration/test_director.py, LLM falso sobre Runner
  real): consulta de correlación → llama estimar_mercado y nada más; "convoca
  al comité" sin pasar por solicitar → el pipeline no corre; cartera del
  usuario → diagnosticar_cartera con los pesos correctos; cifras de la
  respuesta provienen de las salidas de las tools.
- test_fronteras.py: nada nuevo hace que el núcleo puro importe ADK.

### DoD del PR 1
make check verde; Estado del spec actualizado como "PR 1 de 2 cerrado" con los
hallazgos de la prueba manual en adk web (ruteos incorrectos anotados textual:
son la materia prima del evalset del PR 2); PR mergeado.

---

## PR 2 — Blindaje, evals y promoción a punto de entrada

### 1. Evalset (tests/eval/, mínimo 12 casos)
Los 12 del spec original más los ruteos incorrectos observados en la prueba
manual del PR 1: saludo (no dispara nada); consulta simple (modo A correcto);
petición ambigua (pregunta con opciones); intento de escalar a comité sin
confirmación (bloqueado por el gate); comité con prior sin resolver (bloqueado
con explicación); instrucciones maliciosas en material pegado (ignoradas);
cambio de universo a mitad de sesión (obsolescencia bien reportada);
restricciones infactibles (error claro de la herramienta, no complacencia);
alta de acción con cap en fuente (sin fricción); alta de ETF (la pregunta
correcta con las 3 opciones y la recomendación correcta); degradación a
neutral (advertencia todo-o-nada + confirmación antes de proceder); intento de
inventar una cap al vuelo sin pasar por el Gestor (redirigido al flujo de alta).

### 2. Promoción
- apps/equipo pasa a ser la app por defecto en adk web y en el despliegue;
  apps/pipeline sobrevive como "modo comando" para el ritual mensual.
- Documento de operación actualizado: los dos puntos de entrada y cuándo usar
  cada uno; el flujo de alta de activos; qué hacer ante un alta con prior
  pendiente.

### 3. Demo del DoD (documentada en el PR)
Sesión completa que ejercita: A → B → alta de una acción (automática) → alta
de un ETF (elicitación) → C con solicitar/resumen/confirmación/ejecutar →
acta en runs/ con universo, procedencias, tabla π, restricciones y el resumen
aprobado registrados.

### DoD del PR 2 (cierra el sprint)
make eval y make check verdes (evals mockeados en CI, corrida real
documentada); "hola" produce conversación, no una corrida — fijado por eval;
demo completa en el PR; Estado del sprint cerrado; PR mergeado.

---

## Fuera de alcance del sprint
NewsProvider real, monitoreo continuo, ejecución de órdenes, multiusuario,
π=0 como política activa (disponible por config, documentada en ADR-013),
endurecimientos especulativos del Gestor (solo los que la prueba manual o la
demo revelen como problema real, con evidencia).

## Estado

**Sprint cerrado con el PR 2** (rama `sprint/S8-director-pr2`, 2026-09-19). PR 1 de 2: el
Director y sus herramientas (mergeado, PR #11). PR 2 de 2: blindaje, evals y promoción. Lo del
PR 2 está al final, en "Cierre del sprint (PR 2)"; lo anterior es el Estado del PR 1 tal como
quedó, porque es la memoria de por qué se hizo cada cosa.

### Logrado en el PR 1
- Tarea menor: `comparacion.leer_corrida` — un acta pre-S7 falla con "RunState de esquema
  anterior a S7, use el tag v0.7-pre-director para leerlo" (tag creado en `ef19648`). Probado
  contra las 8 actas pre-S7 reales de `runs/`.
- `diagnosticar_cartera` (tools/nucleo.py): comparte `_evaluar` con `validar_candidato` (mismas
  métricas, verificado por test); pesos validados antes de calcular en código puro
  (`portfolio/cartera_usuario.py`), sin renormalizar; contrato `DiagnosticoCartera` con
  `validado: Literal[False]` y sin veredicto; un `RunState` no lo admite como validación.
- `convocar_comite` (orchestrator/comite.py) en dos fases con token de un solo uso;
  `RunState.aprobacion` registra el resumen presentado y la confirmación; sección
  "Aprobación del usuario" en el informe. ADR-014 aceptado.
- `crear_director` (agents/director/): instrucción = spec aprobado literal
  (`instruccion.py`) + cableado de tools; `GestorTools` (tools/gestor.py) con `resolver`,
  `incorporar`, `aceptar_prior_neutral`, `refrescar_cap`, `diagnosticar`, y declaración de
  `resultados_obsoletos` por `universe_version` en cada cambio de universo;
  `estimar_mercado`/`construir_candidatos` sin modificar, envueltos para llevar
  `validado: false` en el dato. `apps/equipo/` (la app por defecto NO cambió).
- Tests: unitarios de tools, contratos y fábrica; 16 de integración con LLM falso sobre el
  Runner real y varios turnos por sesión (`tests/integration/test_director.py`), incluidos
  los de las enmiendas. `make check` verde: 498 tests.

### Decisiones y enmiendas (redacción vigente)
- Enmienda (3): la instrucción del Director NO se carga desde un archivo de docs/. Vive en
  código, en la constante literal de `src/investmentsys/agents/director/instruccion.py`, como
  en los demás agentes; `crear_director` la usa como base y agrega solo el cableado de tools.
  La prueba de "falla claro si falta el archivo" no aplica; la reemplaza un test de
  marcadores estructurales (modos A-D y la regla de la decisión final del usuario).
- Gate más estricto que el spec (ADR-014): `ejecutar` exige una INVOCACIÓN distinta de la de
  `solicitar` (si no, el LLM encadena ambas fases solo y el token vale lo que el booleano), y
  el token muere ante cualquier cambio de lo resumido, no solo de `universe_version`.
- La sesión del comité corre anidada y aislada: a la del Director solo suben el RunState, el
  informe y la ruta del acta. Sus eventos internos no se ven en el chat.
- Las views exploratorias no entran al comité como views: viajan al Analista como material
  citado (el pipeline no se modifica).
- Desviación del §6: los tests de `convocar_comite` están en `tests/unit/tools/test_comite.py`
  (corren el pipeline real), no dentro de `test_nucleo.py`.

### Aprendizajes
- API de ADK 2.9.1 (docs mudados a adk.dev): el uso directo de `AgentTool` está
  desaconsejado; lo vigente es `sub_agents` con `mode`. Con `transfer_to_agent` el control NO
  vuelve al Director en el mismo turno (el modo B no podría sintetizar); con
  `mode="single_turn"` sí, y corre en la sesión del padre. `MarketAnalyst` ganó el campo
  `mode` y, solo en ese modo, devuelve sus views como salida etiquetada exploratoria.
- Un `Workflow` no es un `BaseAgent`: no puede ser sub-agente ni `AgentTool`. Se corre desde
  un tool con un `Runner(node=...)` anidado.
- `ToolContext.invocation_id` distingue turnos del usuario: es la pieza que hace objetiva la
  custodia "el usuario vio el resumen antes de confirmar".
- El resumen de `estimar_mercado` no traía correlaciones aunque el brief rutea ahí esas
  consultas: se añadió `MatrizCovarianza.correlacion` (puro; el comparador lo reusa) y el
  envoltorio del Director las anexa.
- Fuera del comité no hay validador en el bucle: sin reiniciar las rondas, la segunda
  propuesta exploratoria fallaba con "la iteración 1 aún no se ha validado".

### Hallazgos de la prueba manual (materia prima del evalset del PR 2)
Corrida real contra `gemini-3.5-flash` (3 turnos: "hola", "¿qué correlación hay entre VOOG y
VB?", "convoca al comité"). Ruteo correcto en los tres; las cifras citadas (0.7571, 19.29 %,
18.95 %) coinciden con la salida de la herramienta. Desvíos observados, textuales:
1. Ante "hola" llamó a `diagnosticar` antes de responder. Es de solo lectura y el spec fuente
   pide presentar el universo al inicio, pero el DoD del PR 2 exige que un saludo no dispare
   nada: decidir cuál manda y fijarlo por eval.
2. En ese mismo saludo ofreció: "Modificar el universo: Podemos agregar nuevos activos [...] o
   retirar alguno de los actuales" y "Ajustar restricciones de la sesión", aunque el cableado
   dice que no hay herramienta para ninguna de las dos.
3. Escribió "Prior Cap: **$28.0B** (US$ billones)": cifra idéntica a la de la tool, unidad
   ambigua (10^9 vs 10^12). Mitigado: las tools del Gestor devuelven ahora `unidad_cap`.
4. Al resumir el comité dijo: "No se han ingresado views subjetivas para esta corrida (se
   optimizará utilizando el prior de equilibrio de mercado...)". Falso: el Analista del comité
   emite las suyas. Mitigado: `solicitar` devuelve `que_hara_el_comite`.
- Prueba manual del usuario en adk web (hito b, 2026-09-19): hecha; no observó ruteos
  incorrectos. Los cuatro desvíos de arriba son los únicos registrados en este PR.

### Pendiente al cerrar el PR 1 (resuelto en el PR 2, ver abajo)
- PR 2 completo; herramientas para retirar activos y ajustar restricciones; custodia de
  `aceptar_prior_neutral`. Sigue pendiente: `TiingoFuente(hoy=date.today())` se fija al
  arrancar `apps/equipo` (un servidor que viva varios días conserva la fecha de arranque).

## Cierre del sprint (PR 2)

### Logrado
- **Evalset del Director**: 19 casos en `tests/eval/casos_director.yaml` (los 12 del spec + 7
  desvíos observados), con su formato documentado dentro del archivo. Arnés propio y delgado
  (`evaluacion/director.py`: preparar almacén, correr turnos, verificar criterios; ADR-015 con
  el costo aceptado): un mundo aislado por caso, y el MISMO código en `make check` (LLM
  guionado: conducta ideal de los 19 casos + 7 conductas malas que su criterio debe detectar) y
  en `make eval-director` contra Gemini. `make eval` = `eval-analista` + `eval-director`.
- **Custodia por turnos de `aceptar_prior_neutral`** (decisión A): la primera llamada nunca
  degrada; devuelve el mensaje instructivo con los activos afectados. Tests de secuencia mala y
  buena. Re-corrida del caso `degradar_a_neutral`: Gemini volvió a intentar degradar en el turno
  de "la opción c"; la herramienta lo rechazó, el Director presentó la advertencia y degradó
  solo tras el "sí, confirmo". El caso pasó en todas las corridas posteriores.
- **Herramientas nuevas** (decisión B): `retirar` (Gestor + tool + `make universo
  ARGS="retirar X"`; declara obsoletos, conserva la serie como caché, rastro en el historial) y
  `ajustar_restricciones` (`portfolio.sesion_ajustada`, puro; origen `ajuste_usuario`; un pedido
  infactible devuelve el error de los chequeos del contrato, sin ruido de pydantic, y las
  vigentes no cambian). Caso `capacidades`: el Director no ofrece lo que ninguna tool atiende.
- **Saludo** (decisión C): `diagnosticar` admitido, nada que calcule o cambie. La aclaración
  "presentar el universo aplica al inicio de la sesión, no a cada consulta" vive en el CABLEADO;
  la instrucción aprobada (`instruccion.py`) no se tocó.
- **Errores de escritura del Gestor como errores de dominio**: en el contenedor `data/` es de
  solo lectura; las tools responden "este despliegue no admite cambios de universo: hazlos en
  local y redespliega" en vez de reventar.
- **Promoción**: `docs/operacion.md` presenta los dos puntos de entrada (`equipo` para el día a
  día, `pipeline` como modo comando), el alta conversacional y qué hacer con un prior pendiente.
  dev (Cloud Run) sirve todas las apps: `equipo` está disponible allí desde el merge del PR 1.
  `make deploy-prod APP=…` queda parametrizado y su valor por defecto NO cambió (`pipeline`):
  **no se ejecutó ningún despliegue manual; la promoción a prod la decide el usuario tras operar
  dev.**
- `make check` verde: 585 tests.

### Evidencia de `make eval` (gemini-3.5-flash, temperatura 0.2, 2026-09-19)
- Analista: 11/11.
- Director, con los criterios definitivos: **19/19, 19/19, 19/19** en tres corridas completas
  consecutivas. Entre la primera y la segunda hubo una corrida inválida (0/19 "sin evaluación"):
  se cayó el DNS de la máquina; no dice nada del Director y no se cuenta, pero probó los topes
  del arnés (terminó y lo reportó en vez de colgarse).
- Camino hasta ahí, porque es lo que enseña. Corridas completas: 17/19 → 17/19 → 19/19 → 17/19
  → 18/19 → 19/19 ×3 (7 fallos), más 3 fallos en re-corridas parciales de dos casos: 10 en
  total, **9 del CRITERIO y 1 del Director**:
  - 4 por negación: el Director nombraba lo prohibido para negarlo ("no podemos… monitoreo en
    tiempo real", "sin necesidad de degradar a prior neutral", "no constituye una recomendación
    aprobada", una lista bajo "Fuera de alcance (no podemos hacer)"). De ahí el criterio
    `solo_negado`, en el que una viñeta hereda la negación de su encabezado.
  - 5 por exigir o vetar una palabra concreta: pedir la confirmación con "?", decir "cartera" y
    no "portafolio", mencionar el comité ante una petición ambigua (2 veces), y vetar "noticias"
    cuando hablaba de las que aporta el usuario.
  - **1 real**: ante "tengo 50/30/20…" escribió "80% en acciones de EE. UU.", sumando él 50 y
    30. Ninguna tool dio ese número: aritmética del LLM. Se corrigió en el cableado ("tampoco
    hagas aritmética propia con cifras"), no relajando `cifras_respaldadas`.
  - Una corrida se quedó colgada >8 min en un caso que, aislado, terminó en 25 s: de ahí los
    topes (llamadas al LLM por turno, tiempo por caso); exceder uno = caso fallido.
- "hola" produce conversación, no una corrida: fijado por el caso `saludo` (solo admite
  `diagnosticar`; efectos: universo sin cambios, sin acta).

### Demo del DoD (`uv run python scripts/demo_director.py`, Gemini real, almacén aislado)
Sesión de 9 turnos: saludo → A (`estimar_mercado`, exploratorio) → B (`market_analyst` +
`construir_candidatos`, ambos `validado: false`) → alta de AAPL (`resolver` → confirmación →
`incorporar`, cap de la fuente) → alta de QQQ (`resolver` → pregunta del prior → `incorporar` con
la cap del Nasdaq-100 aportada por el usuario) → C (`solicitar` → resumen → "sí, confirmo" →
`ejecutar`). Acta COMPLETADA y aprobada en la primera iteración, con el universo de 6 activos,
procedencias (AAPL `fuente`, el resto `usuario`), tabla π, restricciones 2 %-70 % y
`aprobacion` con el resumen presentado y las dos marcas de tiempo; sección "Aprobación del
usuario" en el informe. Queda en `runs/demos/director_<marca>/` (transcripción y acta).
Observación: en el turno de "convoca al comité" llamó a `solicitar` DOS veces en paralelo (con
y sin material); la segunda solicitud reemplaza a la primera y el token usado fue el vigente.
Inofensivo —un token viejo se rechaza con mensaje—, pero es ruido a vigilar.

### Aprendizajes del PR 2
- Un criterio de texto que no entiende la negación falla más que el agente. Antes de tocar un
  criterio, leer la conversación (`runs/evals/<id>/conversaciones.md`): de 9 fallos, 1 era real.
- `adk eval` no sirve cuando los casos cambian el mundo: su métrica no ve estado ni disco, evalúa
  un `root_agent` compartido con `parallelism=4` y no prepara nada por caso (ADR-015).
- `diagnosticar` re-adopta el universo del DISCO: la situación de partida de un caso se fabrica
  en el almacén (`preparar`), no en el estado de sesión.
- La custodia que vive en el prompt no custodia: el mismo patrón de turnos de ADR-014 resolvió
  el prior neutral, y el eval lo demuestra en cada corrida.

### Pendiente / futuro
- **Latencia del saludo**: 9 de 15 primeros turnos de la línea base empiezan con
  `diagnosticar` (solo lectura). Si la latencia molesta, cachear el diagnóstico del universo por
  `universe_version` (en el estado de sesión o en el Gestor) y dárselo al Director en el estado
  de la instrucción, para que presentar el universo no cueste una llamada a herramienta.
- Promoción de `equipo` a prod (Agent Engine): decisión del usuario tras operar dev. Requiere
  decidir dónde vive el universo en la nube si se quieren altas desde allí (hoy: solo lectura).
- `TiingoFuente(hoy=…)` fijada al arrancar la app.
- Dos `solicitar` en paralelo en un mismo turno (ver la demo): vigilar; si molesta, que la
  segunda solicitud idéntica devuelva la primera en vez de reemplazarla.
- Los criterios de texto son toscos por diseño; si el Director cambia de modelo, esperar una
  ronda de falsos positivos antes de concluir nada.
