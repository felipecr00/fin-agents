# Sprint 10 — Nivelación del Equipo: Sub-Agentes Thin (Doc: Sprint 2)

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

## Nota formal de costo aceptado
El desdoblamiento temprano del Estadístico y el Escéptico requiere evaluar y
calibrar dos contextos de LLM adicionales antes de que la capa operativa esté
completamente madura. Justificación aprobada: resolver la opacidad del comité
monolítico desde el inicio mejora dramáticamente la adopción y auditabilidad
del sistema por parte del CIO.

## Alcance
1. `agents/estadistico/` y `agents/esceptico/`: LlmAgents thin (single_turn,
   Nivel 1 o el nivel que config asigne, temperatura baja), una tool cada uno
   (`estimar_mercado`, `diagnosticar_cartera`), prompt de rol según las
   justificaciones del diagrama aprobado (el Estadístico reporta siempre la
   confianza de su estimación; el Escéptico busca grietas y nunca emite
   veredicto fuera del comité). Los números salen solo de su herramienta.
2. Desmontar el ruteo plano del Director: de ~12 tools a ruteo jerárquico —
   personas (Analista, Estadístico, Escéptico), Gestor (transaccional, sin
   persona), comité. `test_director.py` verifica la delegación de roles.
3. `fintual/no_trade_zones.py` (Nivel 3, puro): bandas de inercia configurables
   (default ±5%); dentro de banda la orden es HOLD obligatorio.
4. `agents/fintual_data/`: evolución del Gestor con la tool
   `gestionar_datos_y_fricciones` — fechas ex-dividendo, cierres ajustados,
   traducción de pesos a montos fraccionados en USD (2 decimales).
5. Evalset extendido: los casos del Director re-corridos sobre el ruteo
   jerárquico + casos nuevos de delegación (pregunta de correlación → habla el
   Estadístico con atribución; «¿qué le preocupa de esta cartera?» → habla el
   Escéptico sobre el diagnóstico de su tool).

## Definition of Done
make check y make eval verdes; demo conversando con las tres personas; el
Director no ofrece capacidades sin herramienta (eval existente sigue verde);
nota de costo aceptado copiada en el Estado; PR.

## Estado
Cerrado el 2026-09-20 (rama `sprint/S10-personas`, PR contra `main`). Un checkpoint del usuario
antes de escribir código: ADR-019 y ADR-020, aprobados con las dos alternativas recomendadas.

### Nota formal de costo aceptado
El desdoblamiento temprano del Estadístico y el Escéptico requiere evaluar y calibrar dos
contextos de LLM adicionales antes de que la capa operativa esté completamente madura.
Justificación aprobada: resolver la opacidad del comité monolítico desde el inicio mejora
dramáticamente la adopción y auditabilidad del sistema por parte del CIO. **Costo medido en este
sprint**: una consulta a una persona pasa de 2 a 4 llamadas al modelo; calibrar las dos personas
y el cierre del Director tomó nueve corridas completas del eval real, varias parciales y dos
demos (ver hallazgos).

### Logrado
- **Personas thin** (`agents/persona.py`, `agents/estadistico/`, `agents/esceptico/`; ADR-019):
  `LlmAgent` `single_turn` con UNA herramienta (sin `transfer_to_agent`, fijado por test), nivel
  y temperatura desde `config.yaml`. Hablan ellas: su respuesta es un evento propio que el
  usuario lee (verificado en la interfaz de `adk web`); el Director recibe ese texto con la
  regla de no re-narrarlo y solo coordina. La ficha de origen la recoge la persona con el mismo
  callback de S9 y la anexa el Director: ninguna custodia se movió al prompt. El Estadístico
  reporta siempre la confianza de su estimación; el Escéptico busca grietas y nunca da veredicto.
- **Los pesos del usuario no pasan por el LLM de la persona**: `ConsultaEsceptico.pesos` →
  `before_tool_callback` del Director → estado → `diagnosticar_cartera()` sin argumentos. Con
  custodia de procedencia en código: solo valen los números que el usuario ESCRIBIÓ; si son los
  de la cartera de la mesa se mide la de la mesa con su procedencia real; lo demás se rechaza sin
  consultar a la persona. Sin pesos, «esta cartera» es la vigente de la mesa
  (`tools/objetivo.py`: la aprobada por el comité manda sobre la exploratoria del Constructor).
- **Ruteo jerárquico** (ADR-020): el Director pasa de 13 entradas planas a 8 en 4 grupos
  (personas, Gestor-Fintual, Constructor, comité, más la mesa). `INSTRUCCION` (spec literal de
  S8) no se tocó; el cableado se reescribió por grupos. `construir_candidatos` ya no obliga a
  conversar con el Estadístico: si no hay estimaciones, su herramienta las calcula y lo avisa.
- **Gestor-Fintual de una sola tool** (`tools/fintual.py`, `agents/fintual_data/`): sin LLM;
  `gestionar_datos_y_fricciones(operacion, …)` con las seis operaciones heredadas (mismo código
  y custodias: sello, obsoletos, prior neutral en dos turnos) y tres nuevas de solo lectura:
  `dividendos` y `cierres` (Tiingo diario: `divCash`, `close`, `adjClose`; una descarga por
  ticker en caché; solo historia) y `montos`. Un argumento ajeno a la operación se rechaza.
- **`fintual/` puro (Nivel 3)**: `no_trade_zones.py` (banda ABSOLUTA ±5 p.p. configurable,
  global y por activo; dentro de banda `HOLD` obligatorio; fuera, solo se señala) y `montos.py`
  (redondeo por mayor residuo: los montos suman exactamente el valor de la cartera). Contrato
  nuevo `PlanInercia` (rechaza una orden incoherente con su desviación); ningún contrato
  existente cambió. `test_fronteras.py` vigila `fintual/` y que las personas no importen el
  núcleo puro. `montos` no recibe cifras del LLM: objetivo de la mesa, cartera actual de config.
- **Evalset**: de 22 a 27 casos; claves `tool:operacion`; criterios nuevos `habla` y
  `no_repite_cifras`; los criterios de texto y `cifras_respaldadas` miran lo que el usuario LEYÓ
  (personas incluidas) y el texto de una persona no puede respaldar sus propias cifras.
- `make check` verde: 744 tests (74 más que en S9).

### Evidencia contra el modelo real (Nivel 1, 2026-09-20)
- **`make eval`**: analista 11/11 y Director **27/27**. Camino: 23/27 → 26/27 → 25/27 → 27/27 →
  (estabilidad: 3×8 y 3×4 casos de personas) → 25/27 → 26/27 → 27/27 → 27/27 (`make eval`) →
  26/27 tras el último ajuste de redacción (falso positivo del criterio de S8 en `capacidades`:
  «un universo que tú controlas en tiempo real»). Los 8 casos de alta pasaron en todas las
  corridas: **no hizo falta el plan B de ADR-020** (mutaciones planas).
- **Demo en `adk web`** (servidor real, datos reales y Tiingo real; transcripción en
  `runs/demos/s10_adk_web/transcripcion.md`): mesa anexada → habla el **Estadístico** (0.76, 59
  observaciones, intervalos, método) → habla el **Analista** → propuesta del Constructor con su
  ficha → habla el **Escéptico** sobre «esta cartera» = la propuesta del Constructor, sin
  veredicto → `montos` (VOOG y BNS sobreponderados, VB subponderado, IBIT HOLD; «no constituye
  una orden de compra o venta») → último ex-dividendo de BNS 2026-07-07, sin proyectar el
  próximo → roster con las tres sillas que conversan.

### Hallazgos (todos vistos con el modelo real; ninguno lo mostraba el LLM guionado)
1. **El Director re-narraba las cifras de la persona** con la regla solo en el cableado. Arreglo:
   la regla viaja JUNTO al texto que recibe (`resultado_para_el_director`).
2. **El Director copió los pesos de la mesa y se los pasó al Escéptico** como si fueran del
   usuario (procedencia falsa, y cifras por argumentos de LLM). Arreglo: custodia en código.
3. **`FUERA_DE_BANDA` se convirtió en «Acción indicada: Vender»**. Arreglo en el dato: cada
   activo trae `situacion` y `accion` («ninguna: no indiques comprar ni vender»), la nota lo
   explica, y el caso del eval veta comprar/vender salvo negados.
4. **El Director habló POR el Escéptico sin consultarlo**. Arreglo: regla de cableado y
   `tools_obligatorias` en el caso. Es prompt, no custodia: vigilarlo (ver pendientes).
5. **Cierre final vacío del modelo** (1 vez en el eval, 3 de 8 turnos en la primera demo): la
   ficha no se anexaba (el callback exigía texto) y en el turno siguiente el modelo contestó la
   pregunta ANTERIOR. Arreglo: la ficha se entrega igual y un cierre vacío se reemplaza por una
   línea determinista; el historial nunca guarda un turno mudo.
6. **Uso natural que la tool rechazaba**: «último ex-dividendo de BNS» llega con `ticker`.
   `dividendos` y `cierres` lo admiten (solo activos del universo).
7. Regresión mía, cazada por un caso de S8: «no la resumas» (la orden del comité) hizo fallar
   `escalar_sin_confirmacion` 2/2; se reformuló.
8. Se probó admitir cifras truncadas en `cifras_respaldadas` y un test existente mostró que
   0.7578 pasaba a respaldar "0.75": revertido y fijado por test. El detector no se afloja.

### Desviaciones del spec
- La propuesta v2 §4.3 hacía del Gestor un sub-agente thin; el spec de S10 dice «sin persona» y
  así quedó (ADR-020): el alta pregunta entre turnos y un `single_turn` no puede.
- `agents/fintual_data/` arma la tool y su cableado; la FunctionTool vive en `tools/`, como todas.
- «Fechas ex-dividendo» es HISTORIA: la fuente no publica calendario futuro y no se proyecta.
- `montos` es informativo: señala, no ordena. El cálculo de aportes (sin ventas), el filtro
  tributario consultivo y el override son S11 y consumirán `PlanInercia`.
- `agents/director/anexos.py` se movió a `agents/anexos.py` (lo usan también las personas).
- Se añadió `agentes.temperatura_personas` y la sección `fintual` a `config.yaml`: cambia el
  `config_hash`, así que el replay rechazará las corridas anteriores, como está diseñado.

### Pendiente / futuro
- El Director a veces REHACE el roster como tabla propia (sin encabezado, así que
  `sin_bloques_imitados` no lo ve). Es el patrón de S9; candidato: contar tablas del Director en
  turnos con anexo.
- «No hablar por una persona» y «no dar valores de ejemplo» viven en el prompt. Si reaparecen,
  custodia posible: que el Director no vea las cifras de la persona (solo un resumen sin números).
- Tasa de cierres vacíos del modelo: medirla; hoy está mitigada, no explicada.
- La persona redondeó una vez 0.28816 como 28.81 % (último dígito). `cifras_respaldadas` lo
  caza; se añadió la regla de redondeo, sin garantía.
- El panel de preview del asistente no puede leer el directorio del proyecto y arranca `adk web`
  sin `.env` completo (sin Tiingo): la demo se hizo levantando el servidor desde un shell.
- `portafolio.valor_usd` y `pesos_actuales` son manuales en `config.yaml`: `montos` es tan
  actual como ellos. S11 debería leer la cartera real de otra fuente.
- Siguen abiertos de S8-S9: latencia del saludo, `TiingoFuente(hoy=…)` fijada al arrancar,
  promoción de `equipo` a prod, streaming en `adk web`.

### Aprendizajes
- **Una regla pegada al dato pesa más que la misma regla en el cableado.** La nota junto al
  texto de la persona y los campos `accion`/`situacion` en `montos` cambiaron la conducta donde
  el párrafo del prompt no lo había logrado.
- **Si una cifra puede llegar por un argumento de LLM, llegará.** Se le dijo al Director que
  omitiera `pesos` y los copió igual; solo la verificación de procedencia en código lo cerró.
- Una capacidad nueva cambia casos viejos: `cierres` apareció en «fuera de alcance» y
  «monitoreo de dividendos» en «capacidades». Re-correr TODO el evalset, no solo lo nuevo.
- La demo larga volvió a pagar sola (como en S9): los cierres vacíos y el `ticker` de
  `dividendos` no aparecían en ningún caso de eval.
- Leer la conversación antes de tocar el criterio separó cinco fallos de conducta de seis de
  criterio; y cuando aflojar un criterio rompió un test existente, el test tenía razón.
- Un spike de una hora sobre el ADK instalado (qué recibe el padre de un `single_turn`, qué
  tools le declara ADK) evitó diseñar la ficha y los pesos sobre supuestos falsos.
