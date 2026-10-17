import os

from fastapi.testclient import TestClient

from services.orchestrator.app import app, gateway_url


def test_health():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "firbo-orchestrator"}


def test_gateway_url_is_configurable(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_BASE_URL", "http://gateway:20128/")
    monkeypatch.setenv("OMNIROUTE_CHAT_PATH", "v1/chat/completions")
    assert gateway_url() == "http://gateway:20128/v1/chat/completions"
