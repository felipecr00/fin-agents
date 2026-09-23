# ADR 023: Lienzo en blanco — el universo de la sesión se separa del guardado

- Fecha: 2026-09-21
- Sprint: tarea intermedia entre S11 y S12 (`chore/lienzo-blanco`)
- Estado: aceptada (2026-09-21: brief del usuario con sus enmiendas; la separación sesión/guardado
  se decidió en sesión, con la evidencia de abajo)

## Contexto
La sesión de `apps/equipo` arrancaba con VOOG, BNS, IBIT y VB cargados: `cargar_universo` adoptaba
al primer turno el universo del Gestor y la instrucción del Director ordenaba presentarlo. El
usuario quiere un lienzo en blanco: ningún activo, cálculo ni restricción hasta que él defina sus
tickers; el guardado se menciona en una línea y se carga solo si lo pide (Decisión A). El modo
comando sigue tomando su universo del almacén, y golden, fixture, propiedad del prior y tests de
custodia son intocables.

El obstáculo: había UN solo universo, persistido en `data/universo.json` (versionado; lo usan el
modo comando, dev y prod). La sesión era una copia: toda alta lo reescribía y la mesa,
`diagnosticar` y `aceptar_prior_neutral` lo re-adoptaban del disco. Con ese mecanismo, una lista
nueva en una sesión limpia o se SUMA al guardado (no es lienzo en blanco) o lo REEMPLAZA (una
conversación exploratoria cambiaría el universo del ritual mensual y los datos en git).

## Decisión
1. **Dos clases de universo.** El GUARDADO (el del almacén) y el de una SESIÓN efímera, que vive
   solo en el estado de sesión. `CLAVE_ORIGEN_UNIVERSO` dice cuál rige: `guardado` (sus cambios se
   persisten, como en S7-S11; sin la clave rige este modo: nada anterior cambia) o `sesion`
   (sin universo en el estado = mesa limpia).
2. **El Gestor puro opera sobre la base que recibe** (`base=GUARDADO | Universe | None`). Con una
   base de sesión devuelve el universo nuevo y NO toca `universo.json` ni su historial. Las series
   descargadas quedan en `data/series/` como caché (igual que ya las deja `retirar`), con una
   excepción dura: **desde una sesión jamás se re-descarga ni se sobrescribe la serie de un activo
   del universo guardado**; entra con su serie, su diagnóstico y su cap congelada. Solo
   `make update-prices` toca esas series, con las barreras de ADR-011.
3. **`apps/equipo` abre limpia** (`crear_director(..., mesa_limpia=True)`): el callback ya no
   carga nada y marca la sesión como efímera. El valor por defecto de la fábrica sigue adoptando
   el guardado: es lo que usan los tests de custodia, que no son sobre la apertura y no se
   tocaron. El modo comando (`comando/pipeline`) no pasa por aquí.
4. **La mesa limpia no tiene nada prefabricado**: `consultar_mesa_trabajo` responde
   `universe_version: null`, `activos: []`, `items: []`, y el bloque del código menciona el
   guardado con sus tickers SIN cargarlo. No se tocó el contrato `MesaDeTrabajoState`: una mesa
   limpia es la ausencia de mesa, no una mesa vacía.
5. **Cargar el guardado es una operación explícita** (`cargar_guardado`), y devuelve sus
   diagnósticos. Una lista nueva crea el universo de la sesión solo con esos activos.
6. **Alta por lista con la cascada de siempre** (ADR-013): `resolver(tickers)` diagnostica todos y
   da la ventana común SI ENTRAN TODOS (quién la limita); `incorporar(tickers)` da de alta lo que
   no requiere una decisión y deja en `pendientes_de_prior` lo que no tiene cap en la fuente, con
   la pregunta de tres opciones; cada pendiente entra después, uno por uno. La custodia de
   `aceptar_prior_neutral` (turno posterior, todo-o-nada) es la misma sobre un universo de sesión.
   La advertencia de ventana es el primer ítem de la mesa porque la mesa es una proyección
   (ADR-016) del universo de la sesión: sale estrictamente de los tickers ingresados.
7. **Custodias en código**: (a) sin universo, el `before_tool_callback` del Director responde
   `SinUniversoError` a toda herramienta que no sea la mesa o la configuración del universo
   —también a los sub-agentes y al gate del comité—, y cada herramienta lo responde por sí misma
   (`leer` del estado); el Analista ya no puede caer al universo de `config.yaml`. (b) Un ticker
   que el usuario no escribió en la sesión no entra por `incorporar` (`tools/procedencia.py`): el
   Director no completa la lista ni propone activos.
8. **La instrucción aprobada del Director cambió** (decisión del usuario): la viñeta "si existe un
   universo previo, preséntalo y pregunta" pasa a mesa limpia + mención del guardado sin
   cargarlo, y se añade la prohibición de sugerir activos no provistos.

## Alternativas descartadas
- **La lista reemplaza al guardado**: cambio pequeño, pero una sesión exploratoria alteraría en
  silencio el universo del modo comando, de dev y de prod, y "usa el guardado" pasaría a ser "lo
  último que alguien escribió".
- **La lista se suma al guardado**: no es lienzo en blanco.
- **Separada + operación "guarda este universo"**: útil, pero reemplaza lo que usa el modo comando
  y merece su propia custodia de dos turnos; queda pendiente.
- **Cambiar el valor por defecto de `crear_director` a mesa limpia y adaptar los tests de
  custodia**: los tests intocables se romperían por algo que no prueban.
- **Un almacén de series aparte para las sesiones**: evitaría archivos sin versionar en
  `data/series/`, a costa de un proveedor de precios de dos directorios. No lo justifica todavía.
- **Una mesa vacía en el contrato** (`universe_version: None`, `items: ()`): relajaría invariantes
  ("exactamente un Universo, el vigente") que custodian todas las demás mesas.

## Consecuencias
- Una sesión nueva no calcula nada hasta tener universo; el comité corre sobre el universo de la
  sesión (ya lo soportaba desde S8) y su acta registra ESE universo.
- Un universo de sesión se pierde al cerrar la sesión. Guardarlo es trabajo pendiente.
- Las series de activos ajenos al guardado quedan en `data/series/` como archivos SIN versionar:
  son caché; no se comitean salvo que el activo entre al guardado. `make update-prices` no las
  actualiza: cada alta las vuelve a descargar.
- Hace alcanzables universos de uno o dos activos: los límites por defecto (techo 70 %) son
  infactibles ahí. La mesa lo dice en su fila de restricciones y las herramientas responden el
  error de dominio de siempre; antes la mesa lanzaba una excepción.
- Los evals corren siempre con el Director de producción (mesa limpia). Los casos que no son
  sobre la apertura declaran `sesion: guardado`: el arnés deja la sesión como la deja
  `cargar_guardado`.
