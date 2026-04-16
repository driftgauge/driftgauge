from __future__ import annotations

from datetime import timezone

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
from .config import analysis_interval_minutes, background_loop_enabled, configured_social_sources, cron_secret, local_file_imports_enabled, single_user_display_name, single_user_enabled, single_user_id, single_user_username
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


def resolve_user_id(requested_user_id: str | None = None) -> str:
    if single_user_enabled():
        return single_user_id()
    if requested_user_id:
        return requested_user_id
    raise HTTPException(status_code=400, detail="user_id is required")


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
        task = asyncio.create_task(background_ingestion_loop(ingestion_stop_event))

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


@app.post("/auth/register")
def register(payload: RegisterRequest):
    configured_username = single_user_username()
    if single_user_enabled() and configured_username and payload.username != configured_username:
        raise HTTPException(status_code=403, detail="Registration is locked to the configured single user")

    try:
        user = create_user(payload.username, payload.password)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Username already exists") from exc
    token = create_session(payload.username)
    return {"user": user, "token": token}


@app.post("/auth/login")
def login(payload: LoginRequest):
    configured_username = single_user_username()
    if single_user_enabled() and configured_username and payload.username != configured_username:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_user(payload.username, payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_session(payload.username)
    return {"username": payload.username, "token": token}


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
    result = await ingest_sources_once()
    return {"fetched_sources": result.fetched_sources, "imported_entries": result.imported_entries, "errors": result.errors}


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
