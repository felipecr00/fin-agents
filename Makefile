.PHONY: install lint type test check run-local eval clean

install:        ## dependencias con uv
	uv sync

lint:
	uv run ruff check src tests && uv run ruff format --check src tests

type:
	uv run mypy src

test:
	uv run pytest tests/unit tests/golden -q

check: lint type test   ## puerta obligatoria antes de todo commit final

run-local:      ## UI de desarrollo de ADK
	uv run adk web src/investmentsys

eval:           ## evalsets de agentes (S5)
	uv run adk eval src/investmentsys tests/eval

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
