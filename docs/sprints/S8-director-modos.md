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
(pendiente — el PR 1 anota aquí sus hallazgos de prueba manual; el PR 2 cierra)

Decisiones registradas antes de empezar el PR 1:
- Enmienda (3), redacción vigente: la instrucción del Director NO se carga desde
  un archivo de docs/. Vive en código, en la constante literal de
  `src/investmentsys/agents/director/instruccion.py`, como en los demás agentes;
  `crear_director` la usa como base y agrega solo el cableado de tools. La prueba
  de "falla claro si falta el archivo" no aplica; la reemplaza un test de
  marcadores estructurales (modos A-D y la regla de la decisión final del usuario).
