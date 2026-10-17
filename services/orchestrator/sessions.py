from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any

from services.orchestrator.tasks import state_db_path


def _connect() -> sqlite3.Connection:
    path = state_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            FOREIGN KEY(session_id) REFERENCES chat_sessions(id)
        )
        """
    )
    return conn


def ensure_session(session_id: str | None = None) -> str:
    sid = session_id or str(uuid.uuid4())
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO chat_sessions(id, created_at, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at
            """,
            (sid, now, now),
        )
    return sid


def append_messages(session_id: str, messages: list[dict[str, Any]]) -> None:
    now = time.time()
    with _connect() as conn:
        for message in messages:
            role = str(message.get("role", "unknown"))
            conn.execute(
                "INSERT INTO chat_messages(session_id, role, content_json, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, json.dumps(message, ensure_ascii=False, sort_keys=True), now),
            )
        conn.execute("UPDATE chat_sessions SET updated_at = ? WHERE id = ?", (now, session_id))


def read_session(session_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        session = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
        if not session:
            return None
        rows = conn.execute(
            "SELECT role, content_json, created_at FROM chat_messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return {
        "id": session_id,
        "created_at": session["created_at"],
        "updated_at": session["updated_at"],
        "messages": [json.loads(row["content_json"]) for row in rows],
    }
