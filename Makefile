# uv del PATH o, si no está, el instalado con pip --user (~/.local/bin).
UV ?= $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)

# Despliegue (ADR-008). Sin valores por defecto para el proyecto: se pasan por entorno o por
# línea de comandos (`make deploy-dev PROYECTO=… REGION=…`); en GitHub Actions son variables.
PROYECTO ?= $(GOOGLE_CLOUD_PROJECT)
REGION ?= us-central1
SERVICIO_DEV ?= fin-agents-dev
SA_EJECUCION ?= fin-agents-run@$(PROYECTO).iam.gserviceaccount.com
# Nombre del secreto con la llave del LLM: sale de config.yaml (inferencia.nivel_1.secreto_llave).
SECRETO_LLM ?= $(shell sed -n 's/^ *secreto_llave: *//p' config.yaml)
VERSION_SECRETO ?= 1
# Opcional (S6): con SECRETO_TIINGO=tiingo-api-key dev recibe TIINGO_API_KEY. Vacío por defecto:
# hoy ninguna corrida remota actualiza datos y un secreto inexistente tumbaría el despliegue.
SECRETO_TIINGO ?=
VERSION_SECRETO_TIINGO ?= 1
# Prod (Agent Engine). Vacío = crear una instancia nueva; con id = actualizarla en sitio.
AGENT_ENGINE_ID ?=
NOMBRE_PROD ?= fin-agents-prod
STAGING_PROD := build/prod
COMA := ,
# Un caso suelto: make eval EVALSET=tests/eval/market_analyst.evalset.json:ambigua_bns
EVALSET ?= tests/eval/market_analyst.evalset.json
APP ?= pipeline

.PHONY: install lint type test nombres check universo update-prices run-local bitacora eval eval-analista eval-director evalset sensibilidad comparar clean deploy-dev url-dev corrida-dev logs-dev deploy-prod corrida-prod

install:        ## dependencias con uv
	$(UV) sync

lint:
	$(UV) run ruff check src tests apps scripts && $(UV) run ruff format --check src tests apps scripts

type:
	$(UV) run mypy src

test:
	$(UV) run pytest tests/unit tests/golden tests/integration tests/test_gate_security.py tests/test_atribucion.py -q

nombres:        ## DoD de S9: nombres comerciales de modelos fuera de config.yaml (debe salir vacío)
	$(UV) run python -m tests.unit.test_nombres_de_modelos

check: lint type test   ## puerta obligatoria antes de todo commit final

universo:       ## Gestor de Datos: make universo [ARGS="incorporar QQQ --cap 22 --metodologia '…'"]
	$(UV) run python scripts/universo.py $(if $(ARGS),$(ARGS),diagnosticar)

update-prices:  ## paso 1 del ritual mensual: Tiingo → validar → data/series/ (ADR-011, S7)
# SIMULAR=1 valida y resume sin escribir. ACEPTAR_DISCREPANCIAS=1 solo tras revisar TÚ un aborto
# por continuidad. Necesita TIINGO_API_KEY en el entorno o en .env. Código 1 = abortado.
	$(UV) run python scripts/update_prices.py $(if $(SIMULAR),--dry-run,) \
		$(if $(ACEPTAR_DISCREPANCIAS),--aceptar-discrepancias,)

run-local:      ## UI de ADK: elige `equipo` (el Director, entrada por defecto); `pipeline` = modo comando
	$(UV) run adk web apps

bitacora:       ## sigue EN VIVO la bitácora del comité desde otra terminal: make bitacora [RUN=<run_id>]
	$(UV) run python scripts/ver_bitacora.py $(RUN)

eval: eval-analista eval-director  ## los dos evalsets contra el modelo REAL; código 1 si algún caso falla

eval-analista:  ## evalset del analista con `adk eval` y métrica propia (ADR-010)
# `adk eval` siempre termina en 0 e imprime una tabla muy ancha: el resumen por caso y el código
# de salida los pone scripts/resumen_eval.py a partir del resultado que ADK deja en disco.
	$(UV) run --group eval adk eval apps/market_analyst $(EVALSET) \
		--config_file_path tests/eval/test_config.json
	$(UV) run --group eval python scripts/resumen_eval.py apps/market_analyst

eval-director:  ## evalset del Director con el arnés propio, un mundo aislado por caso (ADR-015)
# CASOS="saludo degradar_a_neutral" corre solo esos. Casos: tests/eval/casos_director.yaml
	$(UV) run python scripts/eval_director.py $(CASOS)

evalset:        ## regenera el evalset de ADK desde tests/eval/casos_market_analyst.yaml
	$(UV) run python scripts/generar_evalset.py

sensibilidad:   ## sensibilidad del núcleo BL a retornos, covarianzas y parámetros → runs/sensibilidad/
	$(UV) run python scripts/analisis_sensibilidad.py $(if $(RUN_STATE),--run-state $(RUN_STATE),)

comparar:       ## diff estructurado entre dos corridas: make comparar A=<run_id> B=<run_id>
	@test -n "$(A)" -a -n "$(B)" || { echo "Uso: make comparar A=<run_id> B=<run_id>"; exit 1; }
	$(UV) run python scripts/comparar_corridas.py $(A) $(B)

deploy-dev:     ## Cloud Run (dev): Cloud Build construye el Dockerfile y despliega, en un solo comando
	@test -n "$(PROYECTO)" -a -n "$(REGION)" || { echo "Faltan PROYECTO y REGION"; exit 1; }
	gcloud run deploy $(SERVICIO_DEV) --source . \
		--project $(PROYECTO) --region $(REGION) \
		--service-account $(SA_EJECUCION) \
		--set-secrets GOOGLE_API_KEY=$(SECRETO_LLM):$(VERSION_SECRETO)$(if $(SECRETO_TIINGO),$(COMA)TIINGO_API_KEY=$(SECRETO_TIINGO):$(VERSION_SECRETO_TIINGO),) \
		--set-env-vars GOOGLE_GENAI_USE_ENTERPRISE=True \
		--no-allow-unauthenticated \
		--min-instances 0 --max-instances 1 \
		--memory 1Gi --cpu 1 --timeout 300 --quiet

url-dev:
	@gcloud run services describe $(SERVICIO_DEV) --project $(PROYECTO) --region $(REGION) \
		--format 'value(status.url)'

corrida-dev:    ## corrida real contra dev + replay local (ADR-009)
	$(UV) run python scripts/corrida_remota.py $$($(MAKE) -s url-dev)

logs-dev:
	gcloud run services logs read $(SERVICIO_DEV) --project $(PROYECTO) --region $(REGION) --limit 100

deploy-prod:    ## Agent Engine (prod): mismas versiones que uv.lock, sesiones administradas
# El grupo `deploy` trae el SDK de Vertex que usa `adk deploy`; también fija su versión en prod.
# Agent Engine despliega UNA app: APP=pipeline (modo comando, por defecto) o APP=equipo (el
# Director). Promover `equipo` a prod es una decisión de operación (docs/operacion.md).
	@test -n "$(PROYECTO)" || { echo "Falta PROYECTO"; exit 1; }
	@test -f apps/$(APP)/.agent_engine_config.json || { echo "APP=$(APP) no es desplegable"; exit 1; }
	rm -rf $(STAGING_PROD) && mkdir -p $(STAGING_PROD)/$(APP)
	cp apps/$(APP)/__init__.py apps/$(APP)/agent.py apps/$(APP)/.agent_engine_config.json \
		$(STAGING_PROD)/$(APP)/
	$(UV) export --locked --no-dev --group deploy --no-emit-project --no-hashes -q \
		-o $(STAGING_PROD)/$(APP)/requirements.txt
	$(UV) run --group deploy adk deploy agent_engine \
		--project $(PROYECTO) --region $(REGION) \
		--display_name $(NOMBRE_PROD) \
		$(if $(AGENT_ENGINE_ID),--agent_engine_id $(AGENT_ENGINE_ID),) \
		--extra_packages src/investmentsys --extra_packages config.yaml --extra_packages data \
		--temp_folder $(CURDIR)/$(STAGING_PROD)/tmp \
		$(STAGING_PROD)/$(APP)

corrida-prod:   ## corrida real contra Agent Engine (sesiones administradas) + replay local
	@test -n "$(AGENT_ENGINE_ID)" || { echo "Falta AGENT_ENGINE_ID"; exit 1; }
	$(UV) run python scripts/corrida_remota.py \
		projects/$(PROYECTO)/locations/$(REGION)/reasoningEngines/$(AGENT_ENGINE_ID)

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
