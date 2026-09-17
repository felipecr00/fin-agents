# ADR 004: Verificación de look-ahead por invariancia al futuro y backtest walk-forward con estrategia como función

- Fecha: 2026-09-16
- Sprint: S2
- Estado: aceptada

## Contexto
S2 debe (a) simular carteras fuera de muestra con rebalanceo y costos, (b) emitir un
veredicto contra umbrales de `config.yaml` y (c) **verificar explícitamente** que ninguna
decisión usó datos posteriores a su fecha. Hasta S1 la única guarda de look-ahead era por
fechas: `QuantEstimates` rechaza una muestra que termine después de `fecha_decision` y
`PriceProvider.precios(hasta=…)` recorta el panel. Esas guardas no detectan la forma más
común de look-ahead: una estrategia que recibe un panel legítimo pero calcula con la muestra
completa (una media o volatilidad de toda la serie, un z-score normalizado con datos
futuros, una señal precomputada). Ese error no viola ninguna fecha declarada y solo se ve
en el resultado: un Sharpe OOS demasiado bueno.

## Decisión
1. **La estrategia es una función `(precios, fecha) -> pesos`** que recibe el panel completo
   y la fecha de decisión, con la obligación de usar solo filas ≤ `fecha`. Es la misma
   convención de `quant.estimar(retornos, fecha_decision, …)`. `risk/estrategias.py` ofrece
   `pesos_fijos` (cartera estratégica) y `reestimada` (re-estima `QuantEstimates` y
   reoptimiza con cualquier optimizador de `portfolio/` en cada decisión).
2. **La obligación no se confía: se comprueba por invariancia al futuro.**
   `verificar_look_ahead` llama a la estrategia en cada fecha de decisión con el panel real
   y con tres paneles cuyo pasado es idéntico y cuyo futuro difiere: truncado
   (`sin_futuro`), con los retornos posteriores invertidos (`futuro_invertido`) y con un
   paseo aleatorio de semilla fija (`futuro_aleatorio`). Si los pesos cambian o la
   estrategia falla, lanza `LookAheadDetectadoError` con la evidencia (fecha, perturbación,
   pesos con el futuro real y pesos alterados). Tres perturbaciones porque cada una caza
   una familia distinta: la truncada, a quien indexa el futuro; la invertida, a quien usa
   su dirección; la aleatoria, a quien usa magnitudes invariantes al signo (varianzas).
3. **`ValidationReport.look_ahead_verificado` es True solo si esa verificación pasó.** Un
   look-ahead detectado no interrumpe `validar`: produce RECHAZADA con la evidencia en
   `sugerencias`, porque el veto es responsabilidad del Validador, no una excepción del
   sistema. Un panel con precios posteriores a `fecha_decision` sí es excepción
   (`LookAheadError`): es un error de quien llama, no una propiedad del candidato.
4. **Backtest walk-forward** (`backtest_walk_forward`): en `d_{k-1}` la estrategia fija los
   pesos; el retorno del período es `d_{k-1} → d_k` con retornos simples (los log-retornos
   no agregan linealmente en cartera). Rebalanceo según
   `validacion.rebalanceo` (hoy `mensual` = cada período); entre rebalanceos los pesos
   derivan. Turnover = Σ|w_objetivo − w_derivado|; costo = turnover × bps/10 000 cobrado en
   **cada** rebalanceo, descontado del capital al inicio del período. La entrada se hace a
   los primeros pesos sin costo salvo que se den `pesos_iniciales`.
5. **Activo sin precio en la fecha de decisión**: su peso objetivo se reparte
   proporcionalmente entre los disponibles. Así el portafolio de referencia se evalúa sobre
   los 60 retornos de la muestra aunque IBIT cotice desde 2024-01, y el stress de 2022 es
   posible para carteras con IBIT. Consecuencia asumida: antes de 2024, VOOG al 70 % pasa a
   71.4 % en los pesos aplicados.
6. **Criterios del veredicto** (todos con umbral en `config.yaml`): `sharpe_oos_minimo`,
   `max_drawdown_tolerado` y `turnover_maximo_anual` sobre el backtest;
   `concentracion_hhi_maxima` (nuevo, 0.55), `peso_max` y `peso_min` sobre los **pesos
   propuestos** (lo que controla el Constructor; el HHI aplicado se informa en `detalle`);
   y un `ResultadoStress` por escenario de `validacion.escenarios_stress` (nuevo:
   `tasas_2022`, `cripto_2025_26`), evaluado con los pesos propuestos fijos y superado si
   su drawdown ≤ `max_drawdown_tolerado`. Cada incumplimiento genera una sugerencia
   concreta (activo con mayor caída ponderada, activo fuera de límite).

## Alternativas descartadas
- **Pasar a la estrategia solo el panel truncado.** Es "seguro por construcción" pero hace
  vacía la verificación: una estrategia que cierra sobre un DataFrame global o una señal
  precomputada sigue mirando el futuro y ninguna perturbación del panel pasado la afecta.
  Con el panel completo, la verificación es una prueba real.
- **Solo la guarda por fechas (contratos).** Ya existe y se mantiene, pero no detecta el
  uso de muestra completa. La invariancia al futuro es la única prueba que observa el
  comportamiento, no las declaraciones.
- **Una sola perturbación.** La inversión de signo no detecta estrategias que usan
  varianzas futuras; la truncada no detecta a quien tolera la ausencia de futuro con un
  valor por defecto. Tres perturbaciones cuestan tres llamadas por fecha: despreciable.
- **Lanzar excepción ante look-ahead en `validar`.** Rompe el bucle Constructor ↔ Validador
  de S3 y deja al LLM sin reporte que redactar. El contrato ya admite RECHAZADA con
  `look_ahead_verificado=False` y lo lista en `razones_rechazo`.
- **Empezar el backtest en la ventana común (2024-01).** Deja 32 observaciones y sin
  escenario 2022 para cualquier cartera con IBIT. Se prefiere repartir el peso del activo
  ausente y documentarlo.
- **HHI sobre los pesos aplicados.** Penaliza el artefacto del punto 5 (0.561 > 0.55 para
  la referencia por la redistribución de IBIT antes de 2024) en lugar de la decisión del
  Constructor.
- **Log-retornos ponderados como retorno de cartera.** Sesga el resultado (Jensen); se usan
  retornos simples y el valor acumulado se compone geométricamente.

## Consecuencias
- Cero dependencias nuevas; `risk/` es código puro, tipado en `mypy --strict`, sin ADK.
- `config.yaml` gana `validacion.concentracion_hhi_maxima` y
  `validacion.escenarios_stress`; `config.py` gana `EscenarioStressConfig`. Ningún contrato
  de `contracts/` cambia.
- S3 debe construir sus estrategias con la convención `(precios, fecha)`; `reestimada` ya
  cubre el caso de reoptimizar cualquier técnica de `portfolio/`.
- La verificación multiplica por cuatro las llamadas a la estrategia (real + 3
  perturbaciones) en cada fecha: irrelevante para pesos fijos; para `reestimada` con SLSQP
  son ~4 × 60 optimizaciones, del orden de un segundo.
- Con ~60 observaciones mensuales el Sharpe OOS y el drawdown son indicativos (ver
  limitaciones en el spec de S2); el veredicto es estricto contra los umbrales aunque la
  incertidumbre estadística sea alta. S5 debería reportar intervalos.
