# Sprint 9 — Visibilidad, Pizarra y Atribución (Doc: Sprint 1)

> Fuentes: `docs/propuestas/arquitectura_v2.md` y `docs/propuestas/enmienda_v2.md`
> (la enmienda prevalece ante conflicto).
> Reglas globales de los sprints S9-S12:
> - Ningún documento ni código menciona modelos comerciales: los specs hablan de
>   Nivel 1 (Frontier LLM), Nivel 2 (Edge/cuantizado) y Nivel 3 (determinista);
>   la asignación real vive SOLO en config.yaml.
> - Las fronteras existentes son intocables: núcleo puro sin ADK/LLM, contratos
>   sellados con universe_version, custodias en código, cifras jamás por
>   argumentos de LLM. test_fronteras.py se extiende a fintual/ y research_lab/.
> - Todo output operativo lleva el disclaimer: estimación algorítmica, no
>   asesoría tributaria ni financiera.

## Objetivo
La sala se ve: cada respuesta con silla y ficha, la mesa de trabajo inspeccionable,
el gate blindado por test, y la limpieza de nombres de modelos.

## Alcance
1. `contracts/mesa_trabajo.py`: `MesaDeTrabajoState` e `ItemPizarra` según la
   propuesta (categoria, contenido, origen, obsoleto por ítem), sellados con
   universe_version. Un cambio de universo marca `obsoleto: true` ítem por ítem —
   granularidad por elemento, no solo por sesión.
2. Tool `consultar_mesa_trabajo` (determinista): renderiza la tabla de la mesa
   (universo, vistas, estimaciones, diagnósticos, restricciones, con especialista
   de origen y estado). Reemplaza la llamada suelta a `diagnosticar` en la
   apertura de sesión. Responde también el roster («¿quién está en la sala?»)
   desde la composición real del equipo.
3. Ficha de origen generada por código: el envoltorio exploratorio anexa a cada
   respuesta un bloque determinista con especialista fuente, herramienta, cifras
   clave, sello y la etiqueta EXPLORATORIO. Prefijo visual automático para todo
   dato con `validado: false` — la advertencia sobrevive a la narración porque
   no depende de ella.
4. `tests/test_gate_security.py`: fija por test la invariante del invocation_id
   del gate (ejecutar sin token del turno inmediatamente anterior → excepción
   controlada de violación de gate; token invalidado por cambio de universo →
   ídem). Un cambio de semántica en ADK rompe en rojo, no en silencio.
5. `tests/test_atribucion.py`: evaluador automático que falla si el Director
   reporta una cifra de retorno, riesgo o correlación sin nombrar al
   especialista fuente.
6. Memorándum de convocatoria: la fase solicitar del gate renderiza la Orden
   Preparatoria de Sesión con el lenguaje de la propuesta (parámetros fijados,
   qué hará el comité, solicitud de confirmación) — revisión de orden, no peaje.
7. Limpieza de inferencia: eliminar todo nombre de modelo de docs y código;
   config.yaml declara niveles y asignaciones (nivel_1, nivel_2, nivel_3).

## Definition of Done
make check verde con los dos tests nuevos; demo en adk web documentada en el PR
(apertura con mesa, consulta con ficha, «¿qué tenemos?»); grep de nombres de
modelos fuera de config.yaml devuelve vacío; Estado actualizado; PR.

## Estado
Cerrado el 2026-09-20 (rama `sprint/S9-visibilidad`, PR contra `main`). Tres hitos con checkpoint
del usuario: (1) contrato y tool de la mesa, (2) ficha, prefijo y orden del comité, (3) gate,
atribución y limpieza de nombres.

### Logrado
- **Mesa de trabajo** (`contracts/mesa_trabajo.py`, `tools/mesa.py`; ADR-016, aceptada): la
  mesa es una PROYECCIÓN del estado de sesión, armada al consultarla desde los mismos contratos
  sellados que leen las herramientas; no se persiste ni la escribe nadie más. `obsoleto` es por
  ítem y se deriva del sello de cada uno con la regla de `exigir_sello`; el contrato rechaza una
  mesa que llame vigente a algo sellado con otro universo (las vistas siguen la regla de
  `construir_candidatos`: refrescar una cap no las toca). `consultar_mesa_trabajo` reemplaza a
  `diagnosticar` en la apertura, re-adopta el universo del disco y, con `vista="sala"`, da el
  roster desde los nombres reales de tools y sub-agentes (`componer_sala`: una herramienta sin
  silla impide construir el equipo). La tabla avisa cuántos elementos están obsoletos.
- **Ficha de origen, prefijo y Orden Preparatoria, entregados por código** (ADR-017, aceptada):
  tres callbacks del Director (`agents/director/anexos.py`). Tras cada herramienta se arma la
  ficha (especialista desde `ATIENDE`, herramienta, sello, cifras clave, etiqueta) y se retira de
  la salida el bloque ya redactado; al cerrar el turno se anexan al texto; y se recortan del
  historial que ve el modelo. Solo una corrida aprobada por el comité va sin `⚠ NO VALIDADO ·`.
  `solicitar` renderiza la orden desde el `ResumenComite` (`orchestrator/memorandum.py`): el
  contrato del acta no cambió.
- **Gate blindado** (`tests/test_gate_security.py`; enmienda a ADR-014): sobre el Runner real se
  fija la semántica de ADK de la que depende el gate (un `invocation_id` por turno del usuario,
  eventos en orden). Como pide el spec, el token ahora vale SOLO en el turno inmediatamente
  posterior a la orden (`_turno_anterior`, leído de los eventos); toda falta a la secuencia es
  una `ViolacionGateError` controlada: sin solicitud, mismo turno, turnos de por medio, cambio de
  universo, token ya usado. La secuencia legítima corre y deja un acta.
- **Atribución** (`tests/test_atribucion.py`): evaluador `cifras_sin_atribuir` —una cifra de
  retorno, riesgo o correlación debe nombrar en su párrafo a su fuente; una lista hereda la de
  su encabezado; el Director no es fuente—, el mismo que usa el evalset como criterio
  `cifras_atribuidas`. Una narración que suelta la cifra sin fuente falla aunque la ficha venga
  anexada. El cableado del Director pide la atribución en la misma frase.
- **Inferencia por niveles y limpieza de nombres** (ADR-018): `config.yaml: inferencia`
  (nivel_1 con clase cliente, modelo y secreto; nivel_2 sin asignar; nivel_3 determinista;
  asignaciones por agente). `resolver_modelo(config, agente)` carga la clase cliente por
  `importlib`. Se reescribieron 46 archivos (código, tests, scripts, Makefile, ADRs y Estados de
  S3-S8, la propuesta v2 §9) y dos ADRs cambiaron de nombre de archivo. `make nombres` y
  `tests/unit/test_nombres_de_modelos.py`: **vacío**. La lista de marcas vetadas vive en
  `config.yaml`, así que ni el test las escribe.
- **Evalset del Director**: de 19 a 22 casos (`que_tenemos`, `quien_esta_en_la_sala`,
  `sesion_visible` de seis turnos) y tres criterios nuevos (`cifras_atribuidas`,
  `sin_bloques_imitados`, y los textos de ficha/orden en los casos existentes). Conductas malas
  guionadas nuevas: describir la mesa de memoria, cifra sin fuente, rehacer el roster.
- `make check` verde: 670 tests (85 nuevos), con los dos tests que exige el DoD dentro de
  `make test`.

### Evidencia contra el modelo real (Nivel 1, temperatura 0.2, 2026-09-20)
- **`make eval-director`**: 21/21 con los criterios de atribución (antes del caso largo) y
  **22/22** con `sesion_visible` y `sin_bloques_imitados`. Tras el último ajuste (ver hallazgo),
  los casos afectados se re-corrieron: 5/5, 4/5, 2/2, 2/2. El único fallo fue del CRITERIO, no
  del Director: veté la palabra "token" y el Director escribió "el token quedó registrado
  internamente" sin mostrarlo; se retiró ese veto (la lección de S8: leer la conversación antes
  de tocar nada). Sin tocar nada más, el Director ya atribuye: "El Estadístico estimó que la
  correlación…".
- **Demo en adk web** (servidor real `adk web apps`, app `equipo`, datos reales; transcripción en
  `runs/demos/s9_adk_web/transcripcion.md`): «hola» → mesa anexada (verificado también en la UI:
  la tabla renderiza como tabla); «¿qué correlación hay entre VOOG y VB?» → "El Estadístico
  estimó…" + ficha con cinco líneas `⚠ NO VALIDADO ·`; cartera 50/30/20 → ficha del Escéptico;
  «¿qué tenemos hasta ahora?» → mesa con Estimación y Diagnóstico vigentes y prefijados;
  «¿quién está en la sala?» → siete sillas con sus herramientas; «convoca al comité» → Orden
  Preparatoria completa. Un bloque del código por turno, ninguno del modelo.

### Hallazgo de la demo (el más importante del sprint)
La primera demo de seis turnos falló de una forma que ningún eval de un turno mostraba: desde el
cuarto turno el Director IMITABA los bloques —rehízo la tabla de la mesa, duplicada con la del
código y **sin** el prefijo de no-validado; escribió su propia "Ficha de origen"— porque los veía
en su historial como texto suyo. Es la erosión que el sprint quería evitar, reintroducida por el
propio mecanismo. Arreglo: el modelo no ve lo que anexó el código (marca invisible + recorte en
`before_model_callback`); fijado por test de integración y por el caso `sesion_visible`.
Segunda vuelta del mismo hallazgo: dejé una nota en el historial en lugar del anexo ("aquí el
sistema anexó bloques…") y el modelo la REPITIÓ al final de su respuesta. Se recorta sin dejar
nada: lo que el modelo ve al final de sus propios turnos, lo reproduce.

### Desviaciones del spec
- La mesa no es un registro escrito por cada herramienta (propuesta v2 §5) sino una proyección
  (ADR-016); se omitieron `ultimo_diagnostico_id` y `vistas_activas_hash` (nada los consume),
  `categoria` y `origen` son enums, y hay una categoría más (Carteras) y una silla "Comité formal".
- Los dos tests del DoD viven en `tests/` (como los nombra el spec), no en `tests/unit/`; el
  Makefile los incluye en `make test`.
- La lista de marcas vetadas y las excepciones de tooling viven en `config.yaml`. Excepción
  declarada: el archivo de instrucciones del asistente de código y su carpeta de ajustes, cuyos
  nombres impone la herramienta.

### Pendiente / futuro
- Probar en `adk web` con el interruptor de streaming: el anexo va en la respuesta final, no en
  los fragmentos parciales; no se verificó con streaming activo.
- El Director a veces cita cifras con todos sus decimales (0.757847…): es la cifra exacta de la
  herramienta; si molesta, que las herramientas redondeen en su resumen (no el LLM).
- Las restricciones ajustadas por el usuario que un cambio de universo retira no aparecen como
  "obsoletas" en la mesa (desaparecen; lo declara `resultados_obsoletos` en el momento).
- El acta del comité no está en la mesa (decisión del checkpoint 1: la mesa es lo que está en
  juego antes de operar). S11 puede añadir los hitos del comité como categoría.
- Tras el merge, dev queda con otro `config_hash` (sección `inferencia`): el replay rechazará las
  corridas anteriores, como está diseñado.
- Siguen abiertos de S8: latencia del saludo (ahora una llamada a la mesa), `TiingoFuente(hoy=…)`
  fijada al arrancar, promoción de `equipo` a prod.

### Aprendizajes
- **Un eval de un turno no ve lo que el historial le hace al modelo.** Todo bloque que el código
  añade a la respuesta es, para el LLM, un ejemplo de cómo responder. Si no debe imitarlo, no debe
  verlo. La demo larga pagó sola.
- "Entregar por código" tiene dos mitades: que el bloque llegue al usuario y que NO llegue al
  modelo. La primera sin la segunda empeora las cosas.
- Derivar en vez de registrar (la mesa como proyección) dio la obsolescencia por ítem sin tocar
  ninguna herramienta, y un test que compara la mesa con lo que la herramienta rechaza de verdad.
- Una marca invisible pegada al inicio de una línea rompe lo que dependa de "empieza con": el
  criterio de encabezados no contaba el del código hasta que la marca tuvo su propia línea.
- El spec decía "turno inmediatamente anterior" y la implementación de S8 decía "otro turno": leer
  el spec contra el código, no contra el recuerdo del código.
- Retirar nombres de modelos de 46 archivos fue mecánico salvo en tres sitios donde el nombre ERA
  el contenido (el ADR que comparaba versiones, un secreto de GCP, una clase importada): ahí la
  solución fue mover el dato a `config.yaml`, no reescribir la frase.
