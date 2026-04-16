import hashlib
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.auth import ensure_auth_tables, verify_user
from app.privacy import ensure_privacy_tables
from app.scheduler import ensure_scheduler_tables
from app.storage import get_conn, init_db

client = TestClient(app)


def setup_module() -> None:
    init_db()
    ensure_auth_tables()
    ensure_privacy_tables()
    ensure_scheduler_tables()


def test_register_login_and_protected_flow() -> None:
    reg = client.post('/auth/register', json={'username': 'alice_auth_test', 'password': 'password123'})
    if reg.status_code == 200:
        token = reg.json()['token']
    else:
        login = client.post('/auth/login', json={'username': 'alice_auth_test', 'password': 'password123'})
        assert login.status_code == 200
        token = login.json()['token']

    entry = client.post(
        '/entries',
        headers={'X-Auth-Token': token},
        json={'user_id': 'alice-user', 'source': 'journal', 'text': 'calm note'},
    )
    assert entry.status_code == 200

    got = client.get('/entries?user_id=alice-user', headers={'X-Auth-Token': token})
    assert got.status_code == 200
    assert isinstance(got.json(), list)


def test_schedule_run_endpoint() -> None:
    login = client.post('/auth/login', json={'username': 'alice_auth_test', 'password': 'password123'})
    token = login.json()['token']

    client.post('/entries', headers={'X-Auth-Token': token}, json={'user_id': 'sched-user', 'source': 'journal', 'text': 'normal day'})
    client.post('/entries', headers={'X-Auth-Token': token}, json={'user_id': 'sched-user', 'source': 'journal', 'text': 'steady work today'})
    client.post('/entries', headers={'X-Auth-Token': token}, json={'user_id': 'sched-user', 'source': 'drafts', 'text': 'I feel unstoppable tonight and need to post immediately'})

    job = client.post(
        '/schedule/jobs',
        headers={'X-Auth-Token': token},
        json={'user_id': 'sched-user', 'enabled': True, 'interval_minutes': 5},
    )
    assert job.status_code == 200

    run = client.post('/schedule/run', headers={'X-Auth-Token': token})
    assert run.status_code == 200
    assert 'analyzed_users' in run.json()


def test_legacy_password_hash_upgrades_on_login() -> None:
    username = 'legacy_hash_user'
    password = 'password123'
    legacy_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()

    with get_conn() as conn:
        conn.execute('DELETE FROM users WHERE username = ?', (username,))
        conn.execute(
            'INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)',
            (username, legacy_hash, datetime.now(timezone.utc).isoformat()),
        )

    assert verify_user(username, password) is True

    with get_conn() as conn:
        row = conn.execute('SELECT password_hash FROM users WHERE username = ?', (username,)).fetchone()

    assert row is not None
    assert row['password_hash'].startswith('pbkdf2_sha256$')
