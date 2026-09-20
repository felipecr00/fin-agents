# Sprint 11 — Comité Audible y Experiencia Fintual (Doc: Sprint 3)

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

## Alcance
1. `contracts/hitos_comite.py` (`HitoComite`: timestamp, fase, iteracion,
   evento, detalle). `pipeline.py` emite hitos a `pipeline_milestones` en el
   estado compartido Y a `runs/<id>/bitacora.jsonl` mientras corre.
2. Transmisión en vivo: verificar las capacidades de streaming vigentes de ADK;
   si el chat puede mostrar hitos durante la llamada, se implementa; si no, la
   garantía mínima es doble — bitácora legible en tiempo real desde otra
   terminal, y la respuesta del Director al cerrar abre con la cronología
   completa narrada (fases, iteraciones, vetos con motivo, tiempos).
3. `fintual/cash_flow_alloc.py` (Nivel 3): rebalanceo por flujos — aportes y
   dividendos se asignan 100% a los activos bajo su objetivo; cero ventas por
   defecto; salida como Plan de Compra Neta en USD fraccionados.
4. `fintual/tax_filter.py` CONSULTIVO (enmienda §2): emite escenarios
   etiquetados («Costo fiscal estimado: $X CLP»), reconoce tax-loss harvesting
   como estrategia legítima, disclaimer inyectado en la salida («estimación
   algorítmica, no asesoría tributaria o financiera; valida el tratamiento de
   dividendos extranjeros con tu contador»), y mecanismo de Override del
   usuario (forzar la orden pese a la advertencia) que queda REGISTRADO en el
   acta con la advertencia que cruzó. El sistema nunca ejecuta: produce el plan
   que el usuario ejecuta en la app.
5. Unificación de experiencia: apps/equipo es la única interfaz; el modo
   comando sobrevive como target de despliegue y make (ritual mensual sin
   conversación), no como visor — la bitácora eliminó su razón de existir.

## Definition of Done
Una corrida de comité muestra la cronología (en vivo o al cierre según lo que
ADK permita, documentado cuál); bitacora.jsonl legible en paralelo; un plan de
compra generado desde un aporte simulado con no-trade zones y tax guard
consultivo, con su disclaimer y un caso de Override registrado en acta;
make check verde; Estado; PR.

## Estado
(pendiente — actualizar al cerrar el sprint)
