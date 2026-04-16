from fastapi.testclient import TestClient

from app.alerts import ensure_alert_settings_tables, get_alert_settings
from app.auth import ensure_auth_tables
from app.main import app
from app.storage import init_db

client = TestClient(app)


def _auth_headers(username: str = 'alert_tester', password: str = 'password123') -> dict:
    reg = client.post('/auth/register', json={'username': username, 'password': password})
    if reg.status_code == 200:
        token = reg.json()['token']
    else:
        token = client.post('/auth/login', json={'username': username, 'password': password}).json()['token']
    return {'X-Auth-Token': token}


def setup_module() -> None:
    init_db()
    ensure_auth_tables()
    ensure_alert_settings_tables()


def test_alert_settings_roundtrip() -> None:
    headers = _auth_headers()
    res = client.post(
        '/alerts/settings/demo-user',
        headers=headers,
        json={'user_id': 'demo-user', 'email_enabled': True, 'email_to': 'alerts@example.com'},
    )
    assert res.status_code == 200
    body = res.json()
    assert body['email_enabled'] is True
    assert body['email_to'] == 'alerts@example.com'
    settings = get_alert_settings('demo-user')
    assert settings['email_to'] == 'alerts@example.com'
