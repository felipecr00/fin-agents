# uv del PATH o, si no está, el instalado con pip --user (~/.local/bin).
UV ?= $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)

.PHONY: install lint type test check run-local eval clean

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

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
