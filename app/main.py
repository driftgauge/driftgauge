from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

import asyncio
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .alerts import ensure_alert_settings_tables, get_alert_settings, send_email_alert, upsert_alert_settings
from .analyzer import analyze_entries
from .auth import create_session, create_user, ensure_auth_tables, require_auth, user_exists, verify_user
from .config import analysis_interval_minutes, background_loop_enabled, configured_social_sources, cron_secret, local_file_imports_enabled, normalize_text, single_user_display_name, single_user_enabled, single_user_id, single_user_username
from .connectors.files import import_from_directory
from .ingestion import background_ingestion_loop, ensure_ingestion_tables, ingest_sources_once, list_sources, upsert_source
from .models import AlertSettingsRequest, AnalysisRequest, Entry, EntryCreate, HealthResponse, ImportRequest, IngestionSourceRequest, LoginRequest, PrivacySettings, RegisterRequest, ScheduleSettings
from .privacy import apply_retention, ensure_privacy_tables, get_user_settings, set_user_settings
from .scheduler import ensure_scheduler_tables, list_jobs, run_due_jobs, upsert_job
from .storage import init_db, insert_alert, insert_entry, list_alerts, list_entries, utc_now

ingestion_stop_event = asyncio.Event()
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "app" / "static"
TEMPLATES_DIR = BASE_DIR / "app" / "templates"
RUN_BACKGROUND_LOOP = background_loop_enabled()

STATE_LABELS = {
    "none": "STEADY",
    "low": "WATCH",
    "moderate": "ELEVATED",
    "high": "HIGH CONCERN",
}

STATE_SUMMARIES = {
    "none": "No strong deviation from Nate's recent baseline.",
    "low": "A few signals are drifting away from baseline.",
    "moderate": "Several signals are elevated and worth a closer look.",
    "high": "Multiple signals are sharply elevated right now.",
}

PUBLIC_SUMMARY_TEXT = "Neutral public activity metrics from connected sources. Private inference stays behind authentication."


def resolve_user_id(requested_user_id: str | None = None) -> str:
    if single_user_enabled():
        return single_user_id()
    if requested_user_id:
        return normalize_text(requested_user_id)
    raise HTTPException(status_code=400, detail="user_id is required")


def build_evidence(feature_summary: dict) -> list[dict[str, str | float | int]]:
    def clamp(value: float, floor: float = 0.0, ceiling: float = 100.0) -> float:
        return max(floor, min(ceiling, value))

    return [
        {
            "key": "posting_volume_ratio",
            "label": "Posting volume vs baseline",
            "display": f"{feature_summary['posting_volume_ratio']:.2f}x",
            "percent": clamp((feature_summary['posting_volume_ratio'] / 2.5) * 100),
        },
        {
            "key": "late_night_ratio",
            "label": "Late-night posting ratio",
            "display": f"{round(feature_summary['late_night_ratio'] * 100)}%",
            "percent": clamp(feature_summary['late_night_ratio'] * 100),
        },
        {
            "key": "average_length_delta",
            "label": "Writing length shift",
            "display": f"{feature_summary['average_length_delta']:+.2f}",
            "percent": clamp(max(feature_summary['average_length_delta'], 0.0) / 1.5 * 100),
        },
        {
            "key": "elevated_language_hits",
            "label": "Elevated language hits",
            "display": str(feature_summary['elevated_language_hits']),
            "percent": clamp(feature_summary['elevated_language_hits'] / 5 * 100),
        },
        {
            "key": "paranoia_language_hits",
            "label": "Paranoia language hits",
            "display": str(feature_summary['paranoia_language_hits']),
            "percent": clamp(feature_summary['paranoia_language_hits'] / 5 * 100),
        },
        {
            "key": "urgency_language_hits",
            "label": "Urgency language hits",
            "display": str(feature_summary['urgency_language_hits']),
            "percent": clamp(feature_summary['urgency_language_hits'] / 5 * 100),
        },
        {
            "key": "punctuation_intensity_delta",
            "label": "Punctuation intensity shift",
            "display": f"{feature_summary['punctuation_intensity_delta']:+.4f}",
            "percent": clamp(max(feature_summary['punctuation_intensity_delta'], 0.0) / 0.03 * 100),
        },
        {
            "key": "coherence_signal",
            "label": "Coherence pressure",
            "display": f"{round((1 - feature_summary['coherence_signal']) * 100)}%",
            "percent": clamp((1 - feature_summary['coherence_signal']) * 100),
        },
    ]


def build_dashboard_summary(user_id: str) -> dict:
    entries = list_entries(user_id=user_id, limit=40)
    subject_name = single_user_display_name() if single_user_enabled() else user_id

    if len(entries) < 3:
        return {
            "status": "insufficient_data",
            "subject_name": subject_name,
            "headline": "NOT ENOUGH DATA",
            "summary": "Need at least 3 entries before Driftgauge can score a current state.",
            "risk_score": None,
            "level": None,
            "explanation": "Add more entries or let ingestion pull in more public posts first.",
            "evidence": [],
            "source_breakdown": [],
            "recent_entries": [],
            "recommendations": [],
        }

    ordered_entries = sorted(entries, key=lambda item: item.created_at)
    alert = analyze_entries(ordered_entries, window_size=min(10, len(ordered_entries)))
    feature_summary = alert.feature_summary.model_dump()
    source_counts = Counter(entry.source for entry in entries[:20])

    return {
        "status": "ready",
        "subject_name": subject_name,
        "headline": STATE_LABELS[alert.level],
        "summary": STATE_SUMMARIES[alert.level],
        "risk_score": alert.risk_score,
        "level": alert.level,
        "explanation": alert.explanation,
        "evidence": build_evidence(feature_summary),
        "feature_summary": feature_summary,
        "source_breakdown": [
            {"label": source, "count": count} for source, count in source_counts.most_common(6)
        ],
        "recent_entries": [
            {
                "source": entry.source,
                "created_at": entry.created_at.isoformat(),
                "preview": entry.text[:180],
            }
            for entry in entries[:5]
        ],
        "recommendations": alert.recommendations,
    }


def build_public_summary(user_id: str) -> dict:
    entries = list_entries(user_id=user_id, limit=200)
    sources = list_sources(user_id=user_id)
    enabled_sources = [source for source in sources if source["enabled"]]
    subject_name = single_user_display_name() if single_user_enabled() else user_id
    now = utc_now()

    recent_24h = [entry for entry in entries if now - entry.created_at.astimezone(timezone.utc) <= timedelta(hours=24)]
    recent_7d = [entry for entry in entries if now - entry.created_at.astimezone(timezone.utc) <= timedelta(days=7)]
    late_night_ratio = 0.0
    if recent_7d:
        late_night_ratio = sum(1 for entry in recent_7d if entry.created_at.hour < 5 or entry.created_at.hour >= 23) / len(recent_7d)

    average_daily_recent = len(recent_7d) / 7 if recent_7d else 0.0
    activity_tempo = len(recent_24h) / max(average_daily_recent, 1.0) if entries else 0.0

    checked_times: list[datetime] = []
    healthy_sources = 0
    for source in enabled_sources:
        last_status = source.get("last_status") or ""
        if str(last_status).startswith("ok"):
            healthy_sources += 1
        last_checked_at = source.get("last_checked_at")
        if not last_checked_at:
            continue
        parsed = datetime.fromisoformat(last_checked_at)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        checked_times.append(parsed.astimezone(timezone.utc))

    latest_check_at = max(checked_times) if checked_times else None
    freshness_minutes = int((now - latest_check_at).total_seconds() // 60) if latest_check_at else None
    active_source_labels = {entry.source for entry in recent_7d}
    source_coverage_ratio = len(active_source_labels) / max(len(enabled_sources), 1) if enabled_sources else 0.0
    source_counts = Counter(entry.source for entry in entries[:40])

    freshness_percent = 0.0
    if freshness_minutes is not None:
        freshness_percent = max(0.0, min(100.0, 100.0 - (freshness_minutes / 180.0) * 100.0))

    return {
        "status": "ready" if entries or enabled_sources else "empty",
        "subject_name": subject_name,
        "headline": f"{subject_name.upper()} MONITORING",
        "summary": PUBLIC_SUMMARY_TEXT,
        "stats": [
            {"label": "Entries captured", "value": len(entries), "detail": "latest collected items"},
            {"label": "Posts in 24h", "value": len(recent_24h), "detail": "activity volume over the last day"},
            {"label": "Enabled sources", "value": len(enabled_sources), "detail": f"{healthy_sources} reporting healthy checks"},
            {"label": "Last source check", "value": (f"{freshness_minutes}m ago" if freshness_minutes is not None else "waiting"), "detail": "freshness of ingestion status"},
        ],
        "gauges": [
            {"label": "Activity tempo", "display": f"{activity_tempo:.2f}x", "percent": max(0.0, min(100.0, (activity_tempo / 2.5) * 100.0))},
            {"label": "Late-night share", "display": f"{round(late_night_ratio * 100)}%", "percent": max(0.0, min(100.0, late_night_ratio * 100.0))},
            {"label": "Source coverage", "display": f"{len(active_source_labels)}/{len(enabled_sources) or 0}", "percent": max(0.0, min(100.0, source_coverage_ratio * 100.0))},
            {"label": "Ingestion freshness", "display": (f"{freshness_minutes}m" if freshness_minutes is not None else "n/a"), "percent": freshness_percent},
        ],
        "source_breakdown": [
            {"label": source, "count": count} for source, count in source_counts.most_common(6)
        ],
        "recent_activity": [
            {
                "source": entry.source,
                "created_at": entry.created_at.isoformat(),
                "word_count": len(entry.text.split()),
            }
            for entry in entries[:6]
        ],
    }


def ensure_single_user_defaults() -> None:
    if not single_user_enabled():
        return

    configured_user_id = single_user_id()
    existing_job_ids = {job["user_id"] for job in list_jobs()}
    if configured_user_id not in existing_job_ids:
        upsert_job(configured_user_id, True, analysis_interval_minutes())

    for source in configured_social_sources():
        upsert_source(
            source["user_id"],
            source["source_key"],
            source["label"],
            source["url"],
            source["kind"],
            bool(source["enabled"]),
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    ensure_privacy_tables()
    ensure_auth_tables()
    ensure_scheduler_tables()
    ensure_ingestion_tables()
    ensure_alert_settings_tables()
    ensure_single_user_defaults()

    task: asyncio.Task | None = None
    if RUN_BACKGROUND_LOOP:
        ingestion_stop_event.clear()
        task = asyncio.create_task(background_ingestion_loop(ingestion_stop_event, single_user_id() if single_user_enabled() else None))

    try:
        yield
    finally:
        if task is not None:
            ingestion_stop_event.set()
            await task


app = FastAPI(title="Driftgauge", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "default_schedule_interval": analysis_interval_minutes(),
            "default_user_id": single_user_id() if single_user_enabled() else "demo-user",
            "default_username": single_user_username() if single_user_enabled() else "demo",
            "local_file_imports_enabled": local_file_imports_enabled(),
            "single_user_display_name": single_user_display_name(),
            "single_user_enabled": single_user_enabled(),
            "single_user_registered": single_user_enabled() and bool(single_user_username()) and user_exists(single_user_username()),
        },
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/public/summary")
def public_summary(user_id: str | None = None):
    return build_public_summary(resolve_user_id(user_id))


@app.get("/dashboard/summary")
def dashboard_summary(user_id: str | None = None, _: str = Depends(require_auth)):
    return build_dashboard_summary(resolve_user_id(user_id))


@app.post("/auth/register")
def register(payload: RegisterRequest):
    username = normalize_text(payload.username)
    configured_username = single_user_username()
    if single_user_enabled() and configured_username and username != configured_username:
        raise HTTPException(status_code=403, detail="Registration is locked to the configured single user")

    try:
        user = create_user(username, payload.password)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Username already exists") from exc
    token = create_session(username)
    return {"user": user, "token": token}


@app.post("/auth/login")
def login(payload: LoginRequest):
    username = normalize_text(payload.username)
    configured_username = single_user_username()
    if single_user_enabled() and configured_username and username != configured_username:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_user(username, payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_session(username)
    return {"username": username, "token": token}


@app.post("/entries", response_model=Entry)
def create_entry(payload: EntryCreate, _: str = Depends(require_auth)) -> Entry:
    created_at = payload.created_at or utc_now()
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return insert_entry(
        user_id=resolve_user_id(payload.user_id),
        source=payload.source,
        text=payload.text,
        created_at=created_at,
    )


@app.get("/entries", response_model=list[Entry])
def get_entries(user_id: str | None = None, limit: int = Query(50, ge=1, le=500), _: str = Depends(require_auth)) -> list[Entry]:
    return list_entries(user_id=resolve_user_id(user_id) if single_user_enabled() else user_id, limit=limit)


@app.post("/analyze/latest")
async def analyze_latest(payload: AnalysisRequest, _: str = Depends(require_auth)):
    user_id = resolve_user_id(payload.user_id)
    entries = list_entries(user_id=user_id, limit=max(payload.window_size * 4, 20))
    if len(entries) < 3:
        raise HTTPException(status_code=400, detail="Need at least 3 entries for analysis")
    alert = analyze_entries(entries=entries, window_size=payload.window_size)
    alert.user_id = user_id
    saved = insert_alert(alert)
    delivery = await send_email_alert(saved)
    return {**saved.model_dump(), "delivery": delivery}


@app.get("/alerts")
def get_alerts(user_id: str | None = None, limit: int = Query(50, ge=1, le=500), _: str = Depends(require_auth)):
    effective_user_id = resolve_user_id(user_id) if single_user_enabled() else user_id
    return [alert.model_dump() for alert in list_alerts(user_id=effective_user_id, limit=limit)]


@app.post("/import/files")
def import_files(payload: ImportRequest, _: str = Depends(require_auth)):
    user_id = resolve_user_id(payload.user_id)
    if not local_file_imports_enabled():
        raise HTTPException(status_code=403, detail="Local file imports are disabled in this deployment")

    settings = get_user_settings(user_id)
    if not settings["allow_file_imports"]:
        raise HTTPException(status_code=403, detail="File imports are disabled for this user")

    imported = import_from_directory(payload.directory, user_id=user_id, source=payload.source)
    saved = []
    for item in imported:
        entry = insert_entry(
            user_id=item.entry.user_id,
            source=item.entry.source,
            text=item.entry.text,
            created_at=item.entry.created_at or utc_now(),
        )
        saved.append({"id": entry.id, "source_path": item.source_path})
    return {"imported_count": len(saved), "items": saved}


@app.get("/privacy/{user_id}")
def get_privacy(user_id: str, _: str = Depends(require_auth)):
    return get_user_settings(resolve_user_id(user_id))


@app.post("/privacy/{user_id}")
def update_privacy(user_id: str, payload: PrivacySettings, _: str = Depends(require_auth)):
    effective_user_id = resolve_user_id(user_id)
    if not single_user_enabled() and payload.user_id != user_id:
        raise HTTPException(status_code=400, detail="user_id mismatch")
    set_user_settings(user_id=effective_user_id, retention_days=payload.retention_days, allow_file_imports=payload.allow_file_imports)
    return get_user_settings(effective_user_id)


@app.post("/privacy/{user_id}/apply-retention")
def run_retention(user_id: str, _: str = Depends(require_auth)):
    result = apply_retention(resolve_user_id(user_id))
    return {"deleted_entries": result.deleted_entries, "deleted_alerts": result.deleted_alerts}


@app.get("/schedule/jobs")
def get_schedule_jobs(_: str = Depends(require_auth)):
    jobs = list_jobs()
    if single_user_enabled():
        jobs = [job for job in jobs if job["user_id"] == single_user_id()]
    return jobs


@app.post("/schedule/jobs")
def set_schedule_job(payload: ScheduleSettings, _: str = Depends(require_auth)):
    return upsert_job(resolve_user_id(payload.user_id), payload.enabled, payload.interval_minutes)


@app.post("/schedule/run")
def run_schedule_now(_: str = Depends(require_auth)):
    result = run_due_jobs()
    return {"analyzed_users": result.analyzed_users, "created_alerts": result.created_alerts}


@app.get("/ingestion/sources")
def get_ingestion_sources(user_id: str | None = None, _: str = Depends(require_auth)):
    return list_sources(user_id=resolve_user_id(user_id) if single_user_enabled() else user_id)


@app.post("/ingestion/sources")
def create_ingestion_source(payload: IngestionSourceRequest, _: str = Depends(require_auth)):
    return upsert_source(resolve_user_id(payload.user_id), payload.source_key, payload.label, payload.url, payload.kind, payload.enabled)


@app.post("/ingestion/run")
async def run_ingestion_now(_: str = Depends(require_auth)):
    result = await ingest_sources_once(user_id=single_user_id() if single_user_enabled() else None)
    return {"fetched_sources": result.fetched_sources, "fetched_pages": result.fetched_pages, "imported_entries": result.imported_entries, "errors": result.errors}


@app.post("/ingestion/backfill")
async def run_ingestion_backfill(max_pages: int = Query(25, ge=1, le=100), max_items: int = Query(250, ge=1, le=2000), _: str = Depends(require_auth)):
    result = await ingest_sources_once(user_id=single_user_id() if single_user_enabled() else None, historical_backfill=True, max_pages_per_source=max_pages, max_items_per_source=max_items)
    return {"fetched_sources": result.fetched_sources, "fetched_pages": result.fetched_pages, "imported_entries": result.imported_entries, "errors": result.errors}


def require_cron_auth(authorization: str | None = Header(default=None, alias="Authorization")) -> None:
    expected = cron_secret()
    if not expected:
        raise HTTPException(status_code=503, detail="Cron secret is not configured")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    provided = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid cron token")


@app.get("/cron/run")
def run_cron(_: None = Depends(require_cron_auth)):
    ingestion = asyncio.run(ingest_sources_once(respect_min_interval=True))
    scheduled = run_due_jobs()
    return {
        "ingestion": {
            "fetched_sources": ingestion.fetched_sources,
            "imported_entries": ingestion.imported_entries,
            "errors": ingestion.errors,
        },
        "jobs": {
            "analyzed_users": scheduled.analyzed_users,
            "created_alerts": scheduled.created_alerts,
        },
    }


@app.get("/alerts/settings/{user_id}")
def get_private_alert_settings(user_id: str, _: str = Depends(require_auth)):
    return get_alert_settings(resolve_user_id(user_id))


@app.post("/alerts/settings/{user_id}")
def set_private_alert_settings(user_id: str, payload: AlertSettingsRequest, _: str = Depends(require_auth)):
    effective_user_id = resolve_user_id(user_id)
    if not single_user_enabled() and payload.user_id != user_id:
        raise HTTPException(status_code=400, detail="user_id mismatch")
    return upsert_alert_settings(effective_user_id, payload.email_enabled, payload.email_to)
