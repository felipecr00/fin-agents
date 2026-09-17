# ADR 008: Camino de despliegue — Cloud Run (dev) y Agent Engine/Agent Runtime (prod)

- Fecha: 2026-09-17
- Sprint: S4
- Estado: propuesta

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
   que `uv.lock` fija en local. `CMD`: `adk api_server` sobre `apps/`, sin UI web. La imagen se
   construye (en local o en el runner de GitHub), se sube a Artifact Registry y se despliega
   con `gcloud run deploy --image`. Sin Cloud Build: menos permisos para el desplegador.
   - `--no-allow-unauthenticated`; se invoca con identity token.
   - Sesiones `memory://` y `--max-instances=1` (con sesiones en memoria, dos instancias
     romperían "crear sesión → correr"). Dev es desechable; la durabilidad es de prod.
   - Gemini por **API key desde Secret Manager** (`--set-secrets GOOGLE_API_KEY=…:latest`),
     leída por una cuenta de servicio de ejecución propia cuyo único permiso es
     `secretAccessor` sobre ese secreto.
2. **Prod = `adk deploy agent_engine`** (camino "standard deployment" de la guía) con
   `--extra_packages src/investmentsys config.yaml data`, `requirements.txt` generado con
   `uv export --locked --no-dev` (mismas versiones que dev y local) y `--agent_engine_id`
   para actualizar siempre la misma instancia. Sesiones administradas
   (`agentengine://`, el valor por defecto del despliegue). Gemini vía Vertex AI con la
   identidad del servicio: **prod no tiene ningún secreto**.
3. **`RAIZ_PROYECTO` se localiza subiendo desde `config.py` hasta encontrar `config.yaml`**,
   en vez de `parents[2]`: da el mismo resultado en el repo y funciona en `/app` de ambos
   contenedores sin variables de entorno nuevas.
4. **CI/CD** (`.github/workflows/deploy.yaml`): `push` a `main` → `make check` → build, push y
   deploy a dev; prod solo por `workflow_dispatch`. Autenticación con Workload Identity
   Federation (`google-github-actions/auth`), provider restringido a
   `assertion.repository == 'felipecr00/fin-agents'`. Una cuenta de servicio desplegadora con
   roles mínimos: `run.developer`, `artifactregistry.writer` (sobre el repositorio de
   imágenes), `iam.serviceAccountUser` (solo sobre la cuenta de ejecución) y
   `aiplatform.user` (prod). Ninguna llave JSON en el repo ni en GitHub Secrets; los ids de
   proyecto/provider van como *variables* de GitHub (no son secretos).

## Alternativas descartadas
- **`adk deploy cloud_run`** (recomendado por la guía): solo copia la carpeta del agente y no
  admite paquetes extra; habría que vendorizar `investmentsys`, `config.yaml` y los datos dentro
  de `apps/pipeline/`. Además instala dependencias sin lock y exige Cloud Build
  (`cloudbuild.builds.builder` para la cuenta de cómputo por defecto).
- **Dev también con Vertex AI en lugar de API key**: eliminaría el único secreto y haría que
  dev y prod usen el mismo backend de Gemini (S3 ya enseñó que los backends difieren: el 400
  por `additionalProperties`). Se descarta porque el sprint pide ejercitar Secret Manager y
  porque dev reproduce así la configuración local (`.env`). **Es la alternativa donde el
  criterio del usuario cambiaría el diseño**: pasar dev a Vertex es cambiar dos flags.
- **SDK de Python (`client.agent_engines.create(agent=AdkApp(...))`)**: el CLI ya no va por
  ahí, y obligaría a que el `Workflow` sea serializable con cloudpickle, que es justo el
  riesgo de ADR-005.
- **Agents CLI / Agent Starter Pack**: genera un proyecto entero con Terraform y pipelines
  propios; sustituiría el harness de S0 en lugar de desplegarlo.
- **Llave JSON de cuenta de servicio en GitHub Secrets**: prohibida por el spec.
- **Construir con Cloud Build** (`gcloud run deploy --source`): añade permisos de Cloud Build
  y de su bucket al desplegador sin aportar nada que el runner de GitHub no haga.

## Consecuencias
- Dos empaquetados (Dockerfile propio en dev, plantilla de ADK en prod) con las **mismas
  versiones bloqueadas**; la comparación de resultados de ADR-009 es la red que detecta si
  divergen.
- Dev (Gemini API) y prod (Vertex AI) usan backends distintos del mismo modelo. El id fijo
  `gemini-3.5-flash` debe existir en la región de Vertex elegida; se comprueba en el hito 2
  (plan B: `GOOGLE_CLOUD_LOCATION=global` solo para el modelo).
- `adk deploy agent_engine` escribe un `Dockerfile` en una carpeta temporal del directorio de
  trabajo; se usa `--temp_folder` bajo `build/` (gitignored) para no pisar el nuestro.
- La plantilla de ADK fija `python:3.11-slim`, igual que `.python-version`. Subir de Python
  pasa a ser una decisión acoplada a ADK.
- Si el hito 2 mostrara que Agent Engine no sirve el `Workflow`, el plan B de ADR-005 (workflow
  agents clásicos) sigue disponible; la evidencia local indica que no hará falta.
