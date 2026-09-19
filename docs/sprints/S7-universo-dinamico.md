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
  stress 2022 no aplica"), apto/no apto, y el bloque de prior:
  `prior_cap` (valor congelado, opcional), `prior_provenance: fuente | usuario |
  neutral`, `prior_fuente_detalle` (qué endpoint o qué metodología del usuario),
  `prior_as_of` (fecha del valor).
- `Universe`: activos con diagnósticos, versión (hash del contenido, incluye las
  caps congeladas), origen de cada activo (config inicial / agregado en sesión).
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

## Prompt de arranque (sesión nueva de Claude Code)

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
(pendiente — actualizar al cerrar el sprint)
