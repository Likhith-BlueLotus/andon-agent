# syntax=docker/dockerfile:1
# Cloud Run Job image for the eval (infra/deploy_eval_job.sh). Build context = repo root.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
# dev group: eval.report needs matplotlib
RUN uv sync --frozen --no-install-project
ENV PATH="/app/.venv/bin:$PATH"
COPY config.py ./
COPY agents ./agents
COPY analytics ./analytics
COPY simulator ./simulator
COPY eval ./eval
# anomaly models (B2, B1 context)
COPY data/models ./data/models
# truth, labels and the store are NOT in the image: pulled from GCS at start (see the job command)
ENTRYPOINT ["python", "-m"]
CMD ["eval.run_eval", "--help"]
