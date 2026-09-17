.PHONY: install lint type test check run-local eval clean

install:        ## dependencias con uv
	uv sync

lint:
	uv run ruff check src tests apps scripts && uv run ruff format --check src tests apps scripts

type:
	uv run mypy src

test:
	uv run pytest tests/unit tests/golden tests/integration -q

check: lint type test   ## puerta obligatoria antes de todo commit final

run-local:      ## UI de desarrollo de ADK (apps/: market_analyst; credenciales en .env o el entorno)
	uv run adk web apps

eval:           ## evalsets de agentes (S5)
	uv run adk eval apps tests/eval

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
