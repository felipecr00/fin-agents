# Sprint 9 — Visibilidad, Pizarra y Atribución (Doc: Sprint 1)

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

## Objetivo
La sala se ve: cada respuesta con silla y ficha, la mesa de trabajo inspeccionable,
el gate blindado por test, y la limpieza de nombres de modelos.

## Alcance
1. `contracts/mesa_trabajo.py`: `MesaDeTrabajoState` e `ItemPizarra` según la
   propuesta (categoria, contenido, origen, obsoleto por ítem), sellados con
   universe_version. Un cambio de universo marca `obsoleto: true` ítem por ítem —
   granularidad por elemento, no solo por sesión.
2. Tool `consultar_mesa_trabajo` (determinista): renderiza la tabla de la mesa
   (universo, vistas, estimaciones, diagnósticos, restricciones, con especialista
   de origen y estado). Reemplaza la llamada suelta a `diagnosticar` en la
   apertura de sesión. Responde también el roster («¿quién está en la sala?»)
   desde la composición real del equipo.
3. Ficha de origen generada por código: el envoltorio exploratorio anexa a cada
   respuesta un bloque determinista con especialista fuente, herramienta, cifras
   clave, sello y la etiqueta EXPLORATORIO. Prefijo visual automático para todo
   dato con `validado: false` — la advertencia sobrevive a la narración porque
   no depende de ella.
4. `tests/test_gate_security.py`: fija por test la invariante del invocation_id
   del gate (ejecutar sin token del turno inmediatamente anterior → excepción
   controlada de violación de gate; token invalidado por cambio de universo →
   ídem). Un cambio de semántica en ADK rompe en rojo, no en silencio.
5. `tests/test_atribucion.py`: evaluador automático que falla si el Director
   reporta una cifra de retorno, riesgo o correlación sin nombrar al
   especialista fuente.
6. Memorándum de convocatoria: la fase solicitar del gate renderiza la Orden
   Preparatoria de Sesión con el lenguaje de la propuesta (parámetros fijados,
   qué hará el comité, solicitud de confirmación) — revisión de orden, no peaje.
7. Limpieza de inferencia: eliminar todo nombre de modelo de docs y código;
   config.yaml declara niveles y asignaciones (nivel_1, nivel_2, nivel_3).

## Definition of Done
make check verde con los dos tests nuevos; demo en adk web documentada en el PR
(apertura con mesa, consulta con ficha, «¿qué tenemos?»); grep de nombres de
modelos fuera de config.yaml devuelve vacío; Estado actualizado; PR.

## Estado
(pendiente — actualizar al cerrar el sprint)
