# Sprint 6 — Automatización de datos de precios (Tiingo)

## Objetivo
Eliminar la actualización manual de `data/precios.csv`: el sistema obtiene precios
mensuales ajustados desde Tiingo, los valida y los persiste, con verificación de
continuidad contra la historia existente.

## Contexto y decisión de fuente
Fuente primaria elegida: **Tiingo** (EOD ajustado por splits/dividendos, resampleo
mensual nativo, free tier 50 req/hora y 1.000 req/día — nuestro uso es ~4 req/mes).
yfinance queda descartado como primaria por no oficial e inestable; digrin queda solo
como referencia histórica de cómo se construyó el CSV original. Registrar esta
decisión como ADR con las alternativas evaluadas (Alpha Vantage como segunda opción).

## Alcance
- `TiingoPriceProvider` implementando la interfaz `PriceProvider` existente:
  - Endpoint EOD con `resampleFreq=monthly`, usando SIEMPRE la columna de precios
    ajustados (adjClose), no el close crudo.
  - API key desde variable de entorno `TIINGO_API_KEY`; nunca en código ni en el repo.
  - Manejo de errores explícito: 401 (key inválida), 404 (ticker), 429 (rate limit
    con reintento y backoff), timeout.
- Comando de actualización `make update-prices` (script `scripts/update_prices.py`):
  1. Descarga la serie mensual completa de cada activo del universo (config.yaml).
  2. **Validación de continuidad**: sobre la ventana solapada con el CSV vigente,
     compara los retornos mensuales; si algún retorno difiere más que la tolerancia
     de config.yaml (sugerido: 0.5 p.p.), ABORTA sin escribir y reporta las fechas
     discrepantes. Una discrepancia grande = ajuste retroactivo (split/dividendo) o
     error de fuente: decide un humano, no el script.
  3. **Validaciones de sanidad**: sin fechas duplicadas ni huecos de meses (salvo el
     inicio tardío conocido de IBIT), sin precios <= 0, sin retornos mensuales
     absurdos (|r| > umbral de config.yaml, sugerido 60% — IBIT es volátil).
  4. Escribe el CSV nuevo de forma atómica (archivo temporal + rename), conserva el
     anterior como `data/precios_backup_<fecha>.csv` (mantener los últimos 3) y
     registra un resumen de la actualización en runs/.
- Actualizar el flujo de operación: `make update-prices` como paso 1 del ritual
  mensual, documentado en el documento de operación de docs/.
- Tests: provider con respuestas HTTP mockeadas (éxito, 401, 429, datos con hueco),
  test de la validación de continuidad con una discrepancia inyectada (debe abortar),
  test de sanidad con un retorno absurdo inyectado (debe abortar), test de escritura
  atómica. En CI todo corre mockeado; documentar en el PR una corrida real.
- GCP: agregar TIINGO_API_KEY a Secret Manager y al despliegue (dev y prod) para que
  las corridas remotas también puedan actualizar datos si se decide habilitarlo.

## Fuera de alcance
- Datos intradiarios o diarios (el sistema opera mensual).
- Extender el histórico antes de sept 2021 (candidato a sprint futuro; si se hace,
  reutilizará este provider cambiando la fecha de inicio).
- Programar la ejecución automática (cron/Scheduler): por ahora la actualización es
  un comando manual dentro del ritual mensual — el humano mira el resumen antes de
  correr el pipeline.

## Definition of Done
- `make update-prices` real contra Tiingo produce un CSV que empalma con el vigente
  (continuidad verde) y el pipeline completo corre igual que antes con el CSV nuevo.
- El golden test sigue verde con los datos originales (los tests usan un fixture
  congelado de precios, no el CSV vivo — si aún no es así, corregirlo en este sprint).
- Los tests de aborto por discrepancia y por retorno absurdo pasan.
- ADR de fuente registrado; documento de operación actualizado; make check verde;
  Estado actualizado; PR mergeado.

## Estado
(pendiente — actualizar al cerrar el sprint)
