# ADR 013: Prior de equilibrio BL — cascada con procedencia, todo-o-nada y caps congeladas

- Fecha: 2026-09-19
- Sprint: S7
- Estado: propuesta (la política la decidió el usuario en el spec de S7 §4; este ADR la
  documenta y fija cómo se representa; pendiente de aprobación en sesión)

## Contexto
Black-Litterman parte de un prior de equilibrio π = δ·Σ·w_mkt. Hasta S6, w_mkt salía de cuatro
capitalizaciones escritas en `config.yaml` para un universo fijo. Con el universo dinámico de
S7 cualquier activo puede entrar en sesión, y para la mayoría no hay una "capitalización"
obvia: Tiingo la expone para acciones; para un ETF lo que existe es AUM, que mide el tamaño
del vehículo y no el del mercado que representa (VOOG gestiona decenas de miles de millones
de un segmento de ~US$28 billones).

Dos tentaciones que esta decisión cierra:
1. **Rellenar en silencio** la cap que falta (AUM, la media de las demás, un valor "razonable").
   El prior domina la cartera cuando las views son pocas o débiles (S5: la cartera es más
   frágil a los retornos esperados que a cualquier otro supuesto); un peso inventado es una
   opinión de mercado que nadie dio.
2. **Leer caps vivas en cada corrida.** Rompe "misma entrada = misma salida" (CLAUDE.md) y el
   replay de ADR-009: dos corridas con los mismos precios darían carteras distintas.

## Decisión
**Cascada por activo, resolución todo-o-nada sobre el vector, caps congeladas como input.**

1. **Cascada por activo**, en este orden:
   1. `fuente` — Tiingo, solo si devuelve capitalización del tipo correcto (acciones). Se
      congelan valor, endpoint (`prior_fuente_detalle`) y fecha as-of.
   2. `usuario` — cap aportada al dar de alta (`incorporar(ticker, prior_cap, prior_metodologia)`).
      Para ETFs la metodología recomendada es la capitalización del subyacente/índice, no AUM;
      AUM se acepta como proxy débil y queda anotado en `prior_fuente_detalle`.
   3. `neutral` — equal-weight sobre el universo COMPLETO. Requiere confirmación explícita
      (`aceptar_neutral=True` en S7; conversacional en S8).
2. **Coherencia todo-o-nada.** Para cualquier universo, o todas las procedencias del prior
   pertenecen a {fuente, usuario}, o todas son neutral — nunca mezcla. Si un activo queda sin
   cap y no se acepta neutral, **BL se declara no disponible** para ese universo con un mensaje
   que dice qué activo falta; HRP y mínima varianza siguen operativos (no dependen del prior).
3. **Caps congeladas.** Se obtienen al alta, viven en el `Universe` (y por tanto en su
   `version`) y solo cambian con `refrescar_cap(ticker)`, que registra el cambio como
   modificación de input. Nunca se refrescan implícitamente en una corrida. Las cuatro caps
   del universo de referencia quedan pinneadas con procedencia `usuario` y nota de metodología
   (tamaño económico del subyacente, US$ billones [10^12]: large growth 28.0, BNS 0.116,
   BTC 1.9, small caps 2.5).
4. **Nunca una cap silenciosa.** Cada peso del prior lleva su procedencia en `RunState`
   (`PriorSnapshot`), y el reporte muestra SIEMPRE la tabla de retornos implícitos π con la
   procedencia de cada peso, haya o no degradación.
5. **Advertencia estándar** en todo reporte con prior neutral: "prior neutral: la asignación BL
   refleja tus views contra un punto de partida equiponderado, no contra el consenso de
   mercado".

### Representación (ver ADR-012 para los contratos)
- La cap congelada es un dato **del activo**: `AssetDiagnostic.prior_cap / prior_provenance
  (fuente | usuario) / prior_fuente_detalle / prior_as_of`, los cuatro juntos o ninguno ("una
  cap sin procedencia es una cap inventada" es un error de validación).
- `neutral` es una resolución **del universo**: `Universe.prior_neutral_aceptado`. De ahí sale
  `Universe.estado_prior ∈ {capitalizacion, neutral, pendiente}`. El todo-o-nada se cumple por
  construcción (no hay forma de marcar neutral un solo activo) y, además, `PriorSnapshot` lo
  valida sobre las procedencias efectivas. Degradar a neutral **no borra** las caps ya
  congeladas: cuando llegue la cap que faltaba, el universo vuelve al prior de mercado sin
  volver a consultar ninguna fuente.
- `prior_neutral_aceptado=True` con todas las caps presentes es un error: neutral es el último
  escalón de la cascada, no una alternativa a caps disponibles.

### Equal-weight NO es agnóstico
Un prior equiponderado afirma que el mercado tiene la misma cantidad de cada activo, y por
ingeniería inversa le asigna a cada uno un retorno implícito proporcional a su contribución al
riesgo. Con nuestra Σ (fixture de referencia, decisión 2026-09-30, δ = 2.5), π en exceso de rf:

| Activo | w_mkt (caps) | π caps | w_mkt (1/N) | π equal-weight |
|---|---:|---:|---:|---:|
| VOOG | 86,1 % | 9,2 % | 25 % | 8,9 % |
| BNS | 0,4 % | 7,6 % | 25 % | 9,7 % |
| IBIT | 5,8 % | **15,0 %** | 25 % | **24,1 %** |
| VB | 7,7 % | 7,2 % | 25 % | 8,8 % |

Equal-weight "cree" que IBIT rendirá 24 % sobre la tasa libre de riesgo —nueve puntos más que
el prior de mercado— solo porque es el activo más volátil. Por eso la degradación exige
confirmación y lleva advertencia: no es la opción prudente por defecto, es otra opinión.

## Alternativas descartadas
- **Mezcla por activo** (caps donde las hay, 1/N donde no): el vector resultante no representa
  ninguna cartera de mercado ni ningún punto de partida defendible; el peso relativo entre un
  activo "con cap" y uno "neutral" es un artefacto de unidades. Es la opción que el todo-o-nada
  prohíbe.
- **AUM como cap por defecto para ETFs**: automatiza el alta, pero subestima el segmento en
  órdenes de magnitud y de forma desigual entre ETFs. Se admite solo como elección explícita
  del usuario y anotada.
- **Caps vivas por corrida**: descartada por reproducibilidad (ver Contexto).
- **π = 0 (prior solo-views)**: evaluada. Es la única degradación genuinamente "sin opinión"
  sobre el mercado, pero con pocas views deja la cartera determinada casi solo por los límites
  y por Σ, y rompe la continuidad con el ejercicio de referencia. Queda **disponible por
  config** (`prior_equilibrio.degradacion: neutral | solo_views`, por defecto `neutral`) y en
  el contrato (`MetodoPrior.SOLO_VIEWS`, con su propia advertencia estándar) para una
  degradación futura si se prefiere; no es la política activa (S8 la deja fuera de alcance).
- **Bloquear todo el comité si falta una cap**: HRP y mínima varianza no usan el prior; dejarlos
  operativos mantiene útil la sesión mientras se resuelve el alta.

## Consecuencias
- **Aceptada**: dar de alta ETFs y activos sin cap en la fuente requiere una interacción.
- **Rechazada**: priors parcialmente inventados o dependientes de datos vivos.
- Mismos datos, mismas caps y misma semilla → mismas cifras. `refrescar_cap` o aceptar neutral
  cambian `Universe.version`: los resultados anteriores quedan obsoletos de forma mecánica
  (ADR-012) y el cambio aparece en el diff de corridas.
- El golden test no cambia: sigue llamando al núcleo puro con las caps de
  `config.yaml: prior_equilibrio`, que pasan a ser la semilla pinneada del universo de
  referencia. Un test nuevo verifica que el universo de referencia del fixture lleva
  exactamente esas caps, de modo que el camino por `Universe` reproduce los pesos del golden.
- Test de propiedad en CI: para universos arbitrarios, las procedencias del prior resuelto son
  ⊆ {fuente, usuario} o todas neutral.
- Limitación heredada, ahora visible: la cap congelada es de su fecha as-of. Una estrategia
  `reestimada` con BL en el backtest usa esa misma cap en fechas pasadas; hoy el validador
  simula pesos fijos (S2), así que no afecta al veredicto. Si S5-pendiente "validar la técnica"
  se activa, habrá que decidir un prior histórico.
- S8 hereda la mecánica completa y solo añade la conversación (una pregunta con tres opciones
  y la confirmación del todo-o-nada).
