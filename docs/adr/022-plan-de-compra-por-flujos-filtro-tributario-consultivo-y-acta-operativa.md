# ADR 022: Plan de compra por flujos, filtro tributario consultivo y acta operativa

- Fecha: 2026-09-20
- Sprint: S11
- Estado: aceptada (2026-09-20, checkpoint 2 de S11: reparto proporcional y cota por defecto confirmados)

## Contexto
S10 dejó las No-Trade Zones (`PlanInercia`) SEÑALANDO desviaciones sin decir qué hacer con
ellas. S11 pide: (a) rebalanceo por flujos —aportes y dividendos 100 % a lo que está bajo
objetivo, cero ventas, montos fraccionados en US$—; (b) un filtro tributario CONSULTIVO (enmienda
v2 §2: la heurística "evitar ventas con ganancia" pasa de ley a advertencia calificada, reconoce
el tax-loss harvesting, etiqueta «Costo fiscal estimado: $X CLP», inyecta el disclaimer); y (c)
un Override del usuario que quede REGISTRADO en el acta con la advertencia que cruzó. El sistema
nunca ejecuta. Las fronteras siguen: Nivel 3 puro, cifras jamás por argumentos de LLM, custodias
en código.

## Decisión
1. **Reparto proporcional al déficit** (`fintual/cash_flow_alloc.py`, puro). Sobre la cartera ya
   con el flujo, déficit = max(objetivo·(V+F) − tenencia, 0); el flujo se reparte en proporción
   a los déficits, al centavo por mayor residuo. Como Σ(objetivo − actual) = F, Σ déficits ≥ F:
   el flujo se agota siempre sin pasar a nadie de su objetivo (test de propiedad con hypothesis).
   `PlanCompraNeta` no tiene dónde escribir una venta (`ventas_usd` solo admite 0).
2. **Las bandas no frenan la compra con dinero nuevo; frenan la ROTACIÓN.** Un activo en banda y
   bajo objetivo recibe su parte del flujo (matriz de verificación v2 §12.5: "HOLD con indicación
   de compra solo en caso de inyección de aportes"). El plan reporta las bandas ANTES y DESPUÉS
   del flujo: lo que sigue fuera de banda por arriba no se vende; se dice.
3. **Filtro consultivo** (`fintual/tax_filter.py`, puro): por cada activo que sigue
   sobreponderado fuera de banda, dos escenarios de venta (hasta el borde de la banda, hasta el
   objetivo) con su etiqueta en CLP; el escenario por defecto es SIEMPRE "sin ventas" (lo exige
   el contrato). Una venta con pérdida se marca `cosecha_de_perdidas` con costo 0 y su pérdida
   realizable; los activos con pérdida latente se listan aunque nadie proponga venderlos.
4. **Los supuestos son del usuario y viajan en la salida** (`config.yaml: fintual.tributario`:
   tramo marginal, USD/CLP, costo de adquisición por activo). Sin costo declarado el sistema NO
   inventa una base: reporta una COTA (toda la venta es ganancia) y lo dice. Los valores que
   trae `config.yaml` son marcadores editables, no hechos.
5. **Override con la custodia del gate (ADR-014)**: `forzar_orden(escenario, token)` solo vale
   en un turno POSTERIOR al que presentó la advertencia, con el token de ese plan, una vez, y si
   la cartera objetivo y el universo no cambiaron. El LLM pasa el ID del escenario, nunca un
   monto. El producto de la venta se reasigna con la misma regla de flujos.
6. **Acta operativa aparte del `RunState`** (`ActaOperativa`,
   `runs/<run_id>/acta_operativa_<id>.json` junto al acta del comité que aprobó la cartera; en
   `runs/operaciones/` si la cartera es exploratoria). Guarda plan, asesoría y cada
   `OverrideFiscal` con la advertencia cruzada LITERAL (el contrato rechaza otra cosa), los dos
   turnos y sus horas. `ejecutado_por_el_sistema` solo admite `False`.
7. **El monto del flujo es la única cifra que llega por un argumento de LLM**, y solo vale si el
   usuario la ESCRIBIÓ (`tools/procedencia.py`, la custodia de S10 generalizada). La cartera
   objetivo sale de la mesa; la actual, de `config.yaml`.
8. **Bloque y disclaimer por código** (ADR-017): tabla, escenarios, supuestos, "el sistema no
   ejecuta" y `DISCLAIMER_OPERATIVO` se anexan a la respuesta; los contratos rechazan cualquier
   otro texto en el campo `disclaimer`.

## Alternativas descartadas
- **Registrar el override dentro de `RunState`**: el acta del comité es inmutable, sellada y
  reproducible por replay; un override ocurre DESPUÉS de cerrada, lleva la hora del reloj y puede
  haber varios. Cambiar ese contrato obligaba a tocar replay, comparador e informe para algo que
  no es una decisión del comité. El acta operativa referencia el `run_id` y vive a su lado.
- **Llenar primero el activo más desviado (waterfall)**: concentra todo el flujo en un activo
  hasta igualar desviaciones; más agresivo y menos legible. El proporcional da el mismo resultado
  cuando hay un solo activo bajo objetivo y reparte sin sorpresas cuando hay varios.
- **No comprar lo que está dentro de banda**: dejaría flujo sin asignar o lo concentraría solo en
  lo que está fuera de banda; contradice "100 % a los activos bajo su objetivo".
- **Estimar el costo de adquisición** (p. ej. desde precios históricos): sería inventar un dato
  tributario del usuario. Cota explícita o dato declarado.
- **Filtro como veto** (la versión previa a la enmienda): descartada por la enmienda §2.
- **`confirmar_override: bool`** como argumento: el LLM lo rellena solo (ADR-014).

## Consecuencias
- El usuario recibe un plan ejecutable en la app, sin ventas, y la información para decidir si
  su estrategia justifica una; si fuerza una, queda el rastro completo de qué sabía al hacerlo.
- `portafolio.valor_usd`/`pesos_actuales` y los supuestos tributarios son manuales: el plan es
  tan actual como ellos (pendiente heredado de S10: leer la cartera real de otra fuente).
- Las cifras fiscales son estimaciones gruesas por diseño (un tramo marginal, un tipo de cambio,
  sin créditos por impuestos pagados en el extranjero ni reglas de compensación): por eso son
  etiquetas con disclaimer y no una recomendación.
- `config_hash` cambia (sección `fintual.tributario`): el replay rechazará corridas anteriores,
  como está diseñado.
