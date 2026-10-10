from fastapi.testclient import TestClient

import config
from api.main import app


def test_health():
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["theme"] == config.THEME
