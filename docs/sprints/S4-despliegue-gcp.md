# Sprint 4 — Despliegue GCP

## Objetivo
Dev en Cloud Run, prod en Vertex AI Agent Engine, despliegue automatizado desde GitHub.

## Prerrequisitos
Proyecto GCP con facturación activa, APIs de Vertex AI habilitadas, Artifact Registry.

## Alcance
- Contenedor del servicio; despliegue a Cloud Run (entorno dev).
- Despliegue a Vertex AI Agent Engine con sesiones administradas (prod).
- `.github/workflows/deploy.yaml`: en merge a main despliega a dev; promoción a prod
  manual (workflow_dispatch). Autenticación con Workload Identity Federation — ninguna
  llave de servicio en el repo. Secretos en Secret Manager.
- Verificar la guía vigente de despliegue de ADK antes de codificar.

## Definition of Done
- Merge a main → dev desplegado automáticamente.
- Una corrida remota reproduce el resultado local (mismos datos, misma semilla).
- Documento breve de operación en docs/ (cómo desplegar, cómo ver logs, costos aprox).

## Estado
Cerrado el 2026-09-17 (rama `sprint/S4-despliegue-gcp`, PR contra `main`). Proyecto
`ai-exploratory`, región `us-central1`.

### Desviaciones del spec (aprobadas en sesión)
- **Construcción con Cloud Build** (`gcloud run deploy --source .`) en lugar de construir la
  imagen en local o en el runner: el usuario prefirió el despliegue más sencillo (ADR-008).
- **"Reproduce el resultado local" = replay determinista**, no comparar dos corridas: dos
  corridas locales con la misma semilla ya difieren en lo que decide el LLM (ADR-009).
- La doc de ADK renombró Agent Engine a "Agent Runtime on Agent Platform"; el comando
  (`adk deploy agent_engine`) y el recurso (`reasoningEngines`) no cambian.

### Logrado
- ADR-008 (camino de despliegue) y ADR-009 (RunState en la sesión y replay), con la guía
  vigente verificada en `adk.dev/deploy/` y en el paquete instalado (google-adk 2.9.1).
- **Dev — Cloud Run** (`fin-agents-dev`): `Dockerfile` con `uv sync --locked`, `make deploy-dev`,
  solo autenticado, 0-1 instancias, llave de Vertex AI (modo express) en Secret Manager con
  versión fija, leída por `fin-agents-run` (único permiso: `secretAccessor` sobre ese secreto).
- **Prod — Agent Engine** (`reasoningEngines/456971875910680576`): `make deploy-prod` con
  `--extra_packages`, `requirements.txt` exportado de `uv.lock`, sesiones administradas, el LLM
  con la identidad del servicio (sin secretos) y escalado 0-1 (`.agent_engine_config.json`).
  **Agent Engine sirve el `Workflow` raíz**: cerrado el riesgo abierto en ADR-005.
- **CI/CD**: `deploy.yaml` (merge a `main` → `make check` → dev; prod solo `workflow_dispatch`)
  con Workload Identity Federation: provider restringido a este repo y a `refs/heads/main`,
  cuenta `fin-agents-deployer` con cuatro roles mínimos, identificadores como variables del
  repo. Ninguna llave JSON en el repo ni en GitHub Secrets. `ci.yaml` pasa a ser reutilizable.
- Código: `RAIZ_PROYECTO` = primer ancestro con `config.yaml`; `cerrar` deja el `RunState` en
  la sesión y tolera disco no escribible; `orchestrator/replay.py`; `agents/modelo.py`
  (`agentes.ubicacion_vertex: global`); `scripts/corrida_remota.py` (Cloud Run y Agent Engine).
- **DoD — corrida remota que reproduce la local** (misma semilla 42 y `config_hash`):
  dev `20260917T150434_222970Z`, 110 valores, desviación máxima 8.9e-16; prod
  `20260917T154015_108936Z` (2 iteraciones), 140 valores, 1.3e-15, y `20260917T222549_740999Z`
  (tras el escalado a cero), 110 valores, 8.9e-16. Tolerancia 1e-8. linux/x86-64 vs. macOS/arm64.
- `docs/operacion.md`: desplegar, verificar, logs, costos (corrida de 2 iteraciones medida:
  6 llamadas, 7.751 + 5.498 tokens ≈ US$0,06) y la puesta en marcha de WIF paso a paso.
- `make check` verde: 236 tests (16 nuevos).

### Añadido tras el cierre (rama `sprint/S4-reintentos-modelo`)
- Reintentos del modelo: la llave de Vertex AI en modo express devolvió 429 en 3 de ~10
  corridas del 2026-09-17 (cuota por minuto) y cada uno tumbaba la corrida. `resolver_modelo`
  entrega siempre el cliente del modelo con `HttpRetryOptions` desde `agentes.reintentos_modelo`
  (6 intentos; esperas 2-4-8-16-32 s). Verificado con una API local falsa (dos 429 → respuesta
  correcta en 3 peticiones; sin reintentos, `_ResourceExhaustedError`) y con corrida real.

- Primer despliegue automático (merge de #5): WIF autenticó y `make check` pasó, pero el build
  falló: a `fin-agents-deployer` le faltaba `iam.serviceAccountUser` sobre la cuenta de cómputo
  por defecto (identidad del build). Corregido en IAM y en `docs/operacion.md`. El PR #6 se
  mergeó contra la rama de S4 y no contra `main`; este PR lo lleva a `main`.

### Pendiente
- Cuenta de build propia (`--build-service-account`) con solo `run.builder`: la de cómputo por
  defecto tiene `roles/editor` y el desplegador puede actuar como ella.
- **Verificar tras el merge** que el job `dev` de `deploy` se autentica por WIF y despliega: el
  provider solo admite `main`, así que no se puede probar desde el PR. Dev quedó con la imagen
  anterior a `ubicacion_vertex` (otro `config_hash`); ese primer despliegue lo pone al día.
- Proteger `main` (pendiente desde S0) y, si se quiere una aprobación humana para prod, un
  *environment* de GitHub con revisores en el job `prod`.
- Política de limpieza de imágenes en `cloud-run-source-deploy` (Artifact Registry).
- `RunState` no guarda las restricciones de cada ronda: el replay repite la optimización de la
  última y la validación de todas. Guardarlas es un cambio de contrato (ADR aparte).
- Sigue abierto de S3: persistir corridas que fallan por excepción (un error del modelo que
  agote los reintentos sigue siendo un HTTP 500 sin `RunState`): S5.

### Aprendizajes
- De nuevo, el paquete instalado manda sobre la web: `adk deploy agent_engine` ya no serializa
  un `AdkApp` (despliega un contenedor con `adk api_server`), importa `vertexai` sin declararlo
  y `adk deploy cloud_run` no admite paquetes extra. Nada de eso está en la guía.
- Probar `adk api_server` en local con el layout del contenedor (solo dependencias de
  producción, disco de solo lectura) destapó casi todo antes del primer despliegue.
- Credenciales de google-genai: con `GOOGLE_CLOUD_PROJECT`/`LOCATION` definidos el SDK ignora
  la API key y usa ADC; una llave restringida a `aiplatform` necesita
  `GOOGLE_GENAI_USE_ENTERPRISE=True`; los modelos de Nivel 1 vigentes solo se sirven en `global`. La llave free
  tier de la API de AI Studio (20 peticiones/día por modelo) no sirve ni para una tarde de pruebas.
- Los valores por defecto de la nube cuestan: Agent Engine deja 1 instancia encendida (≈ US$60
  al mes) si no se declara `min_instances: 0`.
- `read -s` en un comando pensado para pegarse o ejecutarse con un botón crea secretos vacíos:
  para el usuario, mejor comandos sin interacción que lean de `.env` por tubería.
- La guarda de `config_hash` del replay trabajó sola dos veces (config cambiado tras una
  corrida): distinguir "otra configuración" de "otro número" evita diagnósticos falsos.
