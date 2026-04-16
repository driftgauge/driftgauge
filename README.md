# Driftgauge

Driftgauge is an open-source FastAPI prototype for monitoring opted-in writing and flagging meaningful deviations from a personal baseline.

It is designed as a privacy-conscious, user-configured early-warning tool for reflection and self-checks, not diagnosis.

## What it does
- Ingests opted-in text entries with timestamps and source labels
- Stores entries locally in SQLite by default, or in Postgres for production deployments
- Computes simple baseline and anomaly features
- Scores recent entries and produces plain-language alerts
- Supports user-configured source ingestion
- Supports a configurable single-user mode with automatic social source seeding
- Supports opt-in email delivery when runtime credentials are provided
- Supports scheduled analysis in long-running environments or through a cron endpoint on Vercel

## What it does not do
- Diagnose mania, psychosis, or any mental health condition
- Replace clinical care, crisis response, or emergency services
- Contact third parties automatically
- Ship with preloaded private monitoring targets

## Stack
- Python 3.11+
- FastAPI
- SQLite for local development
- Postgres for production deployments
- Pydantic

## Quick start
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open:
- `http://127.0.0.1:8000/` for the demo dashboard
- `http://127.0.0.1:8000/docs` for the API docs

## Environment
Copy `.env.example` or set these directly in your runtime:

```bash
# Local development
DRIFTGAUGE_DB_PATH=driftgauge.db

# Production or shared deployments
DATABASE_URL=
CRON_SECRET=
RESEND_API_KEY=
DRIFTGAUGE_EMAIL_FROM="Driftgauge <alerts@example.com>"
DRIFTGAUGE_USER_AGENT="DriftgaugeBot/0.1 (+https://driftgauge.com)"
DRIFTGAUGE_SINGLE_USER_ENABLED=0
DRIFTGAUGE_SINGLE_USER_DISPLAY_NAME=
DRIFTGAUGE_SINGLE_USER_USERNAME=
DRIFTGAUGE_SINGLE_USER_ID=
DRIFTGAUGE_INGEST_INTERVAL_MINUTES=5
DRIFTGAUGE_ANALYSIS_INTERVAL_MINUTES=5
DRIFTGAUGE_SOCIAL_HANDLES=
DRIFTGAUGE_SOCIAL_INSTAGRAM_URL=
DRIFTGAUGE_SOCIAL_FACEBOOK_URL=
DRIFTGAUGE_SOCIAL_X_URL=
DRIFTGAUGE_SOCIAL_THREADS_URL=
DRIFTGAUGE_SOCIAL_TIKTOK_URL=
DRIFTGAUGE_SOCIAL_SNAPCHAT_URL=
```

Notes:
- If an older `sentinel.db` already exists, Driftgauge will reuse it automatically unless `DRIFTGAUGE_DB_PATH` is set.
- Passwords are hashed before storage. Older legacy SHA-256 hashes are upgraded on successful login.
- Local file imports are disabled automatically on Vercel unless you explicitly override `DRIFTGAUGE_ENABLE_LOCAL_FILE_IMPORTS=1`.

## Main endpoints
- `GET /health`
- `POST /auth/register`
- `POST /auth/login`
- `POST /entries`
- `GET /entries`
- `POST /analyze/latest`
- `GET /alerts`
- `POST /import/files`
- `GET/POST /privacy/{user_id}`
- `POST /privacy/{user_id}/apply-retention`
- `GET/POST /schedule/jobs`
- `POST /schedule/run`
- `GET/POST /ingestion/sources`
- `POST /ingestion/run`
- `GET /cron/run`
- `GET/POST /alerts/settings/{user_id}`

Most data endpoints require the `X-Auth-Token` header from login or registration.
The cron endpoint requires `Authorization: Bearer <CRON_SECRET>`.

## Production on Vercel
Driftgauge is production-ready on Vercel when you pair it with a persistent Postgres database and a cron secret.

### Required Vercel environment variables
- `DATABASE_URL` - a Postgres connection string
- `CRON_SECRET` - Vercel uses this to protect `/cron/run`

### Optional Vercel environment variables
- `RESEND_API_KEY`
- `DRIFTGAUGE_EMAIL_FROM`
- `DRIFTGAUGE_USER_AGENT`
- `DRIFTGAUGE_SINGLE_USER_ENABLED=1`
- `DRIFTGAUGE_SINGLE_USER_DISPLAY_NAME`, `DRIFTGAUGE_SINGLE_USER_USERNAME`, `DRIFTGAUGE_SINGLE_USER_ID`
- `DRIFTGAUGE_SOCIAL_HANDLES` for automatic profile URL generation across supported platforms
- `DRIFTGAUGE_SOCIAL_INSTAGRAM_URL`, `DRIFTGAUGE_SOCIAL_FACEBOOK_URL`, `DRIFTGAUGE_SOCIAL_X_URL`, `DRIFTGAUGE_SOCIAL_THREADS_URL`, `DRIFTGAUGE_SOCIAL_TIKTOK_URL`, `DRIFTGAUGE_SOCIAL_SNAPCHAT_URL`

### Vercel behavior
- Root entrypoint: `index.py`
- `vercel.json` schedules `/cron/run` every 5 minutes
- `/cron/run` performs due source ingestion and due scheduled analysis jobs
- Source ingestion defaults to a 5 minute minimum interval, configurable with `DRIFTGAUGE_INGEST_INTERVAL_MINUTES`
- Local file imports are disabled by default in Vercel deployments
- The background ingestion loop is disabled automatically on Vercel because the app runs as a serverless function

### Single-user deployments
- Enable `DRIFTGAUGE_SINGLE_USER_ENABLED=1` to lock the app to one account
- Registration is limited to the configured username, and all entry, privacy, alert, schedule, and ingestion routes are pinned to the configured `DRIFTGAUGE_SINGLE_USER_ID`
- When `DRIFTGAUGE_SOCIAL_HANDLES` or explicit social URLs are configured, Driftgauge auto-seeds those sources on startup and keeps them on the 5 minute cron cadence
- For platforms that block unauthenticated scraping, use an authorized public profile URL, feed URL, or approved bridge endpoint that returns the account's own posts

### Important production note
Do not use SQLite for production Vercel deployments. The serverless filesystem is ephemeral, so persistent data belongs in Postgres via `DATABASE_URL`.

## Demo data
Sample opted-in files live in:
- `data/imports/demo-user`

These files are synthetic examples intended for local demos and tests.

## Deployment notes
- Docker Compose example: `docker-compose.yml`
- PM2 example: `ecosystem.driftgauge.config.cjs`
- Vercel entrypoint: root `index.py`
- Vercel cron config: `vercel.json`

## Open-source notes
- Please do not commit real user writing, live credentials, or private monitoring targets.
- See `CONTRIBUTING.md` for development workflow.
- See `SECURITY.md` for vulnerability reporting guidance.

## Safety framing
Driftgauge is a wellness-oriented baseline-deviation detector. It is not a diagnostic or crisis system.

## License
MIT
