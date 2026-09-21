# Imagen del entorno dev (Cloud Run). ADR-008: mismas versiones que uv.lock fija en local.
# Se construye con Cloud Build vía `make deploy-dev` (gcloud run deploy --source .).
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencias primero: esta capa solo se invalida si cambia uv.lock.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# El proyecto se instala editable: investmentsys queda en /app/src y RAIZ_PROYECTO
# (el primer ancestro con config.yaml) resuelve a /app. CLAUDE.md es el readme del paquete.
COPY CLAUDE.md config.yaml ./
COPY data ./data
COPY src ./src
# S11: una sola interfaz (apps/equipo). El modo comando (comando/pipeline) se sirve a su lado
# SOLO como API —`make corrida-dev` y el replay de ADR-009 lo usan—; aquí no hay UI.
COPY apps ./servidos
COPY comando/pipeline ./servidos/pipeline
RUN uv sync --locked --no-dev

RUN adduser --disabled-password --gecos "" agente
USER agente
ENV PATH="/app/.venv/bin:$PATH"

# api_server (sin UI ni endpoints de desarrollo). Sesiones en memoria: dev es desechable y el
# RunState viaja en el estado de sesión (ADR-009). Cloud Run inyecta $PORT.
CMD ["sh", "-c", "exec adk api_server --host 0.0.0.0 --port ${PORT:-8080} --session_service_uri memory:// servidos"]
