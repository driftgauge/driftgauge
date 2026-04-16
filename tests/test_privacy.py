from app.privacy import ensure_privacy_tables, get_user_settings, set_user_settings
from app.storage import init_db


def setup_module() -> None:
    init_db()
    ensure_privacy_tables()


def test_privacy_settings_round_trip() -> None:
    set_user_settings(user_id="privacy-user", retention_days=14, allow_file_imports=False)
    settings = get_user_settings("privacy-user")
    assert settings["retention_days"] == 14
    assert settings["allow_file_imports"] is False
