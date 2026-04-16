from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from .config import ingestion_interval_minutes
from .storage import get_conn, id_column_sql, insert_entry

DEFAULT_USER_AGENT = os.getenv("DRIFTGAUGE_USER_AGENT") or "DriftgaugeBot/0.1 (+https://driftgauge.com)"
DEFAULT_HISTORICAL_MAX_PAGES = 25
DEFAULT_HISTORICAL_MAX_ITEMS = 250
IGNORED_HISTORY_PATH_SNIPPETS = (
    "/login",
    "/accounts/login",
    "/signup",
    "/privacy",
    "/terms",
    "/about",
    "/help",
    "/settings",
    "/explore",
    "/discover",
    "/developer",
    "/recover/",
    "/reg/",
    "/checkpoint/",
    "/challenge/",
    "/ads/create",
)
HISTORY_LINK_HINTS = (
    "/p/",
    "/reel/",
    "/status/",
    "/posts/",
    "/post/",
    "/videos/",
    "/video/",
    "/@",
    "/thread/",
    "?page=",
    "?cursor=",
    "?after=",
    "max_id=",
)


@dataclass
class IngestResult:
    fetched_sources: int
    imported_entries: int
    errors: list[str]
    fetched_pages: int = 0


def ensure_ingestion_tables() -> None:
    with get_conn() as conn:
        conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS ingestion_sources (
                id {id_column_sql()},
                user_id TEXT NOT NULL,
                source_key TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL,
                url TEXT NOT NULL,
                kind TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_checked_at TEXT,
                last_status TEXT
            );

            CREATE TABLE IF NOT EXISTS ingested_items (
                id {id_column_sql()},
                source_key TEXT NOT NULL,
                item_hash TEXT NOT NULL UNIQUE,
                item_url TEXT,
                title TEXT,
                created_at TEXT NOT NULL
            );
            """
        )


def _serialize_source_row(row: Any) -> dict[str, Any]:
    source = {key: row[key] for key in row.keys()}
    source["enabled"] = bool(source.get("enabled"))
    return source


def upsert_source(user_id: str, source_key: str, label: str, url: str, kind: str, enabled: bool = True) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO ingestion_sources (user_id, source_key, label, url, kind, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
              user_id = excluded.user_id,
              label = excluded.label,
              url = excluded.url,
              kind = excluded.kind,
              enabled = excluded.enabled
            """,
            (user_id, source_key, label, url, kind, 1 if enabled else 0, now),
        )
    return {"user_id": user_id, "source_key": source_key, "label": label, "url": url, "kind": kind, "enabled": enabled}


def list_sources(user_id: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM ingestion_sources"
    params: list[Any] = []
    if user_id:
        query += " WHERE user_id = ?"
        params.append(user_id)
    query += " ORDER BY id"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_serialize_source_row(row) for row in rows]


def get_source(source_key: str, user_id: str | None = None) -> dict[str, Any] | None:
    query = "SELECT * FROM ingestion_sources WHERE source_key = ?"
    params: list[Any] = [source_key]
    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)
    with get_conn() as conn:
        row = conn.execute(query, params).fetchone()
    return _serialize_source_row(row) if row else None


def set_source_enabled(source_key: str, enabled: bool, user_id: str | None = None) -> dict[str, Any] | None:
    with get_conn() as conn:
        if user_id:
            conn.execute(
                "UPDATE ingestion_sources SET enabled = ? WHERE source_key = ? AND user_id = ?",
                (1 if enabled else 0, source_key, user_id),
            )
        else:
            conn.execute(
                "UPDATE ingestion_sources SET enabled = ? WHERE source_key = ?",
                (1 if enabled else 0, source_key),
            )
    return get_source(source_key, user_id)


def delete_source(source_key: str, user_id: str | None = None) -> bool:
    with get_conn() as conn:
        if user_id:
            result = conn.execute("DELETE FROM ingestion_sources WHERE source_key = ? AND user_id = ?", (source_key, user_id))
        else:
            result = conn.execute("DELETE FROM ingestion_sources WHERE source_key = ?", (source_key,))
    return bool(result.rowcount)


def clear_source_data(source_key: str, user_id: str | None = None) -> dict[str, Any] | None:
    source = get_source(source_key, user_id)
    if not source:
        return None

    with get_conn() as conn:
        deleted_items = conn.execute("DELETE FROM ingested_items WHERE source_key = ?", (source_key,)).rowcount
        if user_id:
            deleted_entries = conn.execute(
                "DELETE FROM entries WHERE user_id = ? AND source = ?",
                (user_id, source["label"]),
            ).rowcount
            conn.execute(
                "UPDATE ingestion_sources SET last_checked_at = NULL, last_status = NULL WHERE source_key = ? AND user_id = ?",
                (source_key, user_id),
            )
        else:
            deleted_entries = conn.execute(
                "DELETE FROM entries WHERE source = ?",
                (source["label"],),
            ).rowcount
            conn.execute(
                "UPDATE ingestion_sources SET last_checked_at = NULL, last_status = NULL WHERE source_key = ?",
                (source_key,),
            )

    return {
        "source_key": source_key,
        "deleted_entries": deleted_entries,
        "deleted_items": deleted_items,
    }


def item_seen(item_hash: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM ingested_items WHERE item_hash = ?", (item_hash,)).fetchone()
    return row is not None


def remember_item(source_key: str, item_hash: str, item_url: str | None, title: str | None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO ingested_items (source_key, item_hash, item_url, title, created_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(item_hash) DO NOTHING",
            (source_key, item_hash, item_url, title, datetime.now(timezone.utc).isoformat()),
        )


def _hash_item(source_key: str, title: str | None, text: str, item_url: str | None) -> str:
    payload = json.dumps({"source_key": source_key, "title": title or "", "text": text[:2000], "url": item_url or ""}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _extract_site_content(html: str, base_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict[str, str]] = []

    for article in soup.find_all(["article"]):
        title_node = article.find(["h1", "h2", "h3"])
        text = article.get_text(" ", strip=True)
        link = article.find("a", href=True)
        if len(text) < 40:
            continue
        items.append(
            {
                "title": title_node.get_text(" ", strip=True) if title_node else "Website article",
                "text": text,
                "url": urljoin(base_url, link["href"]) if link else base_url,
            }
        )

    if not items:
        title = soup.title.get_text(" ", strip=True) if soup.title else "Website page"
        body = soup.get_text(" ", strip=True)
        if body:
            items.append({"title": title, "text": body[:5000], "url": base_url})

    return items[:25]


def _extract_rss_content(xml_text: str) -> list[dict[str, str]]:
    root = ElementTree.fromstring(xml_text)
    items: list[dict[str, str]] = []
    for node in root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry"):
        title = (node.findtext("title") or node.findtext("{http://www.w3.org/2005/Atom}title") or "Feed entry").strip()
        link = node.findtext("link") or ""
        if not link:
            link_node = node.find("{http://www.w3.org/2005/Atom}link")
            if link_node is not None:
                link = link_node.attrib.get("href", "")
        description = (
            node.findtext("description")
            or node.findtext("summary")
            or node.findtext("{http://www.w3.org/2005/Atom}summary")
            or node.findtext("content")
            or ""
        )
        text = BeautifulSoup(description, "html.parser").get_text(" ", strip=True) or title
        items.append({"title": title, "text": text, "url": link})
    return items[:25]


async def _fetch_url(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    response = await client.get(url, follow_redirects=True, timeout=20.0)
    response.raise_for_status()
    return response.text, response.headers.get("content-type", "")


def _source_is_due(source: dict[str, Any], min_interval_minutes: int) -> bool:
    last_checked_at = source.get("last_checked_at")
    if not last_checked_at:
        return True

    last_checked = datetime.fromisoformat(last_checked_at)
    if last_checked.tzinfo is None:
        last_checked = last_checked.replace(tzinfo=timezone.utc)

    return datetime.now(timezone.utc) - last_checked.astimezone(timezone.utc) >= timedelta(minutes=min_interval_minutes)


def _normalize_history_url(candidate: str, base_url: str) -> str:
    return urldefrag(urljoin(base_url, candidate))[0]


def _same_origin(first: str, second: str) -> bool:
    a = urlparse(first)
    b = urlparse(second)
    return (a.scheme, a.netloc) == (b.scheme, b.netloc)


def _discover_history_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    discovered: list[str] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        url = _normalize_history_url(anchor["href"], base_url)
        lowered_url = url.lower()
        if not _same_origin(url, base_url):
            continue
        if any(snippet in lowered_url for snippet in IGNORED_HISTORY_PATH_SNIPPETS):
            continue

        text = anchor.get_text(" ", strip=True).lower()
        rel = " ".join(anchor.get("rel") or []).lower()
        in_article = anchor.find_parent("article") is not None
        looks_historical = (
            in_article
            or any(token in lowered_url for token in HISTORY_LINK_HINTS)
            or any(token in text for token in ("older", "more", "next", "previous", "archive"))
            or "next" in rel
            or bool(urlparse(url).query)
        )
        if not looks_historical:
            continue
        if url in seen or url == base_url:
            continue
        seen.add(url)
        discovered.append(url)

    return discovered[:50]


def _extract_items_for_page(source: dict[str, Any], body: str, content_type: str, page_url: str) -> list[dict[str, str]]:
    if source["kind"] == "rss" or "xml" in content_type:
        return _extract_rss_content(body)
    return _extract_site_content(body, page_url)


def _is_blocked_or_low_value_item(item: dict[str, str]) -> bool:
    url = (item.get("url") or "").lower()
    title = (item.get("title") or "").lower()
    text = (item.get("text") or "").lower()
    combined = f"{title} {text}"

    if any(snippet in url for snippet in IGNORED_HISTORY_PATH_SNIPPETS):
        return True

    blocked_markers = (
        "create an account to connect with friends",
        "i already have an account",
        "log in or sign up",
        "by tapping submit",
        "recover your account",
        "privacy policy and cookies policy",
        "people who use our service may have uploaded your contact information",
    )
    if any(marker in combined for marker in blocked_markers):
        return True

    if len(text.strip()) < 30:
        return True

    return False


def _persist_items_for_source(source: dict[str, Any], items: list[dict[str, str]], max_items: int | None = None) -> int:
    imported = 0
    for item in items:
        if max_items is not None and imported >= max_items:
            break
        if _is_blocked_or_low_value_item(item):
            continue
        item_hash = _hash_item(source["source_key"], item.get("title"), item["text"], item.get("url"))
        if item_seen(item_hash):
            continue
        remember_item(source["source_key"], item_hash, item.get("url"), item.get("title"))
        insert_entry(
            user_id=source["user_id"],
            source=source["label"],
            text=f"{item.get('title', 'Untitled')}\n\n{item['text']}\n\nSource URL: {item.get('url', source['url'])}",
            created_at=datetime.now(timezone.utc),
        )
        imported += 1
    return imported


async def ingest_sources_once(
    user_id: str | None = None,
    respect_min_interval: bool = False,
    historical_backfill: bool = False,
    max_pages_per_source: int = DEFAULT_HISTORICAL_MAX_PAGES,
    max_items_per_source: int = DEFAULT_HISTORICAL_MAX_ITEMS,
    source_keys: list[str] | None = None,
) -> IngestResult:
    all_sources = list_sources(user_id)
    if source_keys:
        allowed_keys = set(source_keys)
        sources = [source for source in all_sources if source["source_key"] in allowed_keys]
    else:
        sources = [source for source in all_sources if source["enabled"]]
    if respect_min_interval:
        sources = [source for source in sources if _source_is_due(source, ingestion_interval_minutes())]
    fetched = 0
    fetched_pages = 0
    imported = 0
    errors: list[str] = []

    async with httpx.AsyncClient(headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        for source in sources:
            fetched += 1
            source_pages = 0
            source_imported = 0
            queue: deque[str] = deque([source["url"]])
            visited: set[str] = set()
            try:
                while queue:
                    page_url = queue.popleft()
                    if page_url in visited:
                        continue
                    visited.add(page_url)

                    body, content_type = await _fetch_url(client, page_url)
                    source_pages += 1
                    fetched_pages += 1

                    items = _extract_items_for_page(source, body, content_type, page_url)
                    remaining = max_items_per_source - source_imported if historical_backfill else None
                    source_imported += _persist_items_for_source(source, items, remaining)

                    if not historical_backfill:
                        break
                    if source_pages >= max_pages_per_source or source_imported >= max_items_per_source:
                        break

                    for link in _discover_history_links(body, page_url):
                        if link not in visited and link not in queue:
                            queue.append(link)

                imported += source_imported
                status = f"ok:{source_imported} items/{source_pages} pages"
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE ingestion_sources SET last_checked_at = ?, last_status = ? WHERE source_key = ?",
                        (datetime.now(timezone.utc).isoformat(), status, source["source_key"]),
                    )
            except Exception as exc:
                errors.append(f"{source['source_key']}: {exc}")
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE ingestion_sources SET last_checked_at = ?, last_status = ? WHERE source_key = ?",
                        (datetime.now(timezone.utc).isoformat(), f"error:{exc}", source["source_key"]),
                    )

    return IngestResult(fetched_sources=fetched, imported_entries=imported, errors=errors, fetched_pages=fetched_pages)


async def background_ingestion_loop(stop_event: asyncio.Event, user_id: str | None = None) -> None:
    while not stop_event.is_set():
        try:
            await ingest_sources_once(user_id=user_id)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=ingestion_interval_minutes() * 60)
        except asyncio.TimeoutError:
            continue
