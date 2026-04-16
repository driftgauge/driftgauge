from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import asyncio

from .alerts import send_email_alert
from .analyzer import analyze_entries
from .storage import get_conn, insert_alert, list_entries


@dataclass
class ScheduledRunResult:
    analyzed_users: int
    created_alerts: int


DEFAULT_INTERVAL_MINUTES = 60


def ensure_scheduler_tables() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS analysis_jobs (
                user_id TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                interval_minutes INTEGER NOT NULL DEFAULT 60,
                last_run_at TEXT,
                created_at TEXT NOT NULL
            );
            """
        )


def upsert_job(user_id: str, enabled: bool, interval_minutes: int) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO analysis_jobs (user_id, enabled, interval_minutes, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              enabled = excluded.enabled,
              interval_minutes = excluded.interval_minutes
            """,
            (user_id, 1 if enabled else 0, interval_minutes, now),
        )
    return {"user_id": user_id, "enabled": enabled, "interval_minutes": interval_minutes}


def list_jobs() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT user_id, enabled, interval_minutes, last_run_at, created_at FROM analysis_jobs ORDER BY user_id"
        ).fetchall()
    return [
        {
            "user_id": row["user_id"],
            "enabled": bool(row["enabled"]),
            "interval_minutes": row["interval_minutes"],
            "last_run_at": row["last_run_at"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def run_due_jobs() -> ScheduledRunResult:
    now = datetime.now(timezone.utc)
    analyzed = 0
    created = 0
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT user_id, interval_minutes, last_run_at FROM analysis_jobs WHERE enabled = 1"
        ).fetchall()

    for row in rows:
        last_run_at = datetime.fromisoformat(row["last_run_at"]) if row["last_run_at"] else None
        interval = row["interval_minutes"]
        if last_run_at and (now - last_run_at).total_seconds() < interval * 60:
            continue

        entries = list_entries(user_id=row["user_id"], limit=40)
        if len(entries) >= 3:
            alert = analyze_entries(entries, window_size=min(10, len(entries)))
            if alert.level in {"moderate", "high"}:
                saved = insert_alert(alert)
                try:
                    asyncio.run(send_email_alert(saved))
                except Exception:
                    pass
                created += 1
            analyzed += 1

        with get_conn() as conn:
            conn.execute(
                "UPDATE analysis_jobs SET last_run_at = ? WHERE user_id = ?",
                (now.isoformat(), row["user_id"]),
            )

    return ScheduledRunResult(analyzed_users=analyzed, created_alerts=created)
