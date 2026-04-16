from __future__ import annotations

import os
import re


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-")


def database_url() -> str:
    return _env("DATABASE_URL")


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
    return _env("DRIFTGAUGE_CRON_SECRET") or _env("CRON_SECRET")


def single_user_username() -> str:
    username = _env("DRIFTGAUGE_SINGLE_USER_USERNAME")
    if username:
        return username

    display_name = _env("DRIFTGAUGE_SINGLE_USER_DISPLAY_NAME")
    if display_name:
        return _slugify(display_name)

    return _env("DRIFTGAUGE_SINGLE_USER_ID")


def single_user_display_name() -> str:
    return _env("DRIFTGAUGE_SINGLE_USER_DISPLAY_NAME") or single_user_username() or "Single User"


def single_user_id() -> str:
    configured = _env("DRIFTGAUGE_SINGLE_USER_ID")
    if configured:
        return configured

    username = single_user_username()
    return _slugify(username) if username else "single-user"


def single_user_enabled() -> bool:
    return os.getenv("DRIFTGAUGE_SINGLE_USER_ENABLED", "0") == "1" or bool(single_user_username())


def ingestion_interval_minutes() -> int:
    return max(5, int(os.getenv("DRIFTGAUGE_INGEST_INTERVAL_MINUTES", "5")))


def analysis_interval_minutes() -> int:
    return max(5, int(os.getenv("DRIFTGAUGE_ANALYSIS_INTERVAL_MINUTES", "5")))


def configured_social_sources() -> list[dict[str, str | bool]]:
    if not single_user_enabled():
        return []

    user_id = single_user_id()
    sources: list[dict[str, str | bool]] = []
    platform_defs: list[tuple[str, str, tuple[str, ...]]] = [
        ("instagram", "Instagram", ("DRIFTGAUGE_SOCIAL_INSTAGRAM_URL",)),
        ("facebook", "Facebook", ("DRIFTGAUGE_SOCIAL_FACEBOOK_URL",)),
        ("x", "X / Twitter", ("DRIFTGAUGE_SOCIAL_X_URL", "DRIFTGAUGE_SOCIAL_TWITTER_URL")),
        ("threads", "Threads", ("DRIFTGAUGE_SOCIAL_THREADS_URL",)),
        ("tiktok", "TikTok", ("DRIFTGAUGE_SOCIAL_TIKTOK_URL",)),
        ("snapchat", "Snapchat", ("DRIFTGAUGE_SOCIAL_SNAPCHAT_URL",)),
    ]

    for platform_key, default_label, env_names in platform_defs:
        url = next((value for value in (_env(env_name) for env_name in env_names) if value), "")
        if not url:
            continue

        label = _env(f"DRIFTGAUGE_SOCIAL_{platform_key.upper()}_LABEL") or default_label
        source_key = _env(f"DRIFTGAUGE_SOCIAL_{platform_key.upper()}_SOURCE_KEY") or f"social-{platform_key}"
        kind = _env(f"DRIFTGAUGE_SOCIAL_{platform_key.upper()}_KIND") or platform_key
        sources.append(
            {
                "user_id": user_id,
                "source_key": source_key,
                "label": label,
                "url": url,
                "kind": kind,
                "enabled": True,
            }
        )

    return sources
