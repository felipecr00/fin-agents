# Sprint 7 — Universo dinámico y Gestor de Datos

> Spec fuente del sistema final: `docs/prompts/director.md`.
> Prerrequisitos: S6 cerrado (TiingoPriceProvider operativo) y golden test sobre
> fixture congelado. El Director conversacional llega en S8: este sprint es 100%
> determinista.
> La política del prior de equilibrio YA ESTÁ DECIDIDA (ver §4): este sprint la
> implementa, no la debate. El ADR se redacta documentando la decisión tomada.

## Objetivo
Que el núcleo deje de asumir un universo fijo: los especialistas deterministas
operan sobre un universo de sesión validado por el Gestor de Datos, con prior de
equilibrio auditable por procedencia.

## Alcance

### 1. Contratos nuevos y modificados
- `AssetDiagnostic`: ticker resuelto, nombre, moneda, fecha de inicio y fin de
  datos, frecuencia, huecos, meses disponibles, advertencias ("ventana corta:
  stress 2022 no aplica"), apto/no apto, y el bloque de prior (la cap congelada
  del activo; los cuatro campos juntos o ninguno): `prior_cap`,
  `prior_provenance: fuente | usuario` (de dónde viene la cap: propiedad del
  activo), `prior_fuente_detalle` (qué endpoint o qué metodología del usuario),
  `prior_as_of` (fecha del valor).
- `Universe`: activos con diagnósticos, versión (hash del contenido, incluye las
  caps congeladas y `prior_neutral_aceptado`), origen de cada activo (config
  inicial / agregado en sesión). `neutral` NO es procedencia de un activo: es la
  resolución del vector completo (`Universe.prior_neutral_aceptado` →
  `PriorSnapshot`), y solo ahí aparece. (Corregido en S7; ver ADR-013,
  "Refinamiento".)
- `SessionConstraints`: restricciones vigentes con su origen (default de config /
  ajustadas por el usuario).
- `QuantEstimates`, `CandidatePortfolios`, `ValidationReport`, `RunState`: ganan
  `universe_version`. `RunState` gana además el snapshot completo del prior:
  vector de pesos w_mkt, procedencia por activo, y la tabla de retornos
  implícitos π resultante.

### 2. Gestor de Datos (src/investmentsys/data_manager/ — determinista)
- `resolver(ticker)`: valida existencia vía metadata de Tiingo; devuelve
  diagnóstico o error claro (ticker inexistente, sin datos, moneda no soportada).
  Cuando la fuente expone capitalización del tipo correcto (acciones), la captura
  con procedencia `fuente`; cuando no (ETFs, exóticos), deja el bloque de prior
  pendiente — la elicitación conversacional es de S8; en S7 la cap de procedencia
  `usuario` entra como argumento de `incorporar`.
- `incorporar(ticker, prior_cap=None, prior_metodologia=None)`: descarga la serie
  mensual ajustada, aplica las validaciones de sanidad del S6, congela la cap
  (de la fuente o del argumento) con su procedencia y fecha, y persiste en
  `data/series/<TICKER>.csv`. El precios.csv legado migra a este esquema; el
  fixture del golden no se toca.
- `refrescar_cap(ticker)`: única vía para actualizar una cap congelada; registra
  el cambio como modificación de input (aparece en el diff de corridas). Nunca
  se refresca implícitamente en una corrida.
- `diagnosticar(universo)`: ventana común, activo más corto, qué stress tests
  aplican a quién, y estado del prior del universo (ver §4).
- Regla dura: ningún número sobre un activo no validado — los especialistas
  exigen `Universe` con diagnósticos, no listas de strings.

### 3. Especialistas parametrizados por universo
- Estadístico, Constructor y Escéptico reciben `Universe` + `SessionConstraints`;
  rechazan con error claro inputs cuyo `universe_version` no coincida con el
  vigente (regla de obsolescencia del spec fuente, como invariante mecánico).
- Chequeos de factibilidad en la herramienta (incluye los 4 pendientes de la
  auditoría del constructor): piso×N ≤ 100%, techos alcanzan 100%, overrides
  solo endurecen respecto a SessionConstraints, tickers del override ∈ universo,
  override nunca bajo el piso.
- El Escéptico reporta por activo qué ventana de backtest/stress le aplica y
  degrada con advertencia explícita (no en silencio) cuando la historia es corta.

### 4. Prior de equilibrio BL — política decidida (implementar tal cual + ADR)
Cascada por activo con resolución todo-o-nada sobre el vector:
1. **Fuente** (Tiingo): solo si devuelve capitalización del tipo correcto;
   se congela valor, fuente y fecha as-of.
2. **Usuario**: cap aportada al dar de alta (para ETFs, la metodología
   recomendada es capitalización del subyacente/índice, no AUM; AUM se acepta
   como proxy débil y queda anotado en `prior_fuente_detalle`).
3. **Neutral** (equal-weight sobre el universo completo): requiere confirmación
   del usuario (en S7, un flag explícito `aceptar_neutral=True`; la conversación
   llega en S8).

Reglas que constituyen la decisión:
- Coherencia todo-o-nada: para cualquier universo, o todas las procedencias
  pertenecen a {fuente, usuario}, o todas son neutral — nunca mezcla. Si un
  activo queda sin cap y no se acepta neutral, BL se declara no disponible para
  ese universo (HRP y mínima varianza siguen operativos: el comité no queda cojo).
- Caps congeladas como input reproducible: se obtienen al alta, viven en el
  estado, y solo cambian vía `refrescar_cap`. Mismos datos y semilla → mismas
  cifras se preserva. Las 4 caps del universo de referencia quedan pinneadas en
  el fixture con procedencia `usuario` y nota de metodología (tamaño económico
  del subyacente: large growth ~28.0, BNS 0.116, BTC 1.9, small caps 2.5, en
  US$ billones [trillions]).
- Nunca inventar una cap silenciosamente: cada peso del prior lleva procedencia
  en RunState, y el reporte muestra SIEMPRE la tabla de retornos implícitos π
  con la procedencia de cada peso.
- El ADR documenta explícitamente que equal-weight NO es agnóstico: implica
  retornos implícitos proporcionales al riesgo (ejemplo cuantificado con nuestra
  Σ: IBIT ≈24% en exceso con equal-weight vs ~15% con cap del subyacente), y
  nombra π=0 (prior solo-views) como alternativa evaluada y disponible por
  config para degradación futura si se prefiere.
- Advertencia estándar en reportes con prior neutral: "prior neutral: la
  asignación BL refleja tus views contra un punto de partida equiponderado,
  no contra el consenso de mercado".
- Consecuencia aceptada: dar de alta ETFs y activos sin cap en la fuente
  requiere una interacción. Consecuencia rechazada: priors parcialmente
  inventados o dependientes de datos vivos.

## Fuera de alcance
El Director, los modos de trabajo, cualquier LlmAgent nuevo, sesiones
conversacionales, la elicitación interactiva de caps (S8).

## Definition of Done
- Golden test intacto (fixture congelado, universo original, caps pinneadas).
- Test de propiedad del prior en CI: para universos generados arbitrariamente,
  las procedencias son ⊆ {fuente, usuario} o todas neutral — nunca mezcla.
- Test end-to-end nuevo: universo de 5 activos (los 4 + uno incorporado en
  caliente con mock de Tiingo, cap por argumento) corre el pipeline completo y
  el RunState registra universo, diagnósticos, restricciones, snapshot del prior
  y tabla π con procedencias.
- Tests de: ticker inexistente (error claro); activo de historia corta
  (advertencias propagadas hasta el reporte); resultado con universe_version
  viejo (rechazado); los chequeos de factibilidad; activo sin cap sin
  aceptar_neutral (BL no disponible con mensaje claro, HRP/min-var operativos);
  degradación aceptada (todo el vector neutral + advertencia en reporte);
  refrescar_cap (el cambio queda registrado y altera universe_version).
- make check verde; ADR redactado con la decisión y sus consecuencias; Estado
  actualizado; PR.

## Prompt de arranque (sesión nueva de el asistente de código)

> Lee CLAUDE.md. El sprint activo es S7 (docs/sprints/S7-universo-dinamico.md) —
> léelo COMPLETO incluida la §4, que contiene una decisión de diseño ya tomada
> que debes implementar tal cual, junto con docs/prompts/director.md (el spec
> fuente de a dónde vamos, aunque el Director se implementa en S8) y el Estado
> de S0-S6. Crea la rama sprint/S7-universo-dinamico. Hitos con checkpoint:
> (1) contratos nuevos y modificados + el borrador del ADR del prior redactado
> desde la §4 — muéstramelos y espera mi aprobación antes de implementar;
> (2) Gestor de Datos con tests (mock de Tiingo), cascada del prior con
> procedencia y caps congeladas, y migración del storage a data/series/ sin
> tocar el fixture del golden; (3) especialistas parametrizados por Universe +
> SessionConstraints con los chequeos de factibilidad, el sellado por
> universe_version, y la tabla π con procedencias en el reporte. El golden test
> y el test de propiedad del prior son intocables: si algo los rompe, el error
> es del cambio, no del test. Cierra con el test end-to-end de 5 activos,
> make check verde, Estado y PR.

## Estado
Cerrado el 2026-09-19 (rama `sprint/S7-universo-dinamico`, PR contra `main`).

### Desviaciones del spec (aprobadas en sesión)
- **`neutral` no es procedencia de un activo** (refinamiento de la §1; ADR-013). En
  `AssetDiagnostic` solo caben `fuente | usuario` —de dónde viene la cap—; `neutral` es la
  resolución del vector (`Universe.prior_neutral_aceptado` → `PriorSnapshot`). Así el todo-o-nada
  es imposible de violar por construcción y degradar no borra las caps congeladas. La §1 de este
  spec se corrigió en el mismo PR.
- **`universe_version` es opcional en `QuantEstimates`/`CandidatePortfolios`/`ValidationReport`**
  (`None` = núcleo puro llamado directamente: es lo que permite no tocar el golden) **y
  obligatorio donde importa**: las herramientas sellan siempre y rechazan lo que no esté sellado
  con el universo vigente, y `RunState` rechaza cualquier componente con `None` (test).
- **El universo vive en el estado de sesión**, no como argumento de cada especialista: lo siembra
  `iniciar` desde el Gestor (en S8, el Director) y las herramientas lo leen de ahí.
- **Añadidos que el spec no pedía**: `CandidatePortfolios.no_disponibles`,
  `ValidationReport.advertencias`, `Gestor.sincronizar()` (re-diagnóstico tras
  `make update-prices`), `Gestor.aceptar_prior_neutral()`, `scripts/universo.py` + `make universo`
  (sin un CLI el Gestor no se podía usar hasta S8), `hypothesis` como dependencia de desarrollo.
- **`docs/prompts/director.md` no existe** en el repo, en el historial ni en ninguna sesión
  accesible: no se inventó. No afecta a S7; **bloquea S8** (ver Pendiente).

### Logrado
- **ADR-012** (universo como contrato, sellado, almacenamiento) y **ADR-013** (prior: cascada,
  todo-o-nada, caps congeladas, equal-weight no es agnóstico —IBIT 24,1 % vs. 15,0 % en exceso,
  medido con nuestra Σ—, π = 0 evaluada y disponible por config), ambos aceptados en sesión.
- **Contratos** (`contracts/universe.py`, `session.py`, `prior.py`): `AssetDiagnostic` (bloque de
  prior completo o vacío: "una cap sin procedencia es una cap inventada"), `Universe` (solo aptos;
  `version` = SHA-256 del contenido, incluye caps y el flag de neutral; se revalida al cargar),
  `SessionConstraints` (origen de cada límite; piso×N y techos), `PriorSnapshot` (w_mkt,
  procedencias, tabla π; rechaza mezclas). `RunState` gana `universo`, `restricciones_sesion` y
  `prior`, y exige el prior si hay un candidato BL.
- **Sondeo real de Tiingo** (documentado en ADR-013): la metadata no trae moneda ni cap;
  `fundamentals/meta` solo lista acciones; `marketCap` solo para el DOW 30 en el plan gratuito
  (HTTP 400 para el resto). La procedencia `fuente` es rara y casi toda alta será `usuario`: es la
  cascada operando como se diseñó. Nada de scraping ni fuentes secundarias.
- **Gestor de Datos** (`data_manager/`, determinista): `resolver`, `incorporar` (sanidad de S6,
  cap de la fuente o por argumento con metodología obligatoria, alineación con el almacén),
  `refrescar_cap` (única vía; historial con cap y versión antes/después), `aceptar_prior_neutral`,
  `sincronizar`, `diagnosticar` (ventana común, activo más corto, stress por activo, estado del
  prior). `TiingoFuente` con criterio conservador de "tipo correcto" (acción activa, no ADR, que
  reporta en USD). Probado contra el servicio real: AAPL → cap `fuente` 4,94 bill. (as-of
  2026-09-18); QQQ → prior pendiente; ticker inexistente → error claro.
- **Cascada pura del prior** (`portfolio/prior.py`) y BL aceptando el `PriorSnapshot` resuelto: lo
  que se reporta es exactamente lo que se usó. **Test de propiedad** con hypothesis (200 universos
  arbitrarios + 100 mezclas hechas a mano rechazadas por el contrato). El camino por `Universe`
  da los pesos del golden a 1e-9.
- **Almacén** `data/series/<TICKER>.csv` + `data/universo.json`: migración real con panel
  idéntico al legado (verificado); escritura todo-o-nada entre archivos con restauración;
  `make update-prices` opera sobre el universo vigente y re-diagnostica (real contra Tiingo:
  `SIN_CAMBIOS`). Un almacén a medio actualizar o un universo desincronizado son errores.
- **Especialistas por universo**: herramientas selladas, obsolescencia como invariante
  (`ResultadoObsoletoError`), los cinco chequeos de factibilidad (`portfolio/factibilidad.py`),
  criterios `peso_min/max` contra la SESIÓN, BL no disponible con mensaje claro y HRP/mín-var
  operativos, Escéptico con advertencias explícitas de ventana de backtest y stress por activo.
  Analista y Constructor leen el universo del estado.
- **Informe**: universo y restricciones con origen, tabla π con procedencias SIEMPRE (o por qué no
  hay prior), advertencia estándar de prior neutral, alcance de la validación por historia corta.
  **Comparador**: caps, procedencias y π entre corridas (un `refrescar_cap` sale como cambio de
  INPUT). **Replay**: toma universo y restricciones del `RunState`, no del almacén vivo.
- **DoD**: golden intacto; test de propiedad en CI; end-to-end de 5 activos con alta en caliente
  (APROBADA; acta con universo, diagnósticos, restricciones, prior y tabla π); tests de ticker
  inexistente, historia corta hasta el informe, `universe_version` viejo, factibilidad, prior
  pendiente, degradación aceptada y `refrescar_cap`.
- **Corrida real** tras todos los cambios: `20260919T184929_955370Z`, APROBADA a la primera
  (70/2/4,6/23,4; la de S6 dio 70/2/5,3/22,7) y **replay local: 128 valores, desviación 0.0**.
- `make check` verde: 424 tests (80 nuevos), ruff y mypy strict sin avisos. Verificado con
  `data/series` y `data/universo.json` escondidos: solo falla el test que custodia a propósito
  el universo vivo del repo.

### Pendiente
- **`docs/prompts/director.md` (bloqueante para S8)**: hay que traer el documento original (rol,
  equipo de 6, modos A-D, reglas) al repo; S8 carga la instrucción desde ese archivo.
- `config.portafolio.pesos_actuales` y `regimen.activos_referencia` siguen atados a los 4 activos
  iniciales (si un activo de referencia sale del universo, el régimen queda `INDETERMINADO`).
  No existe `retirar(ticker)`: S7 solo pedía altas.
- `AssetDiagnostic.huecos` siempre va vacío: los proveedores rechazan series con huecos antes de
  diagnosticarlas. El campo queda para una fuente que los tolere.
- `SessionConstraints` ajustadas por el usuario: el contrato y los chequeos existen; la vía para
  fijarlas en sesión es de S8 (hoy siempre son las de `config.yaml`).
- La cap congelada es de su fecha as-of: una estrategia `reestimada` con BL en el backtest la
  usaría en fechas pasadas. Hoy el validador simula pesos fijos, así que no afecta (ADR-013).
- Tras el merge, dev queda con otro `config_hash` y con el almacén nuevo: el replay rechazará las
  corridas anteriores, como está diseñado. Los `RunState` previos a S7 no validan (ADR-012).
- Siguen abiertos de S2-S6: el analista no conoce el prior de equilibrio (ahora π está en el
  estado y en el informe: darle la tabla es barato); `sensibilidad` de los candidatos; intervalos
  de confianza OOS; persistir corridas fallidas; proteger `main`; reportar a Tiingo los
  dividendos duplicados de BNS.

### Aprendizajes
- **Un checkpoint de contratos antes de implementar pagó solo**: la separación "cap del activo /
  resolución del vector" salió de intentar escribir el validador de la lectura literal y ver que
  obligaba a tirar caps congeladas. Escribir el contrato es la forma más barata de encontrar
  una imprecisión del spec.
- **Sondear antes de mockear, otra vez**: tres decisiones salieron del servicio real (la moneda
  se deduce de la bolsa, un 400 de plan es "sin dato" y no un error, los ETFs no existen en
  fundamentals). La expectativa pesimista sobre `marketCap` era correcta y quedó escrita.
- Hacer imposible un estado inválido (no hay campo donde marcar neutral un solo activo) vale más
  que validarlo: el test de propiedad pasa a verificar una consecuencia, no a sostener la regla.
- El sello opcional con cerco (herramientas + `RunState`) dio la garantía sin tocar el golden:
  "opcional en el tipo, obligatorio en la frontera".
- Reutilizar el formato de `CSVPriceProvider` para las series por activo hizo que validaciones,
  escritura atómica y 22 tests de S6 siguieran valiendo sin reescribirlos.
- Si un usuario dice "ese archivo está en nuestra conversación" y no está, se busca (sesiones,
  disco, historial) y se dice; redactarlo "de memoria" habría sido inventar la fuente de verdad
  de S8.
