# ADR 007: Orquestador con Workflow y reparto de trabajo entre LLM y código

- Fecha: 2026-09-17
- Sprint: S3
- Estado: aceptada (deriva de ADR-005; verificada con corridas reales el 2026-09-17)

## Contexto
ADR-005 eligió `Workflow` para la topología de S3. Faltaba decidir qué nodos son agentes LLM
y cuáles código, cómo se corta el bucle y quién escribe las cifras del informe, bajo las
reglas de CLAUDE.md: los agentes llegan al núcleo solo por `tools/` y un LLM nunca produce
cifras finales.

## Decisión
    iniciar → [market_analyst ∥ quant] → constructor → asegurar_candidatos → validador
                                             ↑__________ REINTENTAR ___________|
                                                     REPORTAR → reporter → cerrar

- **LLM solo donde hay juicio o redacción**: `market_analyst` (ADR-006), `constructor`
  (elige técnica recomendada y qué máximos endurecer tras un rechazo, vía el tool
  `construir_candidatos`) y `reporter` (narrativa).
- **Código donde no hay nada que decidir**: `quant` y `validador` son nodos-función que
  llaman a los mismos FunctionTools (`estimar_mercado`, `validar_candidato`). Un
  `status=error` ahí lanza `EtapaFallidaError`.
- **Bucle**: el validador enruta `REINTENTAR` si RECHAZADA e iteración < 
  `validacion.max_iteraciones_constructor`; si no, `REPORTAR` (una sola ruta hacia el
  reporter: `Workflow` no admite dos aristas al mismo destino). El tool repite el tope como
  segunda barrera.
- **Red de seguridad del constructor**: si el LLM no deja una ronda nueva de candidatos,
  `asegurar_candidatos` construye la propuesta por defecto y lo anota en el informe.
- **Informe**: tablas y cifras las renderiza `agents/reporter/reporte.py` desde `RunState`.
  El LLM recibe una hoja de hechos con las cifras ya formateadas y solo redacta; los
  porcentajes de su narrativa que no figuren en la hoja se delatan en el propio informe.
- **Persistencia**: `cerrar` arma `RunState` (revalida todos los contratos y su coherencia
  cruzada), lo marca COMPLETADA o FALLIDA ("sin cartera aprobada") y escribe
  `runs/<run_id>/run_state.json` y `reporte.md`. `run_id` = timestamp UTC con microsegundos.
- Los contratos grandes viajan por el estado de sesión como JSON; `iniciar` fija
  `fecha_decision` antes de abrir las ramas paralelas.

## Alternativas descartadas
- **Constructor determinista** (regla fija ante cada criterio incumplido): más reproducible,
  pero es justo la decisión con matices que el proyecto quiere delegar; el tool acota el daño
  (solo endurece límites) y la red de seguridad cubre el fallo del LLM.
- **Quant y validador como LlmAgent con tools**: dos llamadas al modelo por paso para no
  decidir nada, y un punto más de fallo.
- **Reporter que redacta el informe entero**: un LLM transcribiendo decenas de cifras
  acabará alterando alguna.

## Consecuencias
- Verificado: `adk web` carga un `Workflow` como `root_agent` y un `BaseAgent` a medida
  funciona como nodo (riesgos abiertos en ADR-005). Queda el de Agent Engine para S4.
- Si el grafo lanza una excepción a mitad de corrida no se escribe `runs/`; S4 decidirá si
  hace falta persistir corridas fallidas por error.
- El validador usa pesos fijos; validar la técnica con `risk.reestimada` sigue pendiente
  (con views de un LLM no hay views históricas sin look-ahead).
