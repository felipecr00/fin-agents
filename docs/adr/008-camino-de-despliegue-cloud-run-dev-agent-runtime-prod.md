# ADR 008: Camino de despliegue — Cloud Run (dev) y Agent Engine/Agent Runtime (prod)

- Fecha: 2026-09-17
- Sprint: S4
- Estado: aceptada (aprobada por el usuario el 2026-09-17 con una enmienda: construir con Cloud Build
  para simplificar el despliegue)

## Contexto
S4 pide dev en Cloud Run, prod en Vertex AI Agent Engine y despliegue desde GitHub sin llaves
de servicio. Verificado el 2026-09-17 contra la guía oficial (`google.github.io/adk-docs/deploy/`
→ 301 a `adk.dev/deploy/`; fuentes en `google/adk-docs`) y contra el paquete instalado
(google-adk 2.9.1, `google/adk/cli/cli_deploy.py`):

| Hecho verificado | Dónde |
|---|---|
| La doc renombró "Vertex AI Agent Engine" a **"Agent Runtime on Agent Platform"**. El comando sigue siendo `adk deploy agent_engine`, el recurso sigue siendo `reasoningEngines` y la API `aiplatform.googleapis.com`. | `adk.dev/deploy/agent-runtime/` |
| Opciones de la guía: Agent Runtime, Cloud Run, GKE, contenedor propio. Para Cloud Run: `adk deploy cloud_run` ("recommended for Python") **o** `gcloud run deploy` con Dockerfile propio y `get_fast_api_app` ("offers flexibility"). | `adk.dev/deploy/cloud-run/` |
| `adk deploy cloud_run` copia **solo la carpeta del agente** e instala `google-adk` + su `requirements.txt` con `pip` (sin lock). No admite `--extra_packages`. | `cli_deploy.py` (`to_cloud_run`, `extra_packages_copy=''`) |
| `adk deploy agent_engine` en 2.9.1 **ya no serializa un `AdkApp`**: genera un Dockerfile cuyo `CMD` es `adk api_server … --session_service_uri=agentengine://<recurso>` y lo sube con `source_packages`. Admite `--extra_packages` (cada uno queda en `/app/<basename>`, con `/app` en `PYTHONPATH`) y `--agent_engine_id` para actualizar en sitio. `--staging_bucket`, `--adk_app`, `--requirements_file` están deprecados. | `cli_deploy.py` (`to_agent_engine`, `_DOCKERFILE_TEMPLATE`) |
| Secretos: la guía crea `GOOGLE_API_KEY` en Secret Manager y da `roles/secretmanager.secretAccessor` a la cuenta de servicio del servicio. | `adk.dev/deploy/cloud-run/` |
| `gcloud run deploy --source .` construye con Cloud Build usando el `Dockerfile` del directorio, guarda la imagen en el repositorio `cloud-run-source-deploy` de Artifact Registry (lo crea solo) y despliega. Roles: desplegador `roles/run.sourceDeveloper` + `roles/serviceusage.serviceUsageConsumer` + `roles/iam.serviceAccountUser` sobre la identidad del servicio; la cuenta de cómputo por defecto (la que usa Cloud Build) `roles/run.builder`. Para secretos como variable de entorno la doc recomienda **fijar la versión**, no `latest`. | `docs.cloud.google.com/run/docs/deploying-source-code`, `…/configuring/services/secrets` |
| Sin `--session_service_uri`, Cloud Run cae a sesiones en memoria, que se pierden al reciclarse la instancia. | ídem |

Evidencia medida (local, 2026-09-17): `adk api_server apps` —el mismo proceso que corre dentro
del contenedor en **ambos** destinos— sirvió el `Workflow` raíz por HTTP: `POST /apps/pipeline/
users/u1/sessions` + `POST /run` completaron una corrida real con `gemini-3.5-flash` en 24 s
(13 eventos, veredicto APROBADA, `runs/20260917T140754_899029Z/`), sin errores en el log. Como
Agent Engine ejecuta ese mismo `adk api_server`, el riesgo abierto en ADR-005 ("¿despliega
Agent Engine un `Workflow` raíz?") deja de depender de la serialización de `AdkApp`; se
confirma con el despliegue real del hito 2.

Nuestro agente (`apps/pipeline`) no es autocontenido: importa `investmentsys` (`src/`), y lee
`config.yaml` y `data/precios.csv` relativos a `RAIZ_PROYECTO`.

## Decisión
1. **Dev = Cloud Run con Dockerfile propio** (camino "gcloud CLI" de la guía). Imagen
   `python:3.11-slim` + `uv sync --locked --no-dev`: las mismas versiones de numpy/scipy/pandas
   que `uv.lock` fija en local. `CMD`: `adk api_server` sobre `apps/`, sin UI web. Se despliega
   con **un solo comando**, `gcloud run deploy --source .` (`make deploy-dev`): Cloud Build
   construye con nuestro Dockerfile y gestiona el repositorio de imágenes. El mismo comando
   sirve en la Mac (sin Docker) y en GitHub Actions.
   - `--no-allow-unauthenticated`; se invoca con identity token.
   - Sesiones `memory://` y `--max-instances=1` (con sesiones en memoria, dos instancias
     romperían "crear sesión → correr"). Dev es desechable; la durabilidad es de prod.
   - Gemini por **API key desde Secret Manager**
     (`--set-secrets GOOGLE_API_KEY=gemini-api-key:<versión>`, versión fija), leída por una
     cuenta de servicio de ejecución propia cuyo único permiso es `secretAccessor` sobre ese
     secreto. La llave es de **Vertex AI en modo express** (API key de GCP restringida a
     `aiplatform.googleapis.com`) con `GOOGLE_GENAI_USE_ENTERPRISE=True` y **sin**
     `GOOGLE_CLOUD_PROJECT`/`GOOGLE_CLOUD_LOCATION` en el entorno. Medido el 2026-09-17: con
     proyecto y región definidos el SDK ignora la llave y usa ADC; sin el flag la manda a
     `generativelanguage` y recibe 403 `API_KEY_SERVICE_BLOCKED`. La llave free tier de la
     Gemini API usada en S3 tiene 20 peticiones/día por modelo (~4 corridas): inservible.
2. **Prod = `adk deploy agent_engine`** (camino "standard deployment" de la guía) con
   `--extra_packages src/investmentsys config.yaml data`, `requirements.txt` generado con
   `uv export --locked --no-dev` (mismas versiones que dev y local) y `--agent_engine_id`
   para actualizar siempre la misma instancia. Sesiones administradas
   (`agentengine://`, el valor por defecto del despliegue). Gemini vía Vertex AI con la
   identidad del servicio: **prod no tiene ningún secreto**.
3. **`RAIZ_PROYECTO` se localiza subiendo desde `config.py` hasta encontrar `config.yaml`**,
   en vez de `parents[2]`: da el mismo resultado en el repo y funciona en `/app` de ambos
   contenedores sin variables de entorno nuevas.
4. **CI/CD** (`.github/workflows/deploy.yaml`): `push` a `main` → `make check` →
   `make deploy-dev`; prod solo por `workflow_dispatch`. Autenticación con Workload Identity
   Federation (`google-github-actions/auth`), provider restringido a
   `assertion.repository == 'felipecr00/fin-agents'`. Una cuenta de servicio desplegadora con
   roles mínimos: `run.sourceDeveloper`, `serviceusage.serviceUsageConsumer`,
   `iam.serviceAccountUser` (solo sobre la cuenta de ejecución) y `aiplatform.user` (prod).
   Ninguna llave JSON en el repo ni en GitHub Secrets; los ids de proyecto/provider van como
   *variables* de GitHub (no son secretos).

## Alternativas descartadas
- **`adk deploy cloud_run`** (recomendado por la guía): solo copia la carpeta del agente y no
  admite paquetes extra; habría que vendorizar `investmentsys`, `config.yaml` y los datos dentro
  de `apps/pipeline/`. Además instala dependencias sin lock.
- **Dev también con Vertex AI en lugar de API key**: eliminaría el único secreto y haría que
  dev y prod usen el mismo backend de Gemini (S3 ya enseñó que los backends difieren: el 400
  por `additionalProperties`). Resuelto a medias por la llave que consiguió el usuario: es de
  Vertex AI (modo express), así que dev ya usa el backend de prod y sigue ejercitando Secret
  Manager. Pasar dev a la identidad del servicio (sin llave) sigue siendo cambiar dos flags.
- **SDK de Python (`client.agent_engines.create(agent=AdkApp(...))`)**: el CLI ya no va por
  ahí, y obligaría a que el `Workflow` sea serializable con cloudpickle, que es justo el
  riesgo de ADR-005.
- **Agents CLI / Agent Starter Pack**: genera un proyecto entero con Terraform y pipelines
  propios; sustituiría el harness de S0 en lugar de desplegarlo.
- **Llave JSON de cuenta de servicio en GitHub Secrets**: prohibida por el spec.
- **Construir la imagen fuera de Cloud Build** (docker en la Mac o en el runner + push a
  Artifact Registry + `--image`): era la propuesta inicial por pedir menos permisos. El
  usuario prefirió la sencillez: tres pasos y un repositorio que administrar frente a un
  comando, y Docker no corre en su Mac.

## Consecuencias
- Cloud Build corre con la cuenta de cómputo por defecto (`roles/run.builder`): es una
  identidad más con permisos en el proyecto, el precio de la sencillez. `.gcloudignore`
  decide qué se sube al build (nunca `.env`, `runs/` ni `.venv/`).
- Dos empaquetados (Dockerfile propio en dev, plantilla de ADK en prod) con las **mismas
  versiones bloqueadas**; la comparación de resultados de ADR-009 es la red que detecta si
  divergen.
- Dev y prod usan el mismo backend (Vertex AI); solo cambia la credencial (llave express en
  dev, identidad del servicio en prod). **Dev y prod van en `us-central1`** (decisión del
  usuario; `southamerica-west1` no sirve el modelo).
- Los Gemini 3.x solo se sirven en el endpoint `global` de Vertex. Medido el 2026-09-17: el
  primer despliegue a Agent Engine sirvió el `Workflow` raíz (cierra el riesgo de ADR-005) y
  el quant calculó, pero el analista recibió 404 porque la plantilla de ADK fija
  `GOOGLE_CLOUD_LOCATION=us-central1`. Solución: `agentes.ubicacion_vertex: global` en
  `config.yaml` y `agents/modelo.py`, que entrega un `Gemini(client_kwargs={"location": …})`
  —el patrón que documenta ADK— solo cuando el cliente va a Vertex con proyecto. Las sesiones
  administradas siguen en la región del recurso.
- `adk deploy agent_engine` importa `vertexai` y ADK 2.9.1 no lo declara: el grupo de
  dependencias `deploy` lo instala para `make deploy-prod` y fija `google-cloud-aiplatform`
  en el `requirements.txt` de prod (sin él, ADK añade la línea sin versión).
- `adk deploy agent_engine` escribe un `Dockerfile` en una carpeta temporal del directorio de
  trabajo; se usa `--temp_folder` bajo `build/` (gitignored) para no pisar el nuestro.
- La plantilla de ADK fija `python:3.11-slim`, igual que `.python-version`. Subir de Python
  pasa a ser una decisión acoplada a ADK.
- Si el hito 2 mostrara que Agent Engine no sirve el `Workflow`, el plan B de ADR-005 (workflow
  agents clásicos) sigue disponible; la evidencia local indica que no hará falta.
