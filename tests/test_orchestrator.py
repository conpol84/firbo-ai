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


def test_verified_task_golden_journey(monkeypatch, tmp_path):
    monkeypatch.setenv("FIRBO_STATE_DB", str(tmp_path / "state.db"))

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {"message": {"role": "assistant", "content": "Verified report for the requested goal."}}
                ]
            }

    async def fake_post(self, url, json, headers):
        return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    client = TestClient(app)
    first = client.post(
        "/v1/firbo/tasks",
        headers={"X-Idempotency-Key": "golden-1"},
        json={"goal": "Research the topic and produce a short report."},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["status"] == "completed"
    assert body["result"]["verification"]["verified"] is True
    assert body["receipt_sha256"]
    task_id = body["id"]

    readback = client.get(f"/v1/firbo/tasks/{task_id}")
    assert readback.status_code == 200
    assert readback.json()["receipt_sha256"] == body["receipt_sha256"]

    duplicate = client.post(
        "/v1/firbo/tasks",
        headers={"X-Idempotency-Key": "golden-1"},
        json={"goal": "Research the topic and produce a short report."},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == task_id
    assert duplicate.json()["receipt_sha256"] == body["receipt_sha256"]


def test_cancel_task(monkeypatch, tmp_path):
    monkeypatch.setenv("FIRBO_STATE_DB", str(tmp_path / "state.db"))

    from services.orchestrator.tasks import create_or_get_task

    row, created = create_or_get_task("A cancellable task", "cancel-1")
    assert created is True

    client = TestClient(app)
    response = client.post(f"/v1/firbo/tasks/{row['id']}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_chat_session_persists_and_reads_back(monkeypatch, tmp_path):
    monkeypatch.setenv("FIRBO_STATE_DB", str(tmp_path / "state.db"))

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {"message": {"role": "assistant", "content": "Session reply."}}
                ]
            }

    async def fake_post(self, url, json, headers):
        return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    client = TestClient(app)
    first = client.post(
        "/v1/firbo/chat",
        json={"messages": [{"role": "user", "content": "Remember this goal."}]},
    )
    assert first.status_code == 200
    session_id = first.json()["firbo_session_id"]

    readback = client.get(f"/v1/firbo/sessions/{session_id}")
    assert readback.status_code == 200
    messages = readback.json()["messages"]
    assert messages[0]["content"] == "Remember this goal."
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "Session reply."

    second = client.post(
        "/v1/firbo/chat",
        json={
            "session_id": session_id,
            "messages": [{"role": "user", "content": "Continue the same goal."}],
        },
    )
    assert second.status_code == 200
    assert second.json()["firbo_session_id"] == session_id

    again = client.get(f"/v1/firbo/sessions/{session_id}")
    assert len(again.json()["messages"]) == 4
