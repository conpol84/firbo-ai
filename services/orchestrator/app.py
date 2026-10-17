from __future__ import annotations

import os
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]] = Field(min_length=1)
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


app = FastAPI(title="FIRBO Orchestrator", version="0.1.0-alpha")


def gateway_url() -> str:
    base = os.getenv("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128").rstrip("/")
    path = os.getenv("OMNIROUTE_CHAT_PATH", "/v1/chat/completions")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "firbo-orchestrator"}


@app.post("/v1/firbo/chat")
async def chat(body: ChatRequest) -> dict[str, Any]:
    request_id = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "model": body.model or os.getenv("FIRBO_DEFAULT_MODEL", "auto"),
        "messages": body.messages,
    }
    if body.temperature is not None:
        payload["temperature"] = body.temperature
    if body.max_tokens is not None:
        payload["max_tokens"] = body.max_tokens

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
    if isinstance(data, dict):
        data.setdefault("firbo_request_id", request_id)
    return data
