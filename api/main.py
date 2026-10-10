"""Andon Agent API. Phase 0: health check only; the SSE investigation endpoints land in Phase 3.

Health lives at /health, not /healthz: Cloud Run's front end reserves paths ending in "z".
"""

import os

from fastapi import FastAPI

import config

# Interactive docs only off Cloud Run (K_SERVICE is set by the Cloud Run runtime).
_ON_CLOUD_RUN = bool(os.environ.get("K_SERVICE"))

app = FastAPI(
    title="Andon Agent API",
    version=config.APP_VERSION,
    docs_url=None if _ON_CLOUD_RUN else "/docs",
    redoc_url=None,
    openapi_url=None if _ON_CLOUD_RUN else "/openapi.json",
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": config.APP_VERSION,
        "theme": config.THEME,
        "store_backend": config.STORE_BACKEND,
    }
