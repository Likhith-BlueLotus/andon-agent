# syntax=docker/dockerfile:1
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY config.py ./
COPY agents ./agents
COPY api ./api
COPY analytics ./analytics
# simulator code only (plant model, store, manuals); generated data never enters the image
COPY simulator ./simulator

FROM python:3.12-slim
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PORT=8080
USER app
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
