# Sprint 10 — Nivelación del Equipo: Sub-Agentes Thin (Doc: Sprint 2)

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

## Nota formal de costo aceptado
El desdoblamiento temprano del Estadístico y el Escéptico requiere evaluar y
calibrar dos contextos de LLM adicionales antes de que la capa operativa esté
completamente madura. Justificación aprobada: resolver la opacidad del comité
monolítico desde el inicio mejora dramáticamente la adopción y auditabilidad
del sistema por parte del CIO.

## Alcance
1. `agents/estadistico/` y `agents/esceptico/`: LlmAgents thin (single_turn,
   Nivel 1 o el nivel que config asigne, temperatura baja), una tool cada uno
   (`estimar_mercado`, `diagnosticar_cartera`), prompt de rol según las
   justificaciones del diagrama aprobado (el Estadístico reporta siempre la
   confianza de su estimación; el Escéptico busca grietas y nunca emite
   veredicto fuera del comité). Los números salen solo de su herramienta.
2. Desmontar el ruteo plano del Director: de ~12 tools a ruteo jerárquico —
   personas (Analista, Estadístico, Escéptico), Gestor (transaccional, sin
   persona), comité. `test_director.py` verifica la delegación de roles.
3. `fintual/no_trade_zones.py` (Nivel 3, puro): bandas de inercia configurables
   (default ±5%); dentro de banda la orden es HOLD obligatorio.
4. `agents/fintual_data/`: evolución del Gestor con la tool
   `gestionar_datos_y_fricciones` — fechas ex-dividendo, cierres ajustados,
   traducción de pesos a montos fraccionados en USD (2 decimales).
5. Evalset extendido: los casos del Director re-corridos sobre el ruteo
   jerárquico + casos nuevos de delegación (pregunta de correlación → habla el
   Estadístico con atribución; «¿qué le preocupa de esta cartera?» → habla el
   Escéptico sobre el diagnóstico de su tool).

## Definition of Done
make check y make eval verdes; demo conversando con las tres personas; el
Director no ofrece capacidades sin herramienta (eval existente sigue verde);
nota de costo aceptado copiada en el Estado; PR.

## Estado
(pendiente — actualizar al cerrar el sprint)
