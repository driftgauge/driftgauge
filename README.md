# Driftgauge

Driftgauge is an open-source FastAPI prototype for monitoring opted-in writing and flagging meaningful deviations from a personal baseline.

It is designed as a privacy-conscious, user-configured early-warning tool for reflection and self-checks, not diagnosis.

## What it does
- Ingests opted-in text entries with timestamps and source labels
- Stores entries locally in SQLite by default
- Computes simple baseline and anomaly features
- Scores recent entries and produces plain-language alerts
- Supports user-configured source ingestion
- Supports opt-in email delivery when runtime credentials are provided

## What it does not do
- Diagnose mania, psychosis, or any mental health condition
- Replace clinical care, crisis response, or emergency services
- Contact third parties automatically
- Ship with preloaded private monitoring targets

## Stack
- Python 3.11+
- FastAPI
- SQLite
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
DRIFTGAUGE_DB_PATH=driftgauge.db
RESEND_API_KEY=
DRIFTGAUGE_EMAIL_FROM="Driftgauge <alerts@example.com>"
DRIFTGAUGE_USER_AGENT="DriftgaugeBot/0.1 (+https://driftgauge.com)"
```

Notes:
- If an older `sentinel.db` already exists, Driftgauge will reuse it automatically unless `DRIFTGAUGE_DB_PATH` is set.
- Passwords are hashed before storage. Older legacy SHA-256 hashes are upgraded on successful login.

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
- `GET/POST /alerts/settings/{user_id}`

Most data endpoints require the `X-Auth-Token` header from login or registration.

## Background behavior
- The app runs an internal background ingestion loop every 30 minutes in normal long-running deployments.
- It only ingests sources you explicitly configure.
- Email delivery is opt-in and requires runtime env configuration.
- On Vercel, the background loop is disabled automatically because the app runs as a serverless function.

## Demo data
Sample opted-in files live in:
- `data/imports/demo-user`

These files are synthetic examples intended for local demos and tests.

## Deployment notes
- Docker Compose example: `docker-compose.yml`
- PM2 example: `ecosystem.driftgauge.config.cjs`
- Vercel entrypoint: root `app.py`

### Vercel caveat
This project currently uses SQLite for storage. That is fine for local development and demos, but it is not a production-safe persistence layer on Vercel because the serverless filesystem is ephemeral.

## Open-source notes
- Please do not commit real user writing, live credentials, or private monitoring targets.
- See `CONTRIBUTING.md` for development workflow.
- See `SECURITY.md` for vulnerability reporting guidance.

## Safety framing
Driftgauge is a wellness-oriented baseline-deviation detector. It is not a diagnostic or crisis system.

## License
MIT
