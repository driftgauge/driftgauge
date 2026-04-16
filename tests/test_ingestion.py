import asyncio
from uuid import uuid4
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



def test_historical_backfill_follows_same_origin_links(monkeypatch) -> None:
    import app.ingestion as ingestion
    from app.storage import list_entries

    source_key = f'history-source-{uuid4().hex}'
    upsert_source('history-user', source_key, 'History Source', 'https://example.com/profile', 'site', True)

    pages = {
        'https://example.com/profile': ('<html><body><article><h2>Latest</h2><p>This is the latest historical post with enough words to count.</p><a href="/p/1">Open</a></article><a href="/page/2">Older</a></body></html>', 'text/html'),
        'https://example.com/p/1': ('<html><body><article><h2>Latest Permalink</h2><p>This permalink page repeats the latest post with enough words to count properly.</p></article></body></html>', 'text/html'),
        'https://example.com/page/2': ('<html><body><article><h2>Older Post</h2><p>This is an older post with enough words to be imported as well.</p><a href="/p/2">Open</a></article></body></html>', 'text/html'),
        'https://example.com/p/2': ('<html><body><article><h2>Older Permalink</h2><p>This permalink page contains the older post body with enough words to import correctly.</p></article></body></html>', 'text/html'),
    }

    async def fake_fetch(client, url):
        return pages[url]

    monkeypatch.setattr(ingestion, '_fetch_url', fake_fetch)

    result = asyncio.run(ingestion.ingest_sources_once(user_id='history-user', historical_backfill=True, max_pages_per_source=5, max_items_per_source=10))
    assert result.fetched_pages >= 2
    assert result.imported_entries >= 2
    entries = list_entries(user_id='history-user', limit=10)
    assert any('Older Post' in entry.text for entry in entries)



def test_backfill_endpoint_runs(headers=None) -> None:
    headers = _auth_headers(username='backfill_tester')
    res = client.post('/ingestion/backfill?max_pages=2&max_items=5', headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert 'fetched_sources' in body
    assert 'fetched_pages' in body
    assert 'imported_entries' in body



def test_backfill_filters_auth_wall_content(monkeypatch) -> None:
    import app.ingestion as ingestion

    source_key = f'blocked-source-{uuid4().hex}'
    upsert_source('history-user', source_key, 'Blocked Source', 'https://www.facebook.com/example', 'facebook', True)

    async def fake_fetch(client, url):
        return ('<html><body><article><h2>Facebook</h2><p>Create an account to connect with friends, family and communities of people who share your interests. By tapping Submit you agree.</p><a href="/reg/">Open</a></article></body></html>', 'text/html')

    monkeypatch.setattr(ingestion, '_fetch_url', fake_fetch)

    result = asyncio.run(ingestion.ingest_sources_once(user_id='history-user', historical_backfill=True, max_pages_per_source=2, max_items_per_source=5))
    assert result.imported_entries == 0



def test_source_toggle_and_delete_endpoints() -> None:
    headers = _auth_headers(username='source_manager')
    source_key = f'manage-source-{uuid4().hex}'
    upsert_source('demo-user', source_key, 'Managed Source', 'https://example.com/manage', 'site', True)

    toggle = client.post(f'/ingestion/sources/{source_key}/toggle?enabled=false', headers=headers)
    assert toggle.status_code == 200
    assert toggle.json()['enabled'] is False

    listed = client.get('/ingestion/sources?user_id=demo-user', headers=headers)
    source = next(item for item in listed.json() if item['source_key'] == source_key)
    assert source['enabled'] is False

    deleted = client.delete(f'/ingestion/sources/{source_key}', headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()['ok'] is True

    listed_after = client.get('/ingestion/sources?user_id=demo-user', headers=headers)
    assert all(item['source_key'] != source_key for item in listed_after.json())



def test_run_single_source_endpoint(monkeypatch) -> None:
    import app.ingestion as ingestion

    headers = _auth_headers(username='source_runner')
    source_key = f'run-source-{uuid4().hex}'
    upsert_source('demo-user', source_key, 'Runnable Source', 'https://example.com/run', 'site', True)

    async def fake_fetch(client, url):
        assert url == 'https://example.com/run'
        return ('<html><body><article><h2>Run Me</h2><p>This page has enough content to become an imported entry for the single-source run endpoint.</p></article></body></html>', 'text/html')

    monkeypatch.setattr(ingestion, '_fetch_url', fake_fetch)

    res = client.post(f'/ingestion/sources/{source_key}/run', headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body['fetched_sources'] == 1
    assert body['imported_entries'] == 1
