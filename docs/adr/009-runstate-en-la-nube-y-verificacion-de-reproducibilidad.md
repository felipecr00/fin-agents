# ADR 009: RunState en la nube y qué significa "la corrida remota reproduce la local"

- Fecha: 2026-09-17
- Sprint: S4
- Estado: aceptada (aprobada por el usuario el 2026-09-17)

## Contexto
`cerrar` escribe `runs/<run_id>/run_state.json` en `RAIZ_PROYECTO/runs`. En un contenedor ese
disco es efímero (Cloud Run) o inaccesible (Agent Engine), así que el `RunState` de una corrida
remota hoy no se puede recuperar. Y el DoD de S4 exige comparar una corrida remota con la
local: "misma semilla, mismos números en RunState".

Medido el 2026-09-17 con dos corridas locales reales (`runs/20260917T131313…` y
`…T140754…`): misma semilla (42) y mismo `config_hash`; `quant_estimates` **idéntico** byte a
byte; `market_views` **distinto** (lo emite el LLM; temperatura 0.2) y, por tanto, pesos
distintos (50/7/29/14 tras una segunda iteración vs. 70/2/5/23). Dos corridas *locales* ya no
coinciden entre sí en lo que depende del LLM: comparar "remota vs. local" corrida contra
corrida no mide nada.

## Decisión
1. **El `RunState` final viaja también en el estado de sesión** (`run_state_json`), además
   del disco. En prod lo persisten las sesiones administradas; en dev se lee de la sesión
   justo después de la corrida. La escritura a disco pasa a ser tolerante: si el directorio
   no es escribible se anota en `notas_corrida` y la corrida no falla.
2. **"Reproduce" = repetición determinista (*replay*)**: `scripts/verificar_corrida_remota.py`
   toma el `RunState` remoto y, en local, con el mismo `config.yaml` y datos:
   - exige `semilla` y `config_hash` iguales;
   - recalcula `quant_estimates` y exige igualdad;
   - por cada ronda, reconstruye los candidatos con las `market_views` y las restricciones
     **de la corrida remota** (la parte que decidió el LLM se toma como dato) y revalida el
     recomendado; exige los mismos pesos, métricas y veredicto.
   Igualdad numérica con tolerancia `reproducibilidad.tolerancia_replay` en `config.yaml`
   (propuesta: 1e-8): local es macOS/arm64 (Accelerate) y la nube linux/x86-64 (OpenBLAS); la
   igualdad bit a bit entre BLAS distintos no está garantizada, y SLSQP amplifica el último
   dígito. El script informa la desviación máxima observada, no solo pasa/falla.
3. El mismo replay se ejecuta como test de integración con LLM falso (corrida → replay → 0
   diferencias) para que entre en `make check`.

## Alternativas descartadas
- **Comparar dos corridas completas** (remota y local): falla por el LLM aunque el núcleo sea
  idéntico; obligaría a "ajustar" la comparación hasta que pase.
- **Temperatura 0 + semilla del modelo** para forzar views iguales: Gemini no garantiza
  determinismo ni entre llamadas ni entre backends (API vs. Vertex), y cambiaría el
  comportamiento del analista solo para satisfacer un test.
- **Endpoint remoto con views inyectadas** (saltarse al analista en la nube): añade una
  superficie de API solo para pruebas; el replay local obtiene la misma garantía sin tocar
  el servicio.
- **Subir `runs/` a un bucket** (montaje GCS en Cloud Run o artifact service `gs://`): útil
  como archivo histórico, pero Agent Engine no admite montajes y duplicaría lo que las
  sesiones administradas ya guardan. Se puede añadir después sin cambiar esta decisión.

## Consecuencias
- `RunState` solo guarda las restricciones vigentes al final, no las de cada ronda: el replay
  repite la **optimización de la última ronda** y la **validación de todas**; las rondas
  anteriores se informan como "no repetibles". Guardarlas por ronda es un cambio de contrato
  (ADR aparte) que hoy no se justifica.
- Medido en local (tres corridas reales de S3/S4 y los tests con LLM falso): 110-140 valores
  comparados por corrida, desviación máxima 0.0 en la misma máquina.
- No cambia ningún contrato: `RunState` se serializa tal cual en una clave nueva del estado.
- El estado de sesión crece (~decenas de KB por corrida); irrelevante al volumen del proyecto.
- La garantía que se verifica es la que CLAUDE.md promete: misma entrada = misma salida **en
  los módulos puros**. La variabilidad del LLM queda explícitamente fuera y documentada.
- Si la desviación entre plataformas superara la tolerancia, es un hallazgo sobre el núcleo
  (condicionamiento del optimizador), no un motivo para relajar la tolerancia sin ADR.
