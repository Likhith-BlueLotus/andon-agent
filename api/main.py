"""Andon Agent API. Phase 0: health check only; the SSE investigation endpoints land in Phase 3."""

from fastapi import FastAPI

import config

app = FastAPI(title="Andon Agent API", version=config.APP_VERSION)


@app.get("/healthz")
def healthz() -> dict:
    return {
        "status": "ok",
        "version": config.APP_VERSION,
        "theme": config.THEME,
        "store_backend": config.STORE_BACKEND,
    }
