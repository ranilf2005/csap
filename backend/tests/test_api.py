from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_liveness_needs_no_auth():
    resp = client.get("/api/v1/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_protected_endpoints_require_a_token():
    assert client.get("/api/v1/connections").status_code == 403
    assert client.get("/api/v1/plugins").status_code == 403


def test_bad_token_is_rejected():
    resp = client.get("/api/v1/connections", headers={"Authorization": "Bearer not-a-token"})
    assert resp.status_code == 401
