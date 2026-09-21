# Sprint 11 — Comité Audible y Experiencia Fintual (Doc: Sprint 3)

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

## Alcance
1. `contracts/hitos_comite.py` (`HitoComite`: timestamp, fase, iteracion,
   evento, detalle). `pipeline.py` emite hitos a `pipeline_milestones` en el
   estado compartido Y a `runs/<id>/bitacora.jsonl` mientras corre.
2. Transmisión en vivo: verificar las capacidades de streaming vigentes de ADK;
   si el chat puede mostrar hitos durante la llamada, se implementa; si no, la
   garantía mínima es doble — bitácora legible en tiempo real desde otra
   terminal, y la respuesta del Director al cerrar abre con la cronología
   completa narrada (fases, iteraciones, vetos con motivo, tiempos).
3. `fintual/cash_flow_alloc.py` (Nivel 3): rebalanceo por flujos — aportes y
   dividendos se asignan 100% a los activos bajo su objetivo; cero ventas por
   defecto; salida como Plan de Compra Neta en USD fraccionados.
4. `fintual/tax_filter.py` CONSULTIVO (enmienda §2): emite escenarios
   etiquetados («Costo fiscal estimado: $X CLP»), reconoce tax-loss harvesting
   como estrategia legítima, disclaimer inyectado en la salida («estimación
   algorítmica, no asesoría tributaria o financiera; valida el tratamiento de
   dividendos extranjeros con tu contador»), y mecanismo de Override del
   usuario (forzar la orden pese a la advertencia) que queda REGISTRADO en el
   acta con la advertencia que cruzó. El sistema nunca ejecuta: produce el plan
   que el usuario ejecuta en la app.
5. Unificación de experiencia: apps/equipo es la única interfaz; el modo
   comando sobrevive como target de despliegue y make (ritual mensual sin
   conversación), no como visor — la bitácora eliminó su razón de existir.

## Definition of Done
Una corrida de comité muestra la cronología (en vivo o al cierre según lo que
ADK permita, documentado cuál); bitacora.jsonl legible en paralelo; un plan de
compra generado desde un aporte simulado con no-trade zones y tax guard
consultivo, con su disclaimer y un caso de Override registrado en acta;
make check verde; Estado; PR.

## Estado
Cerrado el 2026-09-20 (rama `sprint/S11-comite-fintual`, PR contra `main`). Tres hitos con
checkpoint del usuario: (1) hitos y transmisión —ADR-021 aprobada tras ver la evidencia del
spike—, (2) plan de compra y filtro consultivo —ADR-022 aprobada: reparto proporcional al déficit
y cota por defecto—, (3) unificación.

### Qué permitió ADK (la pregunta del sprint)
**Hitos EN VIVO en el chat, y además la cronología al cierre.** La documentación (adk.dev, "Live →
Tools") solo ofrece *streaming tools* en modo live/bidi; no documenta cómo emitir desde una tool
en `run_async`/SSE. El paquete instalado (google-adk 2.9.1) sí lo permite: toda invocación tiene
una cola de eventos (`InvocationContext._enqueue_event`) que el Runner consume, y una tool la
tiene a mano. Spike medido sobre el Runner real, `/run_sse` y la interfaz: un evento normal
aparece como burbuja propia mientras la tool corre y persiste en la sesión; uno `partial` llega
en vivo pero la interfaz lo amontona y lo borra al cierre. Se implementó el persistido (ADR-021),
con tres cercos por ser API privada: test de semántica sobre el Runner real, modo degradado
automático e interruptor en `config.yaml`.

### Logrado
- **Hitos del comité** (`contracts/hitos_comite.py`, `orchestrator/bitacora.py`): `HitoComite`
  (timestamp con zona, fase, iteración, evento, detalle; un veto sin motivo no valida) y
  `CronologiaComite` (orden temporal, rondas que no retroceden). `pipeline.py` emite apertura →
  views → estimación → propuesta N → VETO con motivo | APROBADA → iteraciones agotadas → acta, a
  `pipeline_milestones` Y a `runs/<id>/bitacora.jsonl` (una línea por hito, mientras corre). El
  detalle lo redacta el código desde los contratos validados: ningún LLM escribe un hito. Las
  ramas paralelas no escriben la lista (el delta de ADK es por clave): sus hitos los deja un nodo
  tras la unión. Los hitos NO entran en `RunState` (llevan reloj; romperían el replay).
- **Transmisión** (`tools/hitos_en_vivo.py`, ADR-021): `convocar_comite` reenvía cada hito a la
  cola de la invocación del Director (autor `comite`); el modelo NO los ve (marca invisible +
  recorte en `ocultar_anexos_al_modelo`); la cronología narrada (fases, rondas, vetos con motivo,
  tiempos) se anexa por código al cierre SIEMPRE; si la corrida revienta, lo ya deliberado queda
  en la sesión del Director. `make bitacora [RUN=…]` sigue la bitácora desde otra terminal.
- **`fintual/cash_flow_alloc.py`** (Nivel 3, puro): flujo (aporte + dividendos) 100 % a lo que
  está bajo objetivo, proporcional al déficit, al centavo por mayor residuo; `PlanCompraNeta` no
  tiene dónde escribir una venta; bandas de inercia ANTES y DESPUÉS del flujo. Test de propiedad
  con hypothesis (que encontró dos bordes reales de redondeo al centavo).
- **`fintual/tax_filter.py`** CONSULTIVO (puro): escenario por defecto "sin ventas" (lo exige el
  contrato) y, por cada activo que sigue sobreponderado fuera de banda, vender hasta la banda /
  hasta el objetivo con «Costo fiscal estimado: $X CLP»; una venta con pérdida se marca tax-loss
  harvesting (costo 0, pérdida realizable) y las pérdidas latentes se listan aunque nadie venda.
  Supuestos del usuario en `config.yaml: fintual.tributario` (marcadores editables); sin costo de
  adquisición declarado el costo es una COTA y la salida lo dice. El disclaimer operativo va
  inyectado por código y los contratos rechazan cualquier otro texto en su lugar.
- **Override** (`tools/plan_operativo.py`): `forzar_orden(escenario, token)` con la custodia del
  gate (otro turno, token de ese plan, un uso, nada cambió); el LLM pasa un id, nunca un monto.
  `ActaOperativa` junto al acta del comité (`runs/<run_id>/acta_operativa_<id>.json`) con la
  advertencia cruzada LITERAL, los dos turnos y sus horas; `ejecutado_por_el_sistema` solo admite
  `False`. El monto del aporte es la única cifra que llega por un argumento de LLM y solo vale si
  el usuario la escribió (`tools/procedencia.py`, la custodia de S10 generalizada).
- **Unificación**: `apps/` = solo `equipo` (lo único que sirve `adk web`). El modo comando pasó a
  `comando/pipeline`: `make comando` (imprime los hitos en vivo), `make deploy-prod` y, en el
  contenedor de dev, API junto al equipo para `make corrida-dev` y el replay. El agente del eval
  del analista pasó a `tests/eval/agentes/`. `tests/unit/test_interfaz_unica.py` lo fija.
- `test_fronteras.py` extendido (archivos de S11 bajo vigilancia; `fintual/` no lee reloj ni
  disco). Evalset: de 27 a 32 casos, criterio nuevo `hitos_en_vivo`, y la cronología, el plan y
  el override entran en `sin_bloques_imitados`. `make check` verde: 824 tests (80 más que en S10).

### Evidencia contra el modelo real (Nivel 1, 2026-09-20)
- **Demo en `adk web`** (servidor real, datos reales; `runs/demos/s11_adk_web/transcripcion.md`,
  con el tiempo de LLEGADA de cada evento por SSE): «convoca al comité» → orden → «sí, confirmo»
  → corrida `20260920T231829_624242Z` con un **veto real**: ronda 1 VOOG 70 % → VETO
  (`concentracion_hhi_maxima: 0.5584 vs umbral 0.55`), ronda 2 VOOG 60 / VB 36 → APROBADA. Los
  ocho hitos llegaron a los 2.5, 10.1, 10.1, 15.3, 15.4, 33.4, 33.5 y 43.7 s de una llamada que
  retornó a los 43.8 s; en la interfaz, una burbuja por hito. `make bitacora`, en otro proceso,
  imprimió las mismas ocho líneas mientras corría. La respuesta cerró con la cronología
  («2 rondas Constructor ⇄ Escéptico, 1 veto, duración total 00:41»).
- En la misma sesión: «aporté 500 dólares» → Plan de Compra Neta sobre la cartera recién
  aprobada (US$ 500.00 a VB, ventas US$ 0.00, VOOG y BNS sobreponderados fuera de banda "no se
  vende", IBIT HOLD), cinco escenarios etiquetados como COTA, supuestos y disclaimer; «fuerza
  `VOOG:vender_hasta_banda`» → override registrado en
  `runs/20260920T231829_624242Z/acta_operativa_…json` con la advertencia literal.
- `scripts/demo_plan_compra.py` (sin LLM, mismas operaciones, costos de adquisición simulados):
  el checkpoint 2; muestra además ganancia parcial y la pérdida latente de IBIT.
- **`make eval`**: analista **11/11** y Director **32/32**. Camino: los 5 casos nuevos 5/5 a la
  primera → (tras la nota del hallazgo 1) 2/3 y 3/3 en los casos del plan → `make eval` completo
  **31/32**: falló `comite_se_ve_deliberar` porque ESA corrida tuvo un veto y las cifras de la
  ronda vetada (que la cronología anexada muestra) no estaban en la salida de la herramienta
  (hallazgo 2) → `convocar_comite` devuelve ahora la `deliberacion` como dato, con un test
  guionado CON veto que reproduce el fallo sin el arreglo → caso 3/3 → `make eval` **32/32**.

### Hallazgos
1. **El Director re-narra el plan con su propio encabezado «Plan de Compra Neta»** y lista los
   escenarios con sus cifras, duplicando el bloque del código (patrón de S9/S10), e invitaba a
   forzar escenarios. Con la regla pegada al dato (`NOTA_PLAN`) bajó de 2 de 3 a 1 de 5 muestras;
   no desapareció. Se mide una vez, en `plan_compra_aporte`. Custodia candidata: que el Director
   no reciba las cifras de los escenarios (solo ids) y que `cifras_respaldadas` no cuente lo que
   anexa el código.
2. `cifras_respaldadas` mira también los bloques anexados: las cifras del bloque deben estar en
   la salida estructurada de la tool. Por eso `plan_compra` devuelve pesos, efectos y supuestos,
   y `convocar_comite` la `deliberacion` (que además le deja al Director explicar un veto de
   una ronda anterior: `razones_rechazo` solo traía las de la última). Apareció solo cuando una
   corrida real tuvo veto: un eval verde no cubre los caminos que el modelo no tomó ese día.
3. El efecto `acta_creada` del arnés contaba cualquier carpeta en `runs/`: un acta operativa lo
   disparaba. Ahora busca el `run_state.json` del comité.
4. Copiar en profundidad un `LlmRequest` entero en el LLM falso (arrastra tools y dataframes)
   colgó la suite en el caso del Director en bucle: se guardan solo los contenidos.
5. `str.capitalize()` baja los tickers («voog, bns»): lo cazó leer la salida de la demo.

### Desviaciones del spec
- «La respuesta del Director ABRE con la cronología»: va ANEXADA al final, como todo bloque del
  código (ADR-017); con los hitos en vivo, la apertura ya ocurrió en el chat.
- `fase` y `evento` de `HitoComite` son enums, no `str`; se añadió `CronologiaComite`.
- El Override no toca `RunState`: vive en `ActaOperativa`, junto al acta (ADR-022).
- Añadidos que el spec no pedía: `make bitacora`, `make comando` con hitos en vivo,
  `scripts/demo_plan_compra.py`, pérdidas latentes, `reinversion_usd` (el producto de una venta
  forzada se reasigna con la misma regla), `corridas.transmitir_hitos_en_vivo`.
- `config.yaml` gana `corridas.transmitir_hitos_en_vivo` y `fintual.tributario`: cambia el
  `config_hash`; el replay rechazará las corridas anteriores, como está diseñado.

### Pendiente / futuro
- **Costos de adquisición por sesión**: hoy solo se declaran en `config.yaml`. Inyectarlos
  temporalmente en la conversación (para una operación grande) es una cifra más entrando por un
  argumento de LLM: necesita su custodia de procedencia y que NO se persista.
- No verificado: que Agent Engine (prod) y Cloud Run entreguen el SSE en vivo (la cronología al
  cierre lo cubre). Revisar `_enqueue_event` en cada subida de versión de ADK (ADR-021).
- La mesa de trabajo no muestra la cronología ni el plan operativo vigente (pendiente de S9).
- `portafolio.valor_usd` y `pesos_actuales` siguen siendo manuales (pendiente de S10): el plan es
  tan actual como ellos. Los dividendos los informa el usuario; no se leen de la fuente.
- El filtro es grueso por diseño (un tramo, un tipo de cambio, sin créditos por impuestos
  pagados en el extranjero ni reglas de compensación de pérdidas).
- El primer despliegue de dev tras el merge estrena el layout `servidos/` del Dockerfile: se
  verificó en local con `adk api_server` (sirve `equipo` y `pipeline`), no con Docker.
- Siguen abiertos de S8-S10: latencia del saludo, `TiingoFuente(hoy=…)` fijada al arrancar,
  promoción de `equipo` a prod, tasa de cierres vacíos del modelo.

### Aprendizajes
- **"La documentación dice que no" no es "no se puede"**: el spike de una hora sobre el paquete
  instalado cambió el alcance del sprint (de cronología al cierre a hitos en vivo). Y usar una
  API privada exige pagar el cerco: test de semántica, degradación y un interruptor.
- Derivar los hitos de los contratos validados (no de texto de LLM) dio gratis que las cifras de
  un hito sean las del acta, y un test que lo compara.
- Un test de propiedad encuentra en segundos lo que un ejemplo no: el centavo del mayor residuo
  puede superar el déficit, y redondear un déficit lo puede borrar.
- La demo larga volvió a pagar sola (como en S9 y S10): el veto real, el encabezado duplicado y
  los tickers en minúscula no estaban en ningún test.
- Medir una conducta intermitente UNA vez, donde es el sujeto del caso, y anotar su tasa, es más
  honesto que duplicar el criterio o quitarlo en silencio.
