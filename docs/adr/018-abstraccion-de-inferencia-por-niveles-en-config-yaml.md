# ADR 018: Abstracción de inferencia por niveles; nombres de modelos solo en `config.yaml`

- Fecha: 2026-09-20
- Sprint: S9
- Estado: aceptada (2026-09-20; decisión tomada en la enmienda v2 §4, aquí se implementa)

## Contexto
La enmienda v2 §4 y la regla global de S9-S12 piden que ningún documento ni código mencione
modelos comerciales: se habla de Nivel 1 (Frontier LLM), Nivel 2 (Edge/cuantizado) y Nivel 3
(determinista), y la asignación real vive SOLO en `config.yaml`. El DoD de S9 exige que el grep
de nombres de modelos fuera de ese archivo salga vacío. Medido al empezar: 46 archivos con
menciones (código, tests, scripts, Makefile, ADRs y Estados de S3-S8, la propuesta v2).
ADR-005 ya fijaba el id del modelo en `config.yaml: agentes.modelo`, pero el código importaba
por nombre la clase cliente del proveedor y los documentos nombraban modelo y proveedor.

## Decisión
- `config.yaml: inferencia` declara `nivel_1` (clase cliente de ADK como `"módulo:Clase"`, id
  fijo del modelo y nombre del secreto de la llave), `nivel_2` (sin asignar), `nivel_3`
  (`determinista`), las `asignaciones` agente → nivel, las marcas vetadas fuera del archivo y
  las excepciones que impone el tooling. `agentes.modelo` desaparece.
- `agents/modelo.py: resolver_modelo(config, agente, modelo)` resuelve el nivel del agente y
  carga la clase cliente por `importlib`: el código no nombra ni al modelo ni al proveedor.
  Rotar de modelo —o de proveedor con cliente en ADK— es editar `config.yaml`.
- `tests/unit/test_nombres_de_modelos.py` (y `make nombres`) recorre todo lo versionado o por
  versionar y falla ante cualquier marca vetada. La lista de marcas vive en `config.yaml`, de
  modo que ni el test las escribe.
- Documentos históricos (ADRs y Estados de S3-S8, la propuesta v2 §9): se reescribieron las
  menciones ("el modelo de Nivel 1", "el proveedor", "la API de AI Studio"); dos ADRs cambiaron
  de nombre de archivo (005 y 006). El razonamiento y las cifras medidas no cambian.

## Alternativas descartadas
- **Exceptuar los documentos históricos del grep.** El DoD dice "fuera de config.yaml"; una
  lista de excepciones crece sola y el grep deja de significar algo.
- **Mantener el import de la clase cliente por nombre** y exceptuar esa línea: deja el cambio
  de proveedor atado a un cambio de código, contra "rotar modelos en minutos".
- **La lista de marcas vetadas en el test.** El test sería el segundo archivo con nombres.

## Consecuencias
- `config_hash` cambia: el replay rechazará corridas anteriores, como está diseñado (ADR-009).
- Excepciones declaradas en `config.yaml: inferencia.excepciones_de_tooling`: el archivo de
  instrucciones del asistente de código y su carpeta de ajustes, cuyos nombres impone la
  herramienta (los referencian `Dockerfile` y `pyproject.toml`). Se excusan literales, nada más.
- La lectura de ADR-005 pierde el detalle de QUÉ versiones se compararon; queda el criterio (id
  fijo, no preview, no alias) y la versión elegida está en `config.yaml` y en su historial git.
- El Makefile toma el nombre del secreto de la llave desde `config.yaml` (`SECRETO_LLM`).
- Una clase cliente que no sea de google-genai puede no aceptar `retry_options`/`client_kwargs`:
  al rotar de proveedor hay que revisar `resolver_modelo` (lo cubre `tests/unit/test_modelo.py`).
