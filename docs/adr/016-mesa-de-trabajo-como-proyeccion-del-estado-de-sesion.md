# ADR 016: La mesa de trabajo es una proyección del estado de sesión, no un registro aparte

- Fecha: 2026-09-20
- Sprint: S9
- Estado: propuesta (pendiente de aprobación en el checkpoint 1 de S9)

## Contexto
S9 pide `contracts/mesa_trabajo.py` (`MesaDeTrabajoState`, `ItemPizarra` con categoria,
contenido, origen y `obsoleto` por ítem, sellados con `universe_version`) y la tool
`consultar_mesa_trabajo`. La propuesta (arquitectura v2 §5) dibuja la pizarra como un artefacto
en el `SessionState` que se lee y se ESCRIBE: cada especialista anotaría su elemento y un cambio
de universo recorrería la lista marcando `obsoleto: true`.

Pero el estado de sesión ya guarda, desde S7-S8, todo lo que la pizarra quiere mostrar, como
contratos sellados: el `Universe`, las `MarketViews`, las `QuantEstimates`, las rondas de
`CandidatePortfolios`, los `DiagnosticoCartera` y las `SessionConstraints`. Y la obsolescencia ya
es un invariante mecánico (`exigir_sello`, ADR-012): las herramientas rechazan lo sellado con
otro universo. Una pizarra escrita aparte sería una SEGUNDA fuente de verdad sobre lo mismo.

## Decisión
`MesaDeTrabajoState` se ARMA cada vez que se consulta, como proyección de esos contratos
(`tools/mesa.py: construir_mesa`); no se persiste en el estado ni la escribe ninguna otra
herramienta. Cada `ItemPizarra` lleva el sello de SU contrato y `obsoleto` se deriva de él con
la misma regla que usan las herramientas; el contrato de la mesa rechaza cualquier ítem cuyo
`obsoleto` contradiga a su sello. Las vistas, que no se sellan por versión, siguen la regla de
`construir_candidatos` (misma lista de activos).

- "Marcar ítem por ítem" queda garantizado por construcción: tras un cambio de universo, la
  siguiente lectura muestra obsoleto exactamente lo que una herramienta rechazaría, y vigente lo
  que ya se rehízo. Test: `test_la_mesa_dice_obsoleto_exactamente_donde_la_herramienta_rechaza`.
- `origen` es un enum cerrado (`Especialista`): la misma fuente de nombres servirá a la ficha de
  origen y al evaluador de atribución de este sprint.
- El roster (`Silla`) sale de los nombres reales de tools y sub-agentes con que se construye el
  Director (`componer_sala`); una herramienta sin silla asignada impide construir el equipo.
- Todo el texto de la tabla lo redacta el código desde los contratos: ningún párrafo de un LLM
  (resumen o justificación de una view) entra en la mesa.
- `consultar_mesa_trabajo` re-adopta el universo del disco y declara `resultados_obsoletos`,
  igual que `diagnosticar`, porque lo reemplaza en la apertura de sesión.

Desviaciones frente al contrato dibujado en la propuesta: `categoria` y `origen` son enums (no
`str`); cada ítem gana `universe_version` (lo exige el spec) y `que_hacer`; se omiten
`ultimo_diagnostico_id` y `vistas_activas_hash`: nada los consume, los diagnósticos no tienen id
(dárselo es cambiar otro contrato) y con la proyección no hacen falta para detectar cambios.

## Alternativas descartadas
- **Pizarra escrita por cada herramienta (lectura literal de la propuesta).** Exige tocar
  `NucleoTools` y `GestorTools` (S8 los dejó "sin modificar") y que toda herramienta futura se
  acuerde de anotar. El fallo es silencioso en los dos sentidos: una mesa que dice "vigente" de
  algo que la herramienta rechaza, o un resultado que existe y no aparece. Es el aprendizaje de
  S7 ("hacer imposible un estado inválido vale más que validarlo") aplicado a la pizarra.
- **Proyección + copia persistida en el estado** (para verla en la pestaña State de `adk web`).
  La copia envejece en cuanto otra herramienta escribe; habría que refrescarla desde todas, que
  es la alternativa anterior con otro nombre.
- **`origen: str` libre.** El evaluador de atribución y la ficha necesitan un vocabulario
  cerrado; un string lo dejaría a merced de la redacción.

## Consecuencias
- Cero deriva entre la mesa y las custodias; ninguna herramienta existente cambia.
- La mesa solo muestra lo que el estado conserva: las restricciones ajustadas por el usuario que
  un cambio de universo retira no aparecen como "obsoletas" (desaparecen y rigen las de
  config.yaml); eso lo declara `resultados_obsoletos` en el momento del cambio. Tampoco hay
  historial de estimaciones reemplazadas.
- Un resultado nuevo en el estado (S10-S11: fricciones Fintual, hitos del comité) necesita su
  rama en `construir_mesa` y su silla en `ATIENDE`; olvidar la silla rompe al construir el
  equipo, olvidar la rama solo lo omite de la tabla (cubrirlo con test al añadirlo).
- El acta del comité (`RunState` en el estado tras `ejecutar`) NO está en la mesa: la mesa es el
  espacio exploratorio. Si se quiere una fila "Acta", es una categoría nueva (decisión abierta).
