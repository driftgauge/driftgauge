from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from .storage import DB_PATH, get_conn


@dataclass
class RetentionSummary:
    deleted_entries: int
    deleted_alerts: int


def ensure_privacy_tables() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id TEXT PRIMARY KEY,
                retention_days INTEGER NOT NULL DEFAULT 30,
                allow_file_imports INTEGER NOT NULL DEFAULT 1
            );
            """
        )


def set_user_settings(user_id: str, retention_days: int, allow_file_imports: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO user_settings (user_id, retention_days, allow_file_imports)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              retention_days = excluded.retention_days,
              allow_file_imports = excluded.allow_file_imports
            """,
            (user_id, retention_days, 1 if allow_file_imports else 0),
        )


def get_user_settings(user_id: str) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id, retention_days, allow_file_imports FROM user_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return {"user_id": user_id, "retention_days": 30, "allow_file_imports": True}
    return {
        "user_id": row["user_id"],
        "retention_days": row["retention_days"],
        "allow_file_imports": bool(row["allow_file_imports"]),
    }


def apply_retention(user_id: str) -> RetentionSummary:
    settings = get_user_settings(user_id)
    retention_days = settings["retention_days"]
    with get_conn() as conn:
        cur1 = conn.execute(
            "DELETE FROM entries WHERE user_id = ? AND datetime(created_at) < datetime('now', ?)",
            (user_id, f"-{retention_days} days"),
        )
        cur2 = conn.execute(
            "DELETE FROM alerts WHERE user_id = ? AND datetime(created_at) < datetime('now', ?)",
            (user_id, f"-{retention_days} days"),
        )
    return RetentionSummary(deleted_entries=cur1.rowcount, deleted_alerts=cur2.rowcount)
