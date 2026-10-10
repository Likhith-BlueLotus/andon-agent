from fastapi.testclient import TestClient

import config
from api.main import app


def test_healthz():
    r = TestClient(app).get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["theme"] == config.THEME
