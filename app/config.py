from __future__ import annotations

import os


def database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def is_postgres() -> bool:
    return database_url().startswith(("postgres://", "postgresql://"))


def is_vercel() -> bool:
    return bool(os.getenv("VERCEL"))


def background_loop_enabled() -> bool:
    return os.getenv("DRIFTGAUGE_DISABLE_BACKGROUND_LOOP", "0") != "1" and not is_vercel()


def local_file_imports_enabled() -> bool:
    default = "0" if is_vercel() else "1"
    return os.getenv("DRIFTGAUGE_ENABLE_LOCAL_FILE_IMPORTS", default) == "1"


def cron_secret() -> str:
    return os.getenv("DRIFTGAUGE_CRON_SECRET") or os.getenv("CRON_SECRET", "")
