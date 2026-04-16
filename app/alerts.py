from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx

from .models import Alert
from .storage import get_conn, id_column_sql

DEFAULT_EMAIL = ""
DEFAULT_FROM = "Driftgauge <alerts@example.com>"


def ensure_alert_settings_tables() -> None:
    with get_conn() as conn:
        conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS alert_settings (
                user_id TEXT PRIMARY KEY,
                email_enabled INTEGER NOT NULL DEFAULT 0,
                email_to TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS alert_deliveries (
                id {id_column_sql()},
                user_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                destination TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL
            );
            """
        )


def upsert_alert_settings(user_id: str, email_enabled: bool, email_to: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO alert_settings (user_id, email_enabled, email_to, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              email_enabled = excluded.email_enabled,
              email_to = excluded.email_to,
              updated_at = excluded.updated_at
            """,
            (user_id, 1 if email_enabled else 0, email_to, now, now),
        )
    return {"user_id": user_id, "email_enabled": email_enabled, "email_to": email_to}


def get_alert_settings(user_id: str) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id, email_enabled, email_to FROM alert_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return {"user_id": user_id, "email_enabled": False, "email_to": DEFAULT_EMAIL}
    return {"user_id": row["user_id"], "email_enabled": bool(row["email_enabled"]), "email_to": row["email_to"] or DEFAULT_EMAIL}


def record_delivery(user_id: str, channel: str, destination: str, status: str, detail: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO alert_deliveries (user_id, channel, destination, status, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, channel, destination, status, detail, datetime.now(timezone.utc).isoformat()),
        )


def _build_email_html(alert: Alert) -> str:
    recs = "".join(f"<li>{item}</li>" for item in alert.recommendations)
    return f"""
    <h2>Driftgauge private alert</h2>
    <p>A supportive baseline-deviation alert was generated for <strong>{alert.user_id}</strong>.</p>
    <p><strong>Level:</strong> {alert.level}<br>
    <strong>Risk score:</strong> {alert.risk_score}</p>
    <p>{alert.explanation}</p>
    <h3>Recommended self-check steps</h3>
    <ul>{recs}</ul>
    <p>This is a private, supportive notice from Driftgauge. It is not a diagnosis.</p>
    """


async def send_email_alert(alert: Alert) -> dict[str, Any]:
    settings = get_alert_settings(alert.user_id)
    if not settings["email_enabled"]:
        return {"sent": False, "reason": "email disabled"}

    email_to = (settings["email_to"] or "").strip()
    if not email_to:
        record_delivery(alert.user_id, "email", "", "skipped", "missing email destination")
        return {"sent": False, "reason": "missing email destination"}

    api_key = os.getenv("RESEND_API_KEY", "")
    if not api_key:
        record_delivery(alert.user_id, "email", email_to, "skipped", "missing RESEND_API_KEY")
        return {"sent": False, "reason": "missing api key"}

    payload = {
        "from": os.getenv("DRIFTGAUGE_EMAIL_FROM") or DEFAULT_FROM,
        "to": [email_to],
        "subject": f"Driftgauge private alert: {alert.level} ({alert.risk_score})",
        "html": _build_email_html(alert),
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post("https://api.resend.com/emails", json=payload, headers=headers)

    if 200 <= response.status_code < 300:
        record_delivery(alert.user_id, "email", email_to, "sent", response.text[:500])
        return {"sent": True, "destination": email_to}

    record_delivery(alert.user_id, "email", email_to, "error", response.text[:500])
    return {"sent": False, "reason": response.text[:500]}
