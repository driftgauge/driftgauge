from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .models import Alert, Entry, FeatureSummary


def _resolve_db_path() -> Path:
    root = Path(__file__).resolve().parent.parent
    env_path = os.getenv("DRIFTGAUGE_DB_PATH") or os.getenv("SENTINEL_DB_PATH")
    if env_path:
        return Path(env_path).expanduser()

    default_path = root / "driftgauge.db"
    legacy_path = root / "sentinel.db"
    if legacy_path.exists() and not default_path.exists():
        return legacy_path
    return default_path


DB_PATH = _resolve_db_path()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                source TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                risk_score INTEGER NOT NULL,
                level TEXT NOT NULL,
                explanation TEXT NOT NULL,
                recommendations TEXT NOT NULL,
                feature_summary TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


def insert_entry(user_id: str, source: str, text: str, created_at: datetime) -> Entry:
    created_at = created_at.astimezone(timezone.utc)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO entries (user_id, source, text, created_at) VALUES (?, ?, ?, ?)",
            (user_id, source, text, created_at.isoformat()),
        )
        entry_id = cur.lastrowid
    return Entry(id=entry_id, user_id=user_id, source=source, text=text, created_at=created_at)


def list_entries(user_id: str | None = None, limit: int = 50) -> list[Entry]:
    query = "SELECT id, user_id, source, text, created_at FROM entries"
    params: list[object] = []
    if user_id:
        query += " WHERE user_id = ?"
        params.append(user_id)
    query += " ORDER BY datetime(created_at) DESC LIMIT ?"
    params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()

    return [
        Entry(
            id=row["id"],
            user_id=row["user_id"],
            source=row["source"],
            text=row["text"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
        for row in rows
    ]


def insert_alert(alert: Alert) -> Alert:
    created_at = alert.created_at or utc_now()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO alerts (user_id, risk_score, level, explanation, recommendations, feature_summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert.user_id,
                alert.risk_score,
                alert.level,
                alert.explanation,
                json.dumps(alert.recommendations),
                alert.feature_summary.model_dump_json(),
                created_at.isoformat(),
            ),
        )
        alert_id = cur.lastrowid
    return alert.model_copy(update={"id": alert_id, "created_at": created_at})


def list_alerts(user_id: str | None = None, limit: int = 50) -> list[Alert]:
    query = "SELECT * FROM alerts"
    params: list[object] = []
    if user_id:
        query += " WHERE user_id = ?"
        params.append(user_id)
    query += " ORDER BY datetime(created_at) DESC LIMIT ?"
    params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()

    alerts: list[Alert] = []
    for row in rows:
        alerts.append(
            Alert(
                id=row["id"],
                user_id=row["user_id"],
                risk_score=row["risk_score"],
                level=row["level"],
                explanation=row["explanation"],
                recommendations=json.loads(row["recommendations"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                feature_summary=FeatureSummary.model_validate_json(row["feature_summary"]),
            )
        )
    return alerts
