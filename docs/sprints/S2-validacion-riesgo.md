# Sprint 2 — Validación y riesgo (adversarial)

## Objetivo
Construir el agente que intenta romper las carteras y tiene poder de veto.

## Alcance
- `risk/`: backtest walk-forward con rebalanceo y costos de config.yaml (los costos se
  aplican en CADA rebalanceo); métricas Sharpe OOS, max drawdown, turnover, concentración.
- Stress tests históricos: 2022 (tasas) y 2025-26 (corrección cripto). El escenario
  2020 (covid) queda fuera: `data/precios.csv` comienza en septiembre de 2021.
- Veredicto APROBADA/RECHAZADA contra umbrales de config.yaml, con razones.
- Verificación explícita de look-ahead bias.

## Definition of Done
- Test que inyecta look-ahead bias a propósito y demuestra que se detecta.
- Test donde una cartera diseñada para violar umbrales es rechazada con razones correctas.
- `make check` verde; PR mergeado.

## Estado
Cerrado el 2026-09-16 (rama `sprint/S2-validacion-riesgo`, PR contra `main`).

### Decisiones de alcance
- Los stress tests cubren 2022 (ciclo de tasas: `tasas_2022`, retornos 2022-01 a 2022-12) y
  la corrección cripto 2025-26 (`cripto_2025_26`, retornos 2025-08 a 2026-06, IBIT −50 %
  desde su máximo). No hay escenario 2020: los datos empiezan en 2021-09.

### Logrado
- ADR-004: estrategia como función `(precios, fecha) -> pesos`, verificación de look-ahead
  por invariancia al futuro (tres perturbaciones con semilla de `config.yaml`) y semántica
  del backtest walk-forward.
- `risk/backtest.py`: walk-forward con rebalanceo (`validacion.rebalanceo`) y costos
  (`costo_transaccion_bps`) cobrados en CADA rebalanceo sobre Σ|Δw|; retornos simples,
  deriva entre rebalanceos, reparto proporcional del peso de un activo que aún no cotiza.
- `risk/metricas.py`: retorno anualizado geométrico, volatilidad, Sharpe OOS, max drawdown,
  turnover anual, costo total, HHI y drawdown por activo.
- `risk/estrategias.py`: `pesos_fijos` y `reestimada` (re-estima `QuantEstimates` y
  reoptimiza con cualquier optimizador de `portfolio/` en cada fecha: walk-forward genuino).
- `risk/look_ahead.py`: `verificar_look_ahead` y `LookAheadDetectadoError` con evidencia
  (fecha, perturbación, pesos reales vs. alterados). Subclase de `quant.LookAheadError`.
- `risk/stress.py`: escenarios de `validacion.escenarios_stress` con los pesos propuestos,
  recortados en la fecha de decisión y omitidos si quedan en el futuro.
- `risk/validacion.py`: `validar` → `ValidationReport` con seis criterios
  (`sharpe_oos_minimo`, `max_drawdown_tolerado`, `turnover_maximo_anual`,
  `concentracion_hhi_maxima`, `peso_max`, `peso_min`), stress, `look_ahead_verificado`
  honesto y una sugerencia concreta por incumplimiento.
- `config.yaml`: `validacion.concentracion_hhi_maxima: 0.55` (la referencia 70/7/2/21 da
  0.539) y `validacion.escenarios_stress`.
- DoD: `test_look_ahead.py` inyecta una estrategia con visión perfecta (100 % en el mejor
  activo del mes siguiente) y una sutil (1/σ con la muestra completa, invariante al signo);
  ambas se detectan con evidencia y `validar` las rechaza. `test_validacion.py` presenta
  una cartera 94 % IBIT y verifica el rechazo por exactamente `max_drawdown_tolerado`,
  `concentracion_hhi_maxima`, `peso_max` y el stress `cripto_2025_26`; además turnover
  excesivo, Sharpe insuficiente (decidiendo en 2022-12) y peso bajo el mínimo.
- Con los datos reales el portafolio de referencia queda APROBADO: Sharpe OOS 0.54, max
  drawdown 29.0 %, turnover 0.18/año, costos totales 9 p.b. en cinco años; supera los dos
  stress (2022: −26.8 %, drawdown 29.0 %; cripto: drawdown 7.4 %).
- `make check` verde: 176 tests (39 nuevos), ruff y mypy strict sin avisos.

### Pendiente
- Detección de régimen de mercado (`RegimenMercado`): no entró en S2; va a S5.
- `validacion.concentracion_hhi_maxima = 0.55` es un valor propuesto en este sprint; el
  usuario decide si lo mantiene.
- S3: el agente de Riesgo expone `validar` como FunctionTool y construye la estrategia del
  candidato con `reestimada` cuando quiera validar la técnica y no solo los pesos.
- S5: intervalos de confianza de las métricas OOS (con 60 observaciones el Sharpe tiene
  un error estándar del orden de 0.45).

### Limitaciones conocidas
- El backtest walk-forward opera sobre ~60 observaciones mensuales (2021-10 a 2026-09).
  Con esa muestra las métricas OOS tienen alta varianza: el Sharpe OOS y el max drawdown
  son indicativos, no estadísticamente concluyentes. IBIT solo aporta 32 observaciones;
  antes de 2024-01 su peso se reparte entre los demás activos (ADR-004), así que el
  escenario 2022 no mide exposición cripto.
- Con pesos fijos el "walk-forward" es un rebalanceo mensual a la cartera propuesta; la
  validación de la técnica (reoptimizar cada mes) existe (`reestimada`) pero el Validador
  la usará cuando S3 decida qué estrategia asociar a cada candidato.

### Aprendizajes
- La guarda por fechas de los contratos no detecta el look-ahead más común (usar la muestra
  completa). La invariancia al futuro sí, y explica el fallo con un ejemplo concreto.
- Medir la concentración sobre los pesos aplicados en lugar de los propuestos hizo que la
  referencia fallara por un artefacto de la redistribución de IBIT; los criterios deben
  evaluar lo que el Constructor controla.
- pandas 3.0: un `DataFrame.loc` con máscara booleana de otro índice lanza `IndexError`;
  las máscaras se construyen siempre sobre el índice del panel que se indexa.
