from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


TERMINAL_STATES = {"completed", "failed", "cancelled"}


def state_db_path() -> Path:
    return Path(os.getenv("FIRBO_STATE_DB", ".firbo/state.db"))


def _connect() -> sqlite3.Connection:
    path = state_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            idempotency_key TEXT UNIQUE,
            goal TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            result_json TEXT,
            receipt_sha256 TEXT,
            error TEXT
        )
        """
    )
    return conn


def create_or_get_task(goal: str, idempotency_key: str | None) -> tuple[dict[str, Any], bool]:
    now = time.time()
    with _connect() as conn:
        if idempotency_key:
            row = conn.execute(
                "SELECT * FROM tasks WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if row:
                return dict(row), False

        task_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO tasks (id, idempotency_key, goal, status, created_at, updated_at)
            VALUES (?, ?, ?, 'running', ?, ?)
            """,
            (task_id, idempotency_key, goal, now, now),
        )
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row), True


def get_task(task_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None


def cancel_task(task_id: str) -> dict[str, Any] | None:
    now = time.time()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        current = dict(row)
        if current["status"] not in TERMINAL_STATES:
            conn.execute(
                "UPDATE tasks SET status = 'cancelled', updated_at = ? WHERE id = ?",
                (now, task_id),
            )
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row)


def complete_task(task_id: str, result: dict[str, Any]) -> dict[str, Any]:
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    receipt = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE tasks
            SET status = 'completed', updated_at = ?, result_json = ?, receipt_sha256 = ?, error = NULL
            WHERE id = ? AND status = 'running'
            """,
            (now, canonical, receipt, task_id),
        )
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row)


def fail_task(task_id: str, error: str) -> dict[str, Any]:
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE tasks
            SET status = 'failed', updated_at = ?, error = ?
            WHERE id = ? AND status = 'running'
            """,
            (now, error[:500], task_id),
        )
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row)


def public_task(row: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(row["result_json"]) if row.get("result_json") else None
    return {
        "id": row["id"],
        "goal": row["goal"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "result": result,
        "receipt_sha256": row.get("receipt_sha256"),
        "error": row.get("error"),
    }
