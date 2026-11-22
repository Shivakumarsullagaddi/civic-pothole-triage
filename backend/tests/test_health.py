from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_db_and_model():
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ok", "degraded"}
    assert "ok" in body["database"]
    assert isinstance(body["model"]["loaded"], bool)
    assert body["model"]["mode"] in {"advisory", "enforce"}
