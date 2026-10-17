from __future__ import annotations

import os
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from services.orchestrator.sessions import append_messages, ensure_session, read_session
from services.orchestrator.tasks import (
    cancel_task,
    complete_task,
    create_or_get_task,
    fail_task,
    get_task,
    public_task,
)
from services.orchestrator.verification import verify_gateway_result


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]] = Field(min_length=1)
    session_id: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class TaskRequest(BaseModel):
    goal: str = Field(min_length=3)
    model: str | None = None
    max_tokens: int | None = None


app = FastAPI(title="FIRBO Orchestrator", version="0.1.0-alpha")


def gateway_url() -> str:
    base = os.getenv("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128").rstrip("/")
    path = os.getenv("OMNIROUTE_CHAT_PATH", "/v1/chat/completions")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


async def call_gateway(payload: dict[str, Any], request_id: str) -> dict[str, Any]:
    headers = {"content-type": "application/json", "x-firbo-request-id": request_id}
    key = os.getenv("OMNIROUTE_API_KEY", "").strip()
    if key:
        headers["authorization"] = f"Bearer {key}"

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(gateway_url(), json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"gateway_unreachable:{type(exc).__name__}") from exc

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail={"error": "gateway_rejected_request", "status": response.status_code, "request_id": request_id},
        )

    data = response.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="gateway_invalid_payload")
    data.setdefault("firbo_request_id", request_id)
    return data


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "firbo-orchestrator"}


@app.post("/v1/firbo/chat")
async def chat(body: ChatRequest) -> dict[str, Any]:
    request_id = str(uuid.uuid4())
    session_id = ensure_session(body.session_id)
    append_messages(session_id, body.messages)

    payload: dict[str, Any] = {
        "model": body.model or os.getenv("FIRBO_DEFAULT_MODEL", "auto"),
        "messages": body.messages,
    }
    if body.temperature is not None:
        payload["temperature"] = body.temperature
    if body.max_tokens is not None:
        payload["max_tokens"] = body.max_tokens

    data = await call_gateway(payload, request_id)
    verification = verify_gateway_result("chat", data)
    if verification["assistant_text"]:
        append_messages(
            session_id,
            [{"role": "assistant", "content": verification["assistant_text"]}],
        )
    data["firbo_session_id"] = session_id
    return data


@app.get("/v1/firbo/sessions/{session_id}")
async def session_readback(session_id: str) -> dict[str, Any]:
    session = read_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session_not_found")
    return session


@app.post("/v1/firbo/tasks")
async def run_task(
    body: TaskRequest,
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
) -> dict[str, Any]:
    row, created = create_or_get_task(body.goal, x_idempotency_key)
    if not created:
        return public_task(row)

    task_id = row["id"]
    request_id = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "model": body.model or os.getenv("FIRBO_DEFAULT_MODEL", "auto"),
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are the execution specialist inside FIRBO. "
                    "Complete the user's goal and return a concise, useful report."
                ),
            },
            {"role": "user", "content": body.goal},
        ],
    }
    if body.max_tokens is not None:
        payload["max_tokens"] = body.max_tokens

    try:
        gateway_result = await call_gateway(payload, request_id)
        verification = verify_gateway_result(body.goal, gateway_result)
        if not verification["verified"]:
            return public_task(fail_task(task_id, "verification_failed"))

        result = {
            "request_id": request_id,
            "verification": verification,
            "gateway": gateway_result,
        }
        return public_task(complete_task(task_id, result))
    except HTTPException as exc:
        fail_task(task_id, str(exc.detail))
        raise


@app.get("/v1/firbo/tasks/{task_id}")
async def read_task(task_id: str) -> dict[str, Any]:
    row = get_task(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="task_not_found")
    return public_task(row)


@app.post("/v1/firbo/tasks/{task_id}/cancel")
async def cancel(task_id: str) -> dict[str, Any]:
    row = cancel_task(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="task_not_found")
    return public_task(row)
