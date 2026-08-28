from fastapi.testclient import TestClient
from ffanalytics.api import app

client = TestClient(app)

def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

def test_refresh_endpoint_accepted():
    resp = client.post("/refresh")
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"