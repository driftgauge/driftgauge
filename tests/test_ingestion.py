from fastapi.testclient import TestClient

from app.auth import ensure_auth_tables
from app.ingestion import ensure_ingestion_tables, upsert_source
from app.main import app
from app.storage import init_db

client = TestClient(app)


def _auth_headers(username: str = "ingest_tester", password: str = "password123") -> dict:
    reg = client.post('/auth/register', json={'username': username, 'password': password})
    if reg.status_code == 200:
        token = reg.json()['token']
    else:
        token = client.post('/auth/login', json={'username': username, 'password': password}).json()['token']
    return {'X-Auth-Token': token}


def setup_module() -> None:
    init_db()
    ensure_auth_tables()
    ensure_ingestion_tables()


def test_sources_endpoint_lists_configured_sources() -> None:
    headers = _auth_headers()
    upsert_source('demo-user', 'test-source', 'Test Source', 'https://example.com', 'site', True)
    res = client.get('/ingestion/sources?user_id=demo-user', headers=headers)
    assert res.status_code == 200
    assert isinstance(res.json(), list)
    assert any(item['source_key'] == 'test-source' for item in res.json())
