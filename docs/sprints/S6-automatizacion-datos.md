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
Cerrado el 2026-09-19 (rama `sprint/S6-automatizacion-datos`, PR contra `main`).

### Desviaciones del spec
- **403, no 401**: Tiingo responde `403 {"detail": "Invalid token."}` a un token ausente o
  inválido. El provider trata 401 y 403 como error de credencial (sin reintento).
- **Solo meses cerrados**: Tiingo fecha el mes en curso a su fin de mes (futuro) con el precio
  del día. Escribirlo rompería la continuidad de la actualización siguiente, así que ni se pide
  ni se escribe. El CSV pasó de 61 a 60 filas (pierde el 2026-09 provisional que se había
  cargado a mano) y la fecha de decisión es 2026-08-31 hasta que cierre septiembre.
- **`ACEPTAR_DISCREPANCIAS=1` y `SIMULAR=1`**, que el spec no pedía: sin un cauce explícito,
  "decide un humano" significaba editar el CSV a mano. Salta solo la comparación de retornos.
- **La lógica vive en `data/actualizacion.py`** y `scripts/update_prices.py` es un CLI delgado:
  así las barreras se prueban sin red y sin conocer Tiingo.
- **GCP**: el secreto es opcional (`SECRETO_TIINGO`, vacío por defecto) y **no se creó**: hoy
  ninguna corrida remota actualiza datos, el disco de los contenedores es de solo lectura y un
  secreto inexistente tumbaría el despliegue automático. Comandos en `docs/operacion.md`.

### Logrado
- ADR-011: Tiingo como fuente, el CSV versionado como caché validado (el pipeline nunca lee de
  la red), reescritura completa de la serie ajustada, meses cerrados y las tres barreras.
- `data/tiingo_provider.py`: `TiingoPriceProvider` (EOD, `resampleFreq=monthly`, siempre
  `adjClose`, key por cabecera desde `TIINGO_API_KEY`), errores tipados (credencial, ticker,
  límite con backoff exponencial y `Retry-After`, timeout) y validación de huecos, duplicados y
  precios ≤ 0 por activo. API verificada contra la doc y contra el servicio real. 20 tests con
  `httpx.MockTransport`.
- `data/actualizacion.py` + `scripts/update_prices.py` + `make update-prices`: sanidad →
  continuidad de retornos (0,5 p.p.; perder historia aborta siempre) → escritura atómica
  (temporal en la misma carpeta, releído con `CSVPriceProvider`, respaldo, `os.replace`, 3
  respaldos). Resumen en `runs/actualizaciones/<marca>/` también al abortar; códigos 0/1/2.
  22 tests: discrepancia inyectada y retorno absurdo inyectado abortan dejando la carpeta byte
  a byte intacta; fallo en el `replace` y CSV ilegible para el consumidor no tocan el vigente.
- **Fixture congelado** `tests/fixtures/precios_referencia.csv` (hash fijado en un test); diez
  archivos de tests leían el CSV vivo. Verificado corriendo la suite con `data/precios.csv`
  escondido: 344 pasan. Golden intacto.
- **Corrida real** (2026-09-19): VOOG/BNS/VB 60 meses, IBIT 32. VOOG, VB e IBIT empalman con
  ≤ 0,03 p.p. en 59/59/31 retornos. **BNS abortó** (2021-12, 2023-09, 2023-10; hasta 1,65
  p.p.): Tiingo tiene dos dividendos de BNS duplicados (22 en 20 trimestres; uno de ellos con el
  importe en CAD) y sobrestima su retorno total ≈ 3,4 % acumulado. Impacto medido: peso de BNS
  6,36 % → 6,50 %. El usuario aceptó la serie de Tiingo (resumen `20260919T173210`); la corrida
  siguiente salió `SIN_CAMBIOS` con continuidad verde sin aceptar nada.
- **Pipeline completo con el CSV nuevo**: corrida real `20260919T173243_033535Z`, APROBADA a la
  primera (70/2/5,3/22,7), Sharpe OOS 0,56, caída máxima 28,8 %; 0,8 p.p. de rotación frente a
  la corrida de cierre de S5 (`make comparar`), casi toda por las views del analista.
- `docs/operacion.md`: ritual mensual con `make update-prices` como paso 1, tabla de mensajes
  y qué hacer ante cada aborto. `.env.example`, `.gitignore`/`.dockerignore`/`.gcloudignore`.
- `make check` verde: 344 tests (44 nuevos), ruff y mypy strict sin avisos. `httpx` pasa a
  dependencia declarada (ya estaba en `uv.lock`).

### Pendiente
- Reportar a Tiingo los dividendos duplicados de BNS. Si lo corrigen, la continuidad abortará
  una vez por esos mismos meses: será la corrección y se acepta igual (ADR-011).
- Tras el merge, dev queda con otro `config_hash` y con el CSV nuevo: el replay rechazará las
  corridas anteriores, como está diseñado.
- Primera actualización "de verdad" a primeros de octubre (entrará 2026-09): comprobar que el
  ritual documentado se sigue sin fricción.
- `--extra_packages data` de `make deploy-prod` copia la carpeta entera: si hay respaldos
  locales viajan a prod (inofensivo, pero sobra). Secreto de Tiingo en GCP, si se habilita la
  actualización remota. Programar la ejecución (fuera de alcance de S6).
- Extender el histórico antes de 2021-09: es cambiar `datos.tiingo.fecha_inicio`; la
  continuidad comparará solo la ventana solapada. Antes, revisar los dividendos de cada activo
  en el tramo nuevo: no habrá CSV contra el que contrastarlos.
- Siguen abiertos de S2-S5: el analista no conoce el prior de equilibrio; `sensibilidad` de los
  candidatos; intervalos de confianza OOS; persistir corridas fallidas; proteger `main`.

### Aprendizajes
- **Una fuente "oficial" también se equivoca, y la barrera lo cazó en su primer uso.** Comparar
  retornos (no niveles) con una tolerancia ajustada separó limpio el redondeo del CSV antiguo
  (≤ 0,03 p.p.) de un dividendo duplicado (≥ 0,57 p.p.). Sin el CSV manual como testigo el
  error habría entrado en silencio: al extender historia no habrá testigo.
- Sondear el servicio real antes de escribir los mocks cambió tres cosas del diseño (403, mes
  en curso con fecha futura, el CSV de digrin ya era ajustado). La documentación web de Tiingo
  es una SPA que casi no se deja leer; los mocks copian respuestas reales.
- Una validación que aborta necesita su vía de escape diseñada, o la vía de escape acaba siendo
  saltarse la validación entera.
- "El usuario ya puso la key" merece un `grep -c` antes de asumirlo: no estaba, y todo lo que no
  dependía de ella se pudo adelantar igual.
- mypy con pandas-stubs: `first_valid_index()`, `idxmax()` y `DataFrame.at` tipan demasiado
  ancho o demasiado estrecho; `dropna().index[0]`, `argmax()` y `to_numpy()` tipan bien.
