# Operación: ritual mensual, desplegar, verificar, ver logs y costos

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

## Dos puntos de entrada (S8)

| | `equipo` — el Director de Análisis | `pipeline` — modo comando |
|---|---|---|
| Qué es | conversación: entiende qué necesitas y convoca al especialista o al comité | la corrida formal completa, de una vez, sin conversar |
| Cuándo | el día a día: consultas ("¿correlación VOOG-VB?"), mesa de trabajo, evaluar TU cartera, altas y bajas del universo, ajustar restricciones, y el comité cuando lo decidas | el ritual mensual, corridas remotas con replay (`make corrida-dev/prod`), scripts y CI |
| Cómo | `make run-local` → http://localhost:8000 → app **equipo** | `uv run python scripts/run_pipeline.py`, o app **pipeline** en `adk web` |
| Qué produce | respuestas EXPLORATORIAS (`validado: false` en el dato) y, solo vía comité con tu confirmación, una RECOMENDACIÓN con acta | siempre un acta en `runs/<run_id>/` |
| Acta | `aprobacion` registra el resumen que viste y tu confirmación ([ADR-014](adr/014-gate-del-comite-en-dos-fases-y-resultados-exploratorios.md)) | `aprobacion: null` |

Custodias del Director que viven en las herramientas, no en el prompt:
- **Comité**: `convocar_comite` en dos fases. Primero te presenta el resumen (universo,
  procedencias del prior, restricciones, material); corre solo si confirmas en tu mensaje
  SIGUIENTE. Un cambio de universo o de restricciones entre medias invalida la solicitud.
- **Prior neutral**: degradar TODO el prior exige ver la advertencia todo-o-nada y confirmar en
  un turno posterior ([ADR-015](adr/015-evaluacion-del-director-con-arnes-propio-y-promocion-de-apps-equipo.md)).
- **Obsolescencia**: tras un alta, una baja o un cambio de cap, el Director lista qué resultados
  dejaron de valer; las herramientas los rechazan por `universe_version`.

**En la nube.** dev (Cloud Run) sirve todas las apps: `equipo` está disponible allí desde el
merge de S8. El almacén `data/` del contenedor es de solo lectura: consultar, diagnosticar y
convocar al comité funcionan; altas, bajas y cambios de cap responden "este despliegue no admite
cambios de universo: hazlos en local y redespliega". prod (Agent Engine) despliega UNA app y
sigue siendo `pipeline`; promover el Director es `make deploy-prod APP=equipo …` y es una
decisión de operación que se toma tras usarlo en dev, no un paso de este sprint.

## Ritual mensual

Los primeros días de cada mes, con el mes anterior ya cerrado:

1. **`make update-prices`** — trae de Tiingo la serie mensual ajustada completa, la valida y, si
   todo está verde, reescribe `data/series/<TICKER>.csv` para TODO el universo vigente
   ([ADR-011](adr/011-tiingo-como-fuente-de-precios-y-csv-como-cache-validado.md)) y re-diagnostica
   `data/universo.json` (datos nuevos = otra `universe_version`: lo calculado antes queda obsoleto).
   **Lee el resumen antes de seguir**: meses nuevos por activo, continuidad y diff.
2. `git diff data/`, commit (`chore: precios AAAA-MM`) y PR: las series y el universo versionados
   son lo que usan dev y prod, y su historial en git es el respaldo de verdad.
3. `uv run python scripts/run_pipeline.py` (o `make corrida-dev` tras el despliegue) y
   `make comparar A=<corrida anterior> B=<corrida nueva>`.

### `make update-prices`

| Variante | Qué hace |
|---|---|
| `make update-prices` | descarga, valida y, si todo está verde, escribe |
| `make update-prices SIMULAR=1` | lo mismo sin escribir: para mirar antes de tocar nada |
| `make update-prices ACEPTAR_DISCREPANCIAS=1` | escribe aunque la continuidad difiera. Solo después de haber revisado TÚ el aborto; queda registrado en el resumen. No salta la sanidad ni la pérdida de historia |

- **Credencial**: `TIINGO_API_KEY` en el entorno o en `.env` (ver `.env.example`). Viaja en la
  cabecera `Authorization: Token …`, nunca en la URL. Free tier: 50 peticiones/hora y 1.000/día;
  una actualización son 4.
- **Solo meses cerrados.** Tiingo fecha el mes en curso a su fin de mes (futuro) con el precio
  de hoy; esa fila no se escribe nunca. Correrlo a mitad de mes no aporta nada nuevo.
- **Salida**: resumen en consola y en `runs/actualizaciones/<marca>/resumen.{md,json}`, también
  cuando aborta. Código 0 = escrito, sin cambios o simulación; 1 = abortado por una validación;
  2 = fallo de la fuente. En los tres casos de fallo las series vigentes quedan intactas.
- **Todo o nada entre archivos**: se escriben y validan todos los temporales, se respaldan las
  series vigentes y solo entonces se reemplaza; si un reemplazo falla, se restaura lo ya cambiado.
- **Respaldos**: `data/series/.backups/<marca>/`, los 3 últimos (`datos.actualizacion.backups_a_conservar`),
  ignorados por git. Deshacer: `cp data/series/.backups/<marca>/*.csv data/series/` o `git checkout data/series`.
- **Parámetros**: `config.yaml: datos.tiingo` y `datos.actualizacion`. Extender el histórico =
  cambiar `datos.tiingo.fecha_inicio` (la continuidad comparará solo la ventana solapada).

| Mensaje | Qué significa | Qué hacer |
|---|---|---|
| `continuidad: N retorno(s) difieren…` | en un mes que ya teníamos, el retorno de Tiingo no coincide con el del CSV (tolerancia 0,5 p.p.). Un precio ajustado cambia de NIVEL con cada dividendo, pero no de retorno: si cambia el retorno, la fuente reexpresó un dividendo o split, o tiene un error | mira la tabla de discrepancias y contrasta los dividendos del activo en esas fechas. Si la versión de Tiingo es la correcta, `ACEPTAR_DISCREPANCIAS=1`; si no, no actualices y anótalo |
| `continuidad: el panel nuevo pierde meses` | Tiingo devuelve menos historia que el CSV | no se puede forzar: revisa `fecha_inicio` y el ticker |
| `sanidad: …` | duplicados, huecos, precio ≤ 0, inicio tardío no declarado o \|retorno\| > 60 % | casi seguro un error de la fuente; reintenta otro día. Si es real (un split mal ajustado no lo es), sube el umbral en `config.yaml` con un commit que lo explique |
| `Tiingo rechazó la API key (HTTP 403)` | key ausente, mal copiada o revocada (Tiingo usa 403, no 401) | regenera el token en tiingo.com → Account → API |
| `límite de peticiones (HTTP 429)` | cuota horaria o diaria agotada tras 4 intentos con espera exponencial | espera una hora |

**GCP (opcional, hoy sin uso).** Las corridas remotas leen las series empaquetadas en la imagen; no
actualizan datos. Si algún día se habilita, el secreto se crea sin que la key pase por la
pantalla ni por el historial, y dev lo recibe al desplegar:

    grep '^TIINGO_API_KEY=' .env | cut -d= -f2- | tr -d '\n' | \
      gcloud secrets create tiingo-api-key --data-file=- --project ai-exploratory
    gcloud secrets add-iam-policy-binding tiingo-api-key --project ai-exploratory \
      --member serviceAccount:fin-agents-run@ai-exploratory.iam.gserviceaccount.com \
      --role roles/secretmanager.secretAccessor
    make deploy-dev PROYECTO=ai-exploratory SECRETO_TIINGO=tiingo-api-key

`SECRETO_TIINGO` va vacío por defecto a propósito: un secreto inexistente tumbaría el despliegue
automático de cada merge. En prod (Agent Engine) la variable se declararía en
`apps/pipeline/.agent_engine_config.json`; no se ha hecho porque el disco del contenedor es de
solo lectura y el CSV no podría reescribirse allí.

## Universo: altas, capitalizaciones y prior (S7)

El universo vigente vive en `data/universo.json` (diagnósticos + capitalizaciones CONGELADAS del
prior de Black-Litterman, [ADR-013](adr/013-prior-de-equilibrio-cascada-con-procedencia-y-todo-o-nada.md));
`config.yaml: portafolio.activos` es solo la semilla. Se gestiona conversando con el Director
("agrega NVDA", "saca BNS": ver abajo) o, sin LLM, con `make universo` (las caps van en US$
billones, 10^12):

| Comando | Qué hace |
|---|---|
| `make universo` | diagnóstico: ventana común, activo más corto, qué stress aplica a quién, estado del prior |
| `make universo ARGS="resolver AAPL"` | valida el ticker contra Tiingo y muestra su diagnóstico; no modifica nada |
| `make universo ARGS="incorporar QQQ --cap 22 --metodologia 'cap del Nasdaq-100'"` | alta con cap del usuario (para ETFs: capitalización del subyacente, no AUM; AUM vale como proxy débil y queda anotado) |
| `make universo ARGS="incorporar AAPL"` | alta automática si la fuente da la cap (en el plan gratuito de Tiingo, solo acciones del DOW 30) |
| `make universo ARGS="incorporar QQQ --aceptar-neutral"` | alta sin cap degradando TODO el prior a equiponderado (el informe llevará la advertencia) |
| `make universo ARGS="refrescar-cap BNS --cap 0.12 --metodologia '…'"` | ÚNICA vía para cambiar una cap congelada; sin `--cap`, la pide a la fuente |
| `make universo ARGS="aceptar-neutral"` | confirma la degradación para un universo con caps pendientes |
| `make universo ARGS="retirar BNS"` | saca el activo del universo; su serie se conserva en `data/series/` como caché |

**Alta conversacional (Director).** "agrega X" → el Director llama a `resolver` y te presenta el
diagnóstico (desde cuándo hay datos, qué limita eso). Si la fuente trae la capitalización, la
incorpora al confirmar e informa el valor congelado y su fecha. Si no (ETFs), hace UNA pregunta
con tres opciones, en este orden: (a) aportas la cap del subyacente o del índice [recomendada];
(b) el AUM como proxy débil; (c) degradar TODO el universo a prior neutral, con la advertencia
todo-o-nada. **Alta con el prior pendiente**: el activo entra, Black-Litterman y el comité quedan
bloqueados ("prior sin resolver: falta la cap de X") hasta que aportes la cap (`refrescar_cap`)
o confirmes neutral; HRP, mínima varianza, las estimaciones y el diagnóstico de tu cartera
siguen disponibles. El Director nunca propone el valor de una capitalización.

- **Sin cap y sin aceptar neutral**: el activo entra, pero Black-Litterman queda *no disponible*
  (el informe y la herramienta dicen qué cap falta); HRP y mínima varianza siguen operativos.
- **Todo o nada**: o todas las procedencias son `fuente`/`usuario`, o todas `neutral`. Degradar no
  borra las caps ya congeladas: al llegar la que faltaba, vuelve el prior de mercado.
- Cada cambio deja una línea en `data/universo_historial.jsonl` (acción, cap antes/después,
  versión antes/después) y cambia `universe_version`: `make comparar` lo muestra como cambio de
  INPUT, y las herramientas rechazan cualquier resultado sellado con la versión anterior.
- El informe de cada corrida muestra SIEMPRE la tabla de retornos implícitos π con la procedencia
  de cada peso, las restricciones de la sesión con su origen y las advertencias de historia corta.
- Tras un alta: `git diff data/`, commit (`chore: alta de <TICKER>`) y PR, igual que con los precios.

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

## Evaluar, medir robustez y comparar corridas (S5)

Todo en local; nada de esto se despliega ni entra en CI salvo sus tests unitarios.

| Comando | Qué hace | LLM | Salida |
|---|---|---|---|
| `make eval` | los dos evalsets contra Gemini real: `eval-analista` (11 casos, `adk eval`) y `eval-director` (19 casos, arnés propio con un almacén aislado por caso, [ADR-015](adr/015-evaluacion-del-director-con-arnes-propio-y-promocion-de-apps-equipo.md)); código 1 si alguno falla ([ADR-010](adr/010-evaluacion-del-analista-con-metrica-determinista-en-adk-eval.md)) | sí | `runs/evals/<id>.md` y `apps/market_analyst/.adk/eval_history/` |
| `make eval EVALSET=tests/eval/market_analyst.evalset.json:ambigua_bns` | un solo caso | sí | ídem |
| `make evalset` | regenera el `.evalset.json` tras editar `tests/eval/casos_market_analyst.yaml` | no | `tests/eval/market_analyst.evalset.json` |
| `make sensibilidad [RUN_STATE=runs/<id>/run_state.json]` | sensibilidad de la cartera a sus supuestos ([docs/sensibilidad.md](sensibilidad.md)) | no | `runs/sensibilidad/<fecha>_<hash>/` |
| `make comparar A=<run_id> B=<run_id>` | diff estructurado entre dos `RunState` (locales o de `runs/remotas/`) | no | `runs/comparaciones/<a>__<b>.md` |

- `make eval` instala al vuelo el grupo de dependencias `eval` (`google-adk[eval]`, ~50
  paquetes); no forma parte de `dev` ni de las imágenes.
- Credenciales: las mismas que `make run-local`. `adk eval` carga el `.env` de la raíz: respeta
  lo que ya esté exportado en la shell, pero **añade lo que falte**. Si tu `.env` define
  `GOOGLE_CLOUD_PROJECT`/`GOOGLE_CLOUD_LOCATION` junto a una llave de modo express, el SDK ignora
  la llave aunque hayas hecho `unset` de esas variables (ver `.env.example`). Para que cuente
  solo lo exportado en la shell: `ADK_DISABLE_LOAD_DOTENV=1 make eval`.
- Un caso que falla de forma intermitente es información, no ruido: el LLM no es determinista.
  Repite el caso suelto y mira el criterio incumplido en el resumen.
- Añadir un caso: edita el YAML (noticias **sintéticas**, con su `categoria` y sus `criterios`),
  `make evalset`, `make check` (un test exige que YAML y JSON estén sincronizados) y `make eval`.

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
