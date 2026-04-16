# Contributing to Driftgauge

Thanks for helping.

## Local setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Tests
```bash
pytest -q
```

## Contribution guidelines
- Keep the project privacy-conscious by default.
- Do not commit real user writing, private monitoring targets, or live credentials.
- Prefer synthetic fixtures and demo data in tests.
- Keep safety language clear: Driftgauge is not a diagnostic or crisis system.
- For user-facing behavior changes, update `README.md` when needed.

## Pull requests
Small focused PRs are easiest to review. Include:
- what changed
- why it changed
- any follow-up work or tradeoffs
