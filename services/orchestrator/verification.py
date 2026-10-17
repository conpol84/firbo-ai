from __future__ import annotations

from typing import Any


def extract_assistant_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content.strip() if isinstance(content, str) else ""


def verify_gateway_result(goal: str, payload: dict[str, Any]) -> dict[str, Any]:
    text = extract_assistant_text(payload)
    checks = {
        "goal_present": bool(goal.strip()),
        "assistant_text_present": bool(text),
        "gateway_payload_is_object": isinstance(payload, dict),
    }
    return {
        "verified": all(checks.values()),
        "checks": checks,
        "assistant_text": text,
    }
