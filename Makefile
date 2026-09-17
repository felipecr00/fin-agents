# uv del PATH o, si no está, el instalado con pip --user (~/.local/bin).
UV ?= $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)

# Despliegue (ADR-008). Sin valores por defecto para el proyecto: se pasan por entorno o por
# línea de comandos (`make deploy-dev PROYECTO=… REGION=…`); en GitHub Actions son variables.
PROYECTO ?= $(GOOGLE_CLOUD_PROJECT)
REGION ?= $(GOOGLE_CLOUD_LOCATION)
SERVICIO_DEV ?= fin-agents-dev
SA_EJECUCION ?= fin-agents-run@$(PROYECTO).iam.gserviceaccount.com
SECRETO_GEMINI ?= gemini-api-key
VERSION_SECRETO ?= 1

.PHONY: install lint type test check run-local eval clean deploy-dev url-dev corrida-dev logs-dev

install:        ## dependencias con uv
	$(UV) sync

lint:
	$(UV) run ruff check src tests apps scripts && $(UV) run ruff format --check src tests apps scripts

type:
	$(UV) run mypy src

test:
	$(UV) run pytest tests/unit tests/golden tests/integration -q

check: lint type test   ## puerta obligatoria antes de todo commit final

run-local:      ## UI de desarrollo de ADK (apps/: market_analyst; credenciales en .env o el entorno)
	$(UV) run adk web apps

eval:           ## evalsets de agentes (S5)
	$(UV) run adk eval apps tests/eval

deploy-dev:     ## Cloud Run (dev): Cloud Build construye el Dockerfile y despliega, en un solo comando
	@test -n "$(PROYECTO)" -a -n "$(REGION)" || { echo "Faltan PROYECTO y REGION"; exit 1; }
	gcloud run deploy $(SERVICIO_DEV) --source . \
		--project $(PROYECTO) --region $(REGION) \
		--service-account $(SA_EJECUCION) \
		--set-secrets GOOGLE_API_KEY=$(SECRETO_GEMINI):$(VERSION_SECRETO) \
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

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
