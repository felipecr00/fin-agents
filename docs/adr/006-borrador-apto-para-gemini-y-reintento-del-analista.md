# ADR 006: El analista emite un borrador apto para Gemini; el contrato lo construye el código

- Fecha: 2026-09-17
- Sprint: S3
- Estado: propuesta (a revisar por el usuario en el checkpoint del hito 2)

## Contexto
El spec de S3 pide `market_analyst` como `LlmAgent` con `output_schema=MarketViews` y
reintento si la salida no valida. Medido sin red con google-adk 2.9.1 / google-genai 2.24.0:

- ADK pasa `output_schema` como `response_schema`; google-genai lo convierte a su `Schema` y
  **rechaza `MarketViews`** antes de llamar al modelo: `exclusiveMinimum` (`gt=0` en
  `horizonte_meses` y `confianza`) y `patternProperties` (`coeficientes: dict[Ticker, float]`)
  no están permitidos, ni con API key ni con Vertex. El test
  `test_gemini_acepta_el_esquema_del_borrador_pero_no_el_contrato` lo fija.
- Si el JSON del modelo no valida contra `output_schema`, `LlmAgent` lanza
  `pydantic.ValidationError` y la invocación muere: ADK no reintenta. `RetryConfig` reintenta
  a ciegas (sin decirle al modelo qué falló) y solo dentro de un `Workflow`.
- `MarketViews` contiene `fecha_decision` y `activos`, que el LLM no debe decidir.

## Decisión
1. El LLM emite `MarketViewsBorrador` (`agents/market_analyst/borrador.py`): mismo contenido
   que `View`, con `coeficientes` como lista `{activo, coeficiente}` y cotas inclusivas. El
   borrador es un detalle interno del agente; no es un contrato ni cruza fronteras.
2. `MarketAnalyst` (`BaseAgent`) envuelve al `LlmAgent`: convierte el borrador a `MarketViews`
   poniendo él la fecha de decisión, el universo y el horizonte (`config.yaml`), y solo
   entonces escribe `market_views` en el estado. El contrato no cambia.
3. Si falla el JSON, el esquema o cualquier validador del contrato (suma cero, universo,
   fuente posterior a la decisión), guarda el error en el estado y vuelve a ejecutar el LLM,
   cuya instrucción incluye ese error. Máximo `agentes.max_intentos_analista`; agotados,
   lanza `ViewsInvalidasError`. Errores del modelo (credenciales, cuota, red) no se
   reintentan aquí: se propagan.
4. Sin herramientas de búsqueda, la instrucción prohíbe inventar URLs en `fuente`.

## Alternativas descartadas
- **Relajar `MarketViews`** (quitar `gt`, cambiar el `dict`): debilita un contrato aprobado
  para acomodar a un proveedor; exigiría tocar `portfolio/` y sus tests.
- **`response_json_schema` a mano con el JSON Schema del contrato**: ADK no lo valida, y no
  pude comprobar sin credenciales que Gemini acepte `patternProperties`.
- **`after_model_callback`**: puede sustituir la respuesta, no pedir otra.
- **`RetryConfig` del nodo**: reintento ciego con backoff; el modelo repetiría el error.

## Consecuencias
- Dos esquemas que mantener en paralelo; `a_contrato` y sus tests son el puente.
- `fuente` será casi siempre "conocimiento general del modelo, sin verificar" hasta que el
  analista tenga búsqueda (requiere un agente en dos pasos: `output_schema` + `tools` solo
  es nativo en Vertex, ADR-005). Candidato para S5.
- La memoria del modelo puede ser posterior a una `fecha_decision` histórica: el contrato
  solo protege `fecha_fuente`. Para backtests de la cadena completa se usan views fijas.
