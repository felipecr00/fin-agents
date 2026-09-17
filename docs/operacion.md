# Operación: desplegar, verificar, ver logs y costos

Decisiones y porqués: [ADR-008](adr/008-camino-de-despliegue-cloud-run-dev-agent-runtime-prod.md)
(camino de despliegue) y [ADR-009](adr/009-runstate-en-la-nube-y-verificacion-de-reproducibilidad.md)
(RunState en la sesión y replay). Herramienta de análisis: ninguna salida constituye asesoría
financiera.

| | dev | prod |
|---|---|---|
| Dónde | Cloud Run, servicio `fin-agents-dev` | Vertex AI Agent Engine (Agent Runtime), `fin-agents-prod` |
| Proyecto / región | `ai-exploratory` / `us-central1` | ídem; el modelo se pide a `global` (`agentes.ubicacion_vertex`) |
| Empaquetado | `Dockerfile` + `uv sync --locked`, construido por Cloud Build | plantilla de `adk deploy agent_engine` + `requirements.txt` exportado de `uv.lock` |
| Gemini | Vertex AI modo express: API key en Secret Manager (`gemini-api-key`) | Vertex AI con la identidad del servicio; sin secretos |
| Sesiones | en memoria, 1 instancia máx. (desechable) | administradas por Agent Engine (persisten el `RunState`) |
| Acceso | solo autenticado (identity token, `roles/run.invoker`) | IAM de Vertex AI (access token, `roles/aiplatform.user`) |
| Se despliega | en cada merge a `main` | a mano: Actions → deploy → Run workflow → `prod` |

## Desplegar

Automático: `.github/workflows/deploy.yaml`. Todo despliegue pasa antes por `make check`.

A mano (mismos comandos que usa el workflow), con `gcloud auth login` y, para prod,
`gcloud auth application-default login`:

    make deploy-dev  PROYECTO=ai-exploratory
    make deploy-prod PROYECTO=ai-exploratory AGENT_ENGINE_ID=456971875910680576

Sin `AGENT_ENGINE_ID`, `deploy-prod` crea una instancia **nueva** (y otra factura de cómputo):
úsalo solo la primera vez y guarda el id en la variable `AGENT_ENGINE_ID` de GitHub.

Rotar la llave de Gemini de dev: `gcloud secrets versions add gemini-api-key --data-file=-` y
`make deploy-dev PROYECTO=… VERSION_SECRETO=<n>` (la versión va fijada, no `latest`).

## Verificar (corrida real + replay)

    make corrida-dev  PROYECTO=ai-exploratory
    make corrida-prod PROYECTO=ai-exploratory AGENT_ENGINE_ID=456971875910680576

Ejecuta el pipeline remoto, guarda su `RunState` en `runs/remotas/<run_id>/` y repite el núcleo
en local con las views y restricciones de esa corrida. Debe terminar en
`OK: la corrida remota reproduce la local`. Referencias (2026-09-17): dev 110 valores,
desviación máxima 8.9e-16; prod 140 valores, 1.3e-15; tolerancia 1e-8.

- `otra semilla u otro config.yaml`: lo desplegado no corresponde a tu copia local. Despliega
  o cambia de rama; no es un fallo numérico.
- `DIFERENCIA …`: el núcleo dio otro número en la nube. Es un hallazgo: no subas la tolerancia.
- HTTP 403 en dev: a tu usuario le falta `roles/run.invoker` sobre el servicio.
- HTTP 500: error dentro de la corrida; mira los logs. Los 429/503 de Gemini se reintentan
  solos (`agentes.reintentos_modelo`: 6 intentos, ≈ 1 min de espera en total); si aun así
  llega uno, la cuota está agotada de verdad: espera unos minutos.

## Logs

    make logs-dev PROYECTO=ai-exploratory

- Dev, en vivo: `gcloud beta run services logs tail fin-agents-dev --region us-central1`.
- Prod: Logs Explorer con
  `resource.type="aiplatform.googleapis.com/ReasoningEngine" resource.labels.reasoning_engine_id="456971875910680576"`,
  o por CLI:
  `gcloud logging read 'resource.type="aiplatform.googleapis.com/ReasoningEngine"' --project ai-exploratory --limit 50 --freshness 1h`.
- Builds de dev: consola de Cloud Build (el enlace sale en la salida de `make deploy-dev`).
- Consola de prod (playground, sesiones): Vertex AI → Agent Engine → `fin-agents-prod`.

## Costos aproximados (precios de lista consultados el 2026-09-17; verifícalos antes de presupuestar)

| Concepto | Precio | Para este proyecto |
|---|---|---|
| Gemini 3.5 Flash | US$1,50 / 1M tokens de entrada, US$9,00 / 1M de salida (incluye *thinking*) | Medido en prod: corrida de 2 iteraciones = 6 llamadas, 7.751 + 5.498 tokens ≈ **US$0,06**; de 1 iteración ≈ US$0,04 |
| Cloud Run (dev) | por vCPU-s y GiB-s mientras atiende; escala a cero | Una corrida ≈ 30-60 s de 1 vCPU/1 GiB. Dentro de la capa gratuita (180.000 vCPU-s/mes) → **≈ US$0** |
| Cloud Build | 2.500 min-build gratis/mes | Un build ≈ 2-3 min → **≈ US$0** con decenas de merges al mes |
| Artifact Registry | 0,5 GB gratis; luego ≈ US$0,10/GB-mes | Cada imagen ≈ 0,4 GB y se acumulan: **limpia versiones viejas** de `cloud-run-source-deploy` o pon una política de limpieza |
| Secret Manager | 6 versiones activas gratis | **≈ US$0** |
| Agent Engine (prod) | ≈ US$0,085 / vCPU-h y US$0,009 / GiB-h; capa gratuita ≈ 50 vCPU-h y 100 GiB-h al mes | Por defecto Agent Engine deja **1 instancia siempre encendida** (hasta 100). `apps/pipeline/.agent_engine_config.json` lo cambia a 0-1 instancias de 1 vCPU / 2 GiB: escala a cero y el uso ocasional cabe en la capa gratuita → **≈ US$0**, a cambio de un arranque en frío en la primera petición. Con el valor por defecto serían ≈ 730 vCPU-h/mes ≈ US$60/mes |
| Sesiones administradas | ≈ US$0,25 / 1.000 eventos almacenados | Una corrida ≈ 19 eventos → **≈ US$0,005**; borra sesiones de prueba si se acumulan |

Orden de magnitud: uso ocasional (unas decenas de corridas al mes) ≈ **US$2-5/mes de modelo**; el
coste dominante posible es el cómputo de Agent Engine si se vuelve a `min_instances` ≥ 1.
Borrar prod: `gcloud beta ai reasoning-engines delete 456971875910680576 --region us-central1`
o desde la consola.

## Identidades y permisos (mínimos)

| Identidad | Para qué | Permisos |
|---|---|---|
| `fin-agents-run@…` | cuenta con la que corre el contenedor de dev | `secretmanager.secretAccessor` solo sobre `gemini-api-key` |
| `<nº>-compute@developer…` | la usa Cloud Build para construir | `run.builder` |
| `fin-agents-deployer@…` | la suplanta GitHub Actions vía WIF | `run.sourceDeveloper`, `serviceusage.serviceUsageConsumer`, `aiplatform.user` (proyecto); `iam.serviceAccountUser` solo sobre `fin-agents-run` (identidad del servicio) y sobre `<nº>-compute@developer…` (identidad del build) |
| Agente de servicio de Agent Engine | corre prod y llama a Gemini | lo gestiona Google |

## Workload Identity Federation: puesta en marcha (una sola vez)

Qué es: GitHub emite en cada job un token OIDC firmado que dice "soy el repo X, rama Y". GCP
confía en ese emisor a través de un *provider* dentro de un *pool* y canjea el token por
credenciales de **una hora** de la cuenta desplegadora. No existe ninguna llave que filtrar.

    export PROYECTO=ai-exploratory REPO=felipecr00/fin-agents
    export NUM=$(gcloud projects describe $PROYECTO --format 'value(projectNumber)')

1. API que emite las credenciales de corta vida y la de federación:

       gcloud services enable iamcredentials.googleapis.com sts.googleapis.com --project $PROYECTO

2. **Pool**: contenedor de identidades externas. Solo agrupa; no da acceso a nada.

       gcloud iam workload-identity-pools create github --location global \
         --display-name "GitHub Actions" --project $PROYECTO

3. **Provider**: declara que confiamos en los tokens de GitHub, qué campos del token se
   copian a atributos (`attribute-mapping`) y cuáles se **exigen** (`attribute-condition`):
   solo este repo y solo la rama `main`. Un fork, otro repo o un PR no pueden ni entrar.

       gcloud iam workload-identity-pools providers create-oidc fin-agents --location global \
         --workload-identity-pool github --project $PROYECTO \
         --issuer-uri "https://token.actions.githubusercontent.com" \
         --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
         --attribute-condition "assertion.repository == '$REPO' && assertion.ref == 'refs/heads/main'"

4. **Cuenta de servicio desplegadora**: la identidad con la que actúa el workflow.

       gcloud iam service-accounts create fin-agents-deployer \
         --display-name "fin-agents: despliegue desde GitHub Actions" --project $PROYECTO

5. Permisos mínimos de esa cuenta. Los tres primeros son a nivel de proyecto: desplegar a
   Cloud Run desde código fuente, usar las APIs del proyecto y gestionar Agent Engine. Los
   otros dos son `serviceAccountUser` sobre cuentas concretas: `fin-agents-run`, para poder
   asignarla como identidad del servicio, y la cuenta de cómputo por defecto, porque Cloud
   Build ejecuta el build *como* ella y quien lo lanza debe poder "actuar como" esa cuenta.
   La doc de Cloud Run no lista este último y un Owner no lo nota; sin él el primer despliegue
   desde GitHub falló con `caller does not have permission to act as service account`.

       for ROL in roles/run.sourceDeveloper roles/serviceusage.serviceUsageConsumer roles/aiplatform.user; do
         gcloud projects add-iam-policy-binding $PROYECTO --condition None \
           --member "serviceAccount:fin-agents-deployer@$PROYECTO.iam.gserviceaccount.com" --role $ROL
       done
       gcloud iam service-accounts add-iam-policy-binding fin-agents-run@$PROYECTO.iam.gserviceaccount.com \
         --member "serviceAccount:fin-agents-deployer@$PROYECTO.iam.gserviceaccount.com" \
         --role roles/iam.serviceAccountUser --project $PROYECTO
       gcloud iam service-accounts add-iam-policy-binding $NUM-compute@developer.gserviceaccount.com \
         --member "serviceAccount:fin-agents-deployer@$PROYECTO.iam.gserviceaccount.com" \
         --role roles/iam.serviceAccountUser --project $PROYECTO

   Ojo: en este proyecto la cuenta de cómputo por defecto tiene `roles/editor` (valor de
   fábrica de GCP), así que poder actuar como ella es, de hecho, un permiso amplio. Endurecerlo
   = cuenta de build propia (`gcloud run deploy --build-service-account`) con solo
   `run.builder`; queda como pendiente.

6. El enlace: las identidades del pool cuyo atributo `repository` sea este repo pueden
   **suplantar** a la cuenta desplegadora (`workloadIdentityUser`). Es lo que sustituye a la llave.

       gcloud iam service-accounts add-iam-policy-binding fin-agents-deployer@$PROYECTO.iam.gserviceaccount.com \
         --role roles/iam.workloadIdentityUser --project $PROYECTO \
         --member "principalSet://iam.googleapis.com/projects/$NUM/locations/global/workloadIdentityPools/github/attribute.repository/$REPO"

7. Variables del repositorio (no son secretos: son identificadores):

       gh variable set GCP_PROJECT_ID  --body "$PROYECTO"
       gh variable set GCP_REGION      --body "us-central1"
       gh variable set GCP_DEPLOY_SA   --body "fin-agents-deployer@$PROYECTO.iam.gserviceaccount.com"
       gh variable set GCP_WIF_PROVIDER --body "projects/$NUM/locations/global/workloadIdentityPools/github/providers/fin-agents"
       gh variable set AGENT_ENGINE_ID --body "456971875910680576"

Comprobación: tras el merge a `main`, el job `dev` de `deploy` debe autenticarse y desplegar.
Si `auth` falla con *"The given credential is rejected by the attribute condition"*, el job no
corre sobre `main` de este repo (es lo que debe pasar en cualquier otro caso).
