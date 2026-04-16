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
