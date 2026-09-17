# ADR 001: Contratos inmutables con validación de coherencia semántica

- Fecha: 2026-09-16
- Sprint: S0
- Estado: aceptada

## Contexto
Los agentes solo se comunican mediante los esquemas de `contracts/`. Un contrato que
únicamente tipa campos deja pasar estados absurdos (pesos que no suman 1, un veredicto
APROBADA con un criterio incumplido, una muestra que termina después de la fecha de
decisión). Detectar eso aguas abajo, dentro de un LLM o al final de una corrida, es caro
y difícil de auditar.

## Decisión
Todos los contratos heredan de `ContractBase` con `frozen=True`, `extra="forbid"` y
`allow_inf_nan=False`, y llevan validadores de modelo que hacen cumplir invariantes del
dominio:
- pesos y filas de P coherentes con su tipo (absoluta/relativa) y que suman lo esperado;
- `ValidationReport.veredicto` es consistente con `criterios`, `stress` y
  `look_ahead_verificado` (el contrato impide aprobar con un criterio incumplido);
- guardas de look-ahead por fecha en `MarketViews` (fuentes), `QuantEstimates` (muestra)
  y `ValidationReport` (backtest);
- `RunState` exige un solo universo y una sola fecha de decisión en todos los
  subcontratos y avanza solo por `avanzar(...)`, que revalida el estado completo.
Las unidades son siempre fracciones (0.03 = 3 %), nunca porcentajes.

`View.confianza` es obligatoria, pero su traducción a Ω la decide
`config.yaml: optimizacion.metodo_omega` (`he_litterman` ignora la confianza y reproduce
el ejercicio de referencia; `idzorek` la usa). Así el analista siempre declara confianza
sin que el golden test dependa de ella.

## Alternativas descartadas
- **Dataclasses o TypedDict sin validación.** Más livianos, pero trasladan las
  comprobaciones a cada consumidor y no sirven como `output_schema` de ADK.
- **Modelos mutables (`frozen=False`).** Facilitan el uso incremental, pero permiten que
  un agente altere un estado ya validado sin volver a validarlo; rompe reproducibilidad.
- **Validar el veredicto solo en `risk/`.** Deja al contrato admitir un APROBADA
  inconsistente si el LLM redactor lo emite; el contrato es la última barrera.
- **Confianza opcional (`None` = He-Litterman).** Acopla el contrato a un método
  concreto de Ω y permite que el analista omita información.

## Consecuencias
- Cambiar un invariante exige ADR + actualizar consumidores + tests (regla de CLAUDE.md).
- Los estados intermedios de `RunState` se construyen con `avanzar(...)`; algo más de
  copia de datos, irrelevante a esta escala.
- Los tests unitarios de contratos (60) documentan qué se admite y qué no.
