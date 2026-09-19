# ADR 011: Tiingo como fuente de precios y el CSV como caché validado

- Fecha: 2026-09-19
- Sprint: S6
- Estado: aceptada (fuente decidida por el usuario en el spec de S6; la aceptación de las
  discrepancias de BNS, en sesión el 2026-09-19)

## Contexto
`data/precios.csv` se actualizaba a mano desde digrin. S6 pide automatizarlo sin perder lo que
el CSV daba gratis: corridas reproducibles, sin red, con datos que un humano ha mirado.

Verificado el 2026-09-19 en <https://www.tiingo.com/documentation/end-of-day> y, sobre todo,
contra el servicio real (la documentación es una SPA y no detalla casi nada de esto):
- `GET /tiingo/daily/<ticker>/prices?startDate&endDate&resampleFreq=monthly` →
  lista JSON con `date`, `close`, `adjClose`, `divCash`, `splitFactor`… `resampleFreq` admite
  `daily | weekly | monthly | annually`; en mensual, la fecha es el último día hábil (lun-vie).
- Autenticación: cabecera `Authorization: Token <key>` (también admite `?token=`, que no usamos:
  la key acabaría en logs y proxies).
- **Token ausente o inválido → HTTP 403** `{"detail": "Invalid token."}`, no el 401 del spec.
  Ticker desconocido → 404.
- **El mes en curso llega fechado a su fin de mes** (p. ej. `2026-09-30` pedido el 19) con el
  precio del día. El CSV manual tenía ese mismo defecto: su fila 2026-09 era un precio de
  mitad de mes etiquetado como cierre.
- El CSV de digrin **ya era de precios ajustados**: `adjClose` de VOOG en 2021-09 = 42,891
  frente a 42,88. Por eso la continuidad puede compararse retorno a retorno.

## Decisión
1. **Tiingo es la fuente primaria; el CSV versionado sigue siendo lo único que lee el
   pipeline** (`datos.proveedor: csv`). `TiingoPriceProvider` implementa `PriceProvider`, pero
   solo lo usa `make update-prices`. El CSV es un caché validado y revisado: las corridas no
   dependen de la red ni de que Tiingo reexprese su historia entre dos ejecuciones, y el
   replay de ADR-009 sigue siendo posible.
2. **Siempre `adjClose`** (retorno total). Cada actualización **reescribe la serie completa**:
   un precio ajustado se reescala hacia atrás con cada dividendo, así que añadir filas a una
   historia vieja mezclaría bases distintas.
3. **Solo meses cerrados.** Se pide `endDate` = fin del último mes terminado y se filtra por
   si acaso. Consecuencia inmediata: el CSV pasa de 61 a 60 filas (pierde el 2026-09
   provisional) y la fecha de decisión es 2026-08-31 hasta que cierre septiembre.
4. **Tres barreras antes de escribir** (`data/actualizacion.py`, sin red y sin conocer Tiingo):
   sanidad (duplicados, huecos, inicio tardío solo para `activos_inicio_tardio`, precios ≤ 0,
   |retorno| > 60 %), continuidad de **retornos** contra el vigente (tolerancia 0,5 p.p.; los
   niveles pueden diferir; perder historia aborta siempre) y escritura atómica (temporal en la
   misma carpeta, releído con `CSVPriceProvider`, respaldo, `os.replace`; 3 respaldos).
   Todo aborto deja el vigente byte a byte intacto y un resumen en `runs/actualizaciones/`.
5. **La decisión humana tiene un cauce explícito**: `ACEPTAR_DISCREPANCIAS=1` salta solo la
   comparación de retornos (nunca la sanidad ni la pérdida de historia) y queda en el resumen.
   Sin ese cauce, "decide un humano" significaría editar el CSV a mano.
6. **Los tests usan un fixture congelado** (`tests/fixtures/precios_referencia.csv`, hash fijado
   en un test): el golden y los oráculos no pueden depender de un archivo que cambia cada mes.
7. `httpx` pasa a dependencia declarada (ya estaba en `uv.lock` vía google-genai): los tests
   mockean con `httpx.MockTransport`, sin librerías nuevas.
8. El secreto de GCP es opcional (`SECRETO_TIINGO`, vacío por defecto): hoy ninguna corrida
   remota actualiza datos y un secreto inexistente tumbaría el despliegue de cada merge.

### Hallazgo de la primera corrida real: dividendos duplicados de BNS en Tiingo
VOOG, VB e IBIT empalmaron con diferencias ≤ 0,03 p.p. en 59/59/31 retornos. BNS abortó:

| Mes | Retorno CSV (digrin) | Retorno Tiingo | Diferencia |
|---|---|---|---|
| 2021-12 | +14,83 % | +16,09 % | 1,26 p.p. |
| 2023-09 | −3,90 % | −2,24 % | 1,65 p.p. |
| 2023-10 | −9,64 % | −9,07 % | 0,57 p.p. |

Causa, vista en los datos diarios de Tiingo: 22 dividendos en 20 trimestres. El de enero-2022
figura dos veces (2021-12-31 por 0,785 y 2022-01-03 por 0,789 USD) y el de octubre-2023 también
(2023-09-29 por 0,786 USD y 2023-10-02 por 1,06, que es el importe en CAD sin convertir). Su
`adjClose` sobrestima el retorno total de BNS ≈ 3,4 % acumulado; digrin tenía un dividendo por
trimestre. Impacto medido (views de referencia, decisión 2026-08-31): peso de BNS 6,36 % →
6,50 %, resto igual; media histórica anual de BNS 13,8 % → 14,5 %.

**El usuario decidió aceptar la serie de Tiingo tal cual** (`ACEPTAR_DISCREPANCIAS=1`, resumen
`20260919T173210`): el sesgo es pequeño y conocido, y la alternativa era abortar todos los
meses por los mismos tres retornos. La corrida siguiente salió verde sin aceptar nada.

## Alternativas descartadas
- **Alpha Vantage** (segunda opción del spec): tiene serie mensual ajustada, pero su plan
  gratuito es más estrecho (del orden de 25 peticiones al día) y la key viaja en la URL. No se
  volvió a verificar su API en este sprint: habrá que hacerlo si algún día se usa. Queda como
  repuesto: basta otra implementación de `PriceProvider`; las barreras no cambian.
- **yfinance**: no oficial, se rompe sin aviso. **digrin**: sin API; queda como referencia de
  cómo se construyó el CSV original (y como testigo en el hallazgo de BNS).
- **Que el pipeline lea de Tiingo en vivo**: cada corrida dependería de la red y de la historia
  que Tiingo sirva ese día; adiós al replay y a la revisión humana.
- **Modo empalme** (conservar la historia vigente y encadenar solo los meses nuevos): habría
  preservado los dividendos correctos de BNS, pero el CSV dejaría de ser una serie reproducible
  desde la fuente y las correcciones retroactivas legítimas no entrarían nunca.
- **Reconstruir el ajuste nosotros** (`close` + `divCash` deduplicado): convierte un problema de
  datos en lógica financiera propia que habría que mantener y justificar.
- **Escribir el mes en curso**: cada actualización siguiente abortaría por continuidad, y una
  fila fechada a fin de mes con un precio anterior es un look-ahead de etiqueta.

## Consecuencias
- El ritual mensual empieza con un comando; el humano sigue mirando el resumen antes de correr.
- La historia de BNS en el CSV lleva un sesgo conocido de ≈ +3,4 % (2021-12 y 2023-09/10). Si
  Tiingo lo corrige, la continuidad abortará una vez con esos mismos meses: será la corrección,
  y se acepta igual. Pendiente reportarlo a Tiingo.
- Las cifras del pipeline con el CSV vivo ya no coinciden al cuarto decimal con el ejercicio de
  referencia (otra base de ajuste, un mes menos); el golden sigue exacto sobre el fixture.
- `config.yaml` cambia (`datos.tiingo`, `datos.actualizacion`) → otro `config_hash`: el replay
  rechazará las corridas anteriores, como está diseñado.
- La tolerancia de 0,5 p.p. detectó un error real de la fuente en su primer uso y dejó pasar el
  redondeo a 2 decimales del CSV antiguo (≤ 0,03 p.p.): no se toca.
