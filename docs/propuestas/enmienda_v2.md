# Enmienda Técnica a la Arquitectura v2 (aprobada)

> Cierra las cinco brechas identificadas en la revisión de la propuesta y sella
> el diseño antes de la ejecución. Ante conflicto con arquitectura_v2.md, esta
> enmienda prevalece.

## 1. Evolución del Simulador: De Block-Bootstrap a Deep Generative

El Agente Simulador se reestructura en dos generaciones para respetar el
principio de "endurecer detrás del uso". El prerrequisito innegociable para
ambas es el cambio a datos diarios (ej. Tiingo).

- Generación 1 (Inmediata y Defendible): Simulación no paramétrica mediante
  Block-Bootstrap para preservar la autocorrelación, combinada con simulación
  paramétrica usando cópulas empíricas y distribuciones de colas pesadas
  (ej. t-Student multivariada). Esto genera mundos contrafactuales rigurosos
  sin requerir convergencia de redes neuronales.
- Generación 2 (Condicional): VAEs secuenciales o Normalizing Flows. Solo se
  habilitan si la Gen 1 demuestra incapacidad para capturar asimetrías
  extremas o cambios de régimen, y operarán estrictamente sobre el dataset
  diario ampliado.

## 2. Filtro Tributario Consultivo (Advisory Tax Guard)

La heurística de "evitar ventas con ganancia" se degrada de ley absoluta a
advertencia calificada, reconociendo estrategias legítimas como la recolección
de pérdidas fiscales (tax-loss harvesting) y los matices del SII.

- El Fintual Execution Guard emite escenarios etiquetados explícitamente:
  "Costo fiscal estimado: $X CLP".
- Incluye un disclaimer inyectado en el prompt de salida: "Esta es una
  estimación algorítmica, no asesoría tributaria o financiera. Valida el
  tratamiento de dividendos extranjeros con tu contador."
- El usuario tiene un botón de Override (Forzar Ejecución) que le permite al
  sistema cruzar la advertencia y ejecutar la orden si la estrategia del
  usuario así lo requiere.

## 3. El Gate de Promoción (Lab → Real)

Se formaliza la frontera más crítica del sistema. Ninguna señal sobrevive al
laboratorio para tocar dinero real sin una ceremonia explícita.

- Se crea un nuevo artefacto tipado: `PromotionAct.json`.
- Para que el Portfolio Allocator (Capa Real) pueda consumir una señal del
  Estratega (Capa Lab), el Orquestador debe iniciar la fase de promoción.
- El usuario recibe un resumen que incluye: la lógica de la señal, el Deflated
  Sharpe Ratio (DSR), el desempeño bajo estrés de la Gen 1 y una solicitud
  formal de confirmación. Si el usuario aprueba, el `PromotionAct.json` se
  sella y la señal pasa a producción.

## 4. Abstracción de Inferencia (`config.yaml`)

El documento de arquitectura dejará de mencionar nombres comerciales
perecederos.

- El spec se redacta basándose en capacidades funcionales: Nivel 1 (Frontier
  LLM) para razonamiento/código, Nivel 2 (Edge/Cuantizado) para NLP local, y
  Nivel 3 (Determinista) para álgebra.
- La asignación real (ej. apuntar el Orquestador a un modelo concreto) vivirá
  exclusivamente como pares de clave-valor en un archivo `config.yaml`,
  permitiendo rotar modelos en minutos según el costo o las actualizaciones
  del mercado.

## 5. Reconocimiento de Deuda en el Sprint 2

Se asume el costo de adelantar la creación de las personas (Sub-Agentes) para
priorizar la experiencia de la "Sala de Inversión".

- El spec del Sprint 2 incluye ahora una nota formal de costo aceptado: "El
  desdoblamiento temprano del Estadístico y el Escéptico requiere evaluar y
  calibrar dos contextos de LLM adicionales antes de que la capa operativa
  esté completamente madura."
- La justificación aprobada es que resolver la opacidad del comité monolítico
  desde el inicio mejora dramáticamente la adopción y auditabilidad del
  sistema por parte del CIO.
