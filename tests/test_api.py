from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import ensure_auth_tables
from app.main import app
from app.storage import init_db


client = TestClient(app)


def _auth_headers(username: str = "api_tester", password: str = "password123") -> dict:
    reg = client.post('/auth/register', json={'username': username, 'password': password})
    if reg.status_code == 200:
        token = reg.json()['token']
    else:
        login = client.post('/auth/login', json={'username': username, 'password': password})
        token = login.json()['token']
    return {'X-Auth-Token': token}


def setup_module() -> None:
    init_db()
    ensure_auth_tables()


def test_health() -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_entry_ingest_and_analysis_flow() -> None:
    headers = _auth_headers()
    payloads = [
        {"user_id": "api-user", "source": "journal", "text": "Calm day. Had lunch and wrapped up work.", "created_at": "2026-03-12T20:00:00Z"},
        {"user_id": "api-user", "source": "journal", "text": "Quiet evening. Reading and sleeping early.", "created_at": "2026-03-13T20:00:00Z"},
        {"user_id": "api-user", "source": "journal", "text": "Regular day, no unusual stress.", "created_at": "2026-03-14T20:00:00Z"},
        {"user_id": "api-user", "source": "drafts", "text": "I feel unstoppable and need to post this immediately tonight!!!", "created_at": "2026-03-17T01:00:00Z"},
        {"user_id": "api-user", "source": "drafts", "text": "People may be watching this and I cannot stop writing right now.", "created_at": "2026-03-17T02:00:00Z"},
    ]
    for payload in payloads:
        res = client.post("/entries", headers=headers, json=payload)
        assert res.status_code == 200

    analyze = client.post("/analyze/latest", headers=headers, json={"user_id": "api-user", "window_size": 3})
    assert analyze.status_code == 200
    body = analyze.json()
    assert body["user_id"] == "api-user"
    assert body["risk_score"] >= 20
    assert "recommendations" in body


def test_import_files_disabled_in_serverless_deployments(monkeypatch) -> None:
    monkeypatch.setenv("VERCEL", "1")
    init_db()
    ensure_auth_tables()
    headers = _auth_headers(username="api_import_disabled")
    res = client.post(
        "/import/files",
        headers=headers,
        json={"user_id": "api-user", "directory": "data/imports/demo-user", "source": "import"},
    )
    assert res.status_code == 403
    assert "disabled" in res.json()["detail"].lower()


def test_cron_endpoint_requires_secret_and_runs(monkeypatch) -> None:
    monkeypatch.setenv("CRON_SECRET", "test-secret")

    denied = client.get("/cron/run")
    assert denied.status_code == 401

    allowed = client.get("/cron/run", headers={"Authorization": "Bearer test-secret"})
    assert allowed.status_code == 200
    body = allowed.json()
    assert "ingestion" in body
    assert "jobs" in body


def test_vercel_defaults_sqlite_to_tmp(monkeypatch) -> None:
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DRIFTGAUGE_DB_PATH", raising=False)
    monkeypatch.delenv("SENTINEL_DB_PATH", raising=False)

    from app import storage

    resolved = storage._resolve_db_path()
    assert resolved == Path("/tmp/driftgauge.db")



def test_single_user_mode_restricts_auth_and_coerces_user_id(monkeypatch) -> None:
    monkeypatch.setenv("DRIFTGAUGE_SINGLE_USER_ENABLED", "1")
    monkeypatch.setenv("DRIFTGAUGE_SINGLE_USER_DISPLAY_NAME", "Nate Houk")
    monkeypatch.setenv("DRIFTGAUGE_SINGLE_USER_USERNAME", "nate_houk_single")
    monkeypatch.setenv("DRIFTGAUGE_SINGLE_USER_ID", "nate-houk")

    wrong_reg = client.post('/auth/register', json={'username': 'someone_else', 'password': 'password123'})
    assert wrong_reg.status_code == 403

    reg = client.post('/auth/register', json={'username': 'nate_houk_single', 'password': 'password123'})
    if reg.status_code == 200:
        token = reg.json()['token']
    else:
        login = client.post('/auth/login', json={'username': 'nate_houk_single', 'password': 'password123'})
        assert login.status_code == 200
        token = login.json()['token']

    created = client.post(
        '/entries',
        headers={'X-Auth-Token': token},
        json={'user_id': 'not-nate', 'source': 'journal', 'text': 'Single-user entry'},
    )
    assert created.status_code == 200
    assert created.json()['user_id'] == 'nate-houk'

    listed = client.get('/entries?user_id=another-user', headers={'X-Auth-Token': token})
    assert listed.status_code == 200
    assert any(entry['user_id'] == 'nate-houk' for entry in listed.json())



def test_configured_social_sources(monkeypatch) -> None:
    monkeypatch.setenv('DRIFTGAUGE_SINGLE_USER_ENABLED', '1')
    monkeypatch.setenv('DRIFTGAUGE_SINGLE_USER_USERNAME', 'nate_social')
    monkeypatch.setenv('DRIFTGAUGE_SINGLE_USER_ID', 'nate-houk')
    monkeypatch.setenv('DRIFTGAUGE_SOCIAL_INSTAGRAM_URL', 'https://instagram.com/nate')
    monkeypatch.setenv('DRIFTGAUGE_SOCIAL_X_URL', 'https://x.com/nate')

    from app.config import configured_social_sources

    sources = configured_social_sources()
    assert {source['source_key'] for source in sources} == {'social-instagram', 'social-x'}
    assert all(source['user_id'] == 'nate-houk' for source in sources)



def test_dashboard_summary_returns_headline_and_evidence() -> None:
    headers = _auth_headers(username='dashboard_tester')
    payloads = [
        {'user_id': 'dashboard-user', 'source': 'x', 'text': 'Normal day, a couple of posts and then offline.', 'created_at': '2026-03-12T20:00:00Z'},
        {'user_id': 'dashboard-user', 'source': 'threads', 'text': 'Another steady update, nothing unusual here.', 'created_at': '2026-03-13T20:00:00Z'},
        {'user_id': 'dashboard-user', 'source': 'instagram', 'text': 'I need to post this right now because everything is lining up tonight!!!', 'created_at': '2026-03-17T01:00:00Z'},
    ]
    for payload in payloads:
        res = client.post('/entries', headers=headers, json=payload)
        assert res.status_code == 200

    dashboard = client.get('/dashboard/summary?user_id=dashboard-user', headers=headers)
    assert dashboard.status_code == 200
    body = dashboard.json()
    assert body['status'] == 'ready'
    assert body['headline'] in {'STEADY', 'WATCH', 'ELEVATED', 'HIGH CONCERN'}
    assert body['risk_score'] is not None
    assert body['evidence']
    assert body['source_breakdown']



def test_configured_social_sources_from_handles(monkeypatch) -> None:
    monkeypatch.setenv('DRIFTGAUGE_SINGLE_USER_ENABLED', '1')
    monkeypatch.setenv('DRIFTGAUGE_SINGLE_USER_USERNAME', 'nate_social_handles')
    monkeypatch.setenv('DRIFTGAUGE_SINGLE_USER_ID', 'nate-houk')
    monkeypatch.setenv('DRIFTGAUGE_SOCIAL_HANDLES', '@natehouk, @epsilonrecords')

    from app.config import configured_social_sources

    sources = configured_social_sources()
    assert 'social-instagram-natehouk' in {source['source_key'] for source in sources}
    assert 'social-x-epsilonrecords' in {source['source_key'] for source in sources}
    assert len(sources) == 12



def test_public_summary_exposes_only_neutral_metrics() -> None:
    headers = _auth_headers(username='public_summary_tester')
    payloads = [
        {'user_id': 'public-user', 'source': 'x', 'text': 'Normal day, a couple of posts and then offline.', 'created_at': '2026-03-12T20:00:00Z'},
        {'user_id': 'public-user', 'source': 'threads', 'text': 'Another steady update, nothing unusual here.', 'created_at': '2026-03-13T20:00:00Z'},
        {'user_id': 'public-user', 'source': 'instagram', 'text': 'I need to post this right now because everything is lining up tonight!!!', 'created_at': '2026-03-17T01:00:00Z'},
    ]
    for payload in payloads:
        res = client.post('/entries', headers=headers, json=payload)
        assert res.status_code == 200

    public_summary = client.get('/public/summary?user_id=public-user')
    assert public_summary.status_code == 200
    body = public_summary.json()
    assert body['headline'].endswith('MONITORING')
    assert body['stats']
    assert body['gauges']
    assert body['source_breakdown']
    assert body['recent_activity']
    assert 'risk_score' not in body
    assert all('word_count' in item for item in body['recent_activity'])
    assert all('preview' not in item for item in body['recent_activity'])



def test_login_normalizes_invisible_username_chars() -> None:
    password = 'password123'
    reg = client.post('/auth/register', json={'username': 'invisible_user', 'password': password})
    assert reg.status_code == 200

    login = client.post('/auth/login', json={'username': 'invisible_user ⁠', 'password': password})
    assert login.status_code == 200
    assert login.json()['username'] == 'invisible_user'
