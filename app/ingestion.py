from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from .storage import get_conn, insert_entry

DEFAULT_INGEST_INTERVAL_MINUTES = 30
DEFAULT_USER_AGENT = os.getenv("DRIFTGAUGE_USER_AGENT") or "DriftgaugeBot/0.1 (+https://driftgauge.com)"


@dataclass
class IngestResult:
    fetched_sources: int
    imported_entries: int
    errors: list[str]


def ensure_ingestion_tables() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ingestion_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_key TEXT NOT NULL,
                item_hash TEXT NOT NULL UNIQUE,
                item_url TEXT,
                title TEXT,
                created_at TEXT NOT NULL
            );
            """
        )


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
    return [{key: row[key] for key in row.keys()} for row in rows]


def item_seen(item_hash: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM ingested_items WHERE item_hash = ?", (item_hash,)).fetchone()
    return row is not None


def remember_item(source_key: str, item_hash: str, item_url: str | None, title: str | None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO ingested_items (source_key, item_hash, item_url, title, created_at) VALUES (?, ?, ?, ?, ?)",
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


async def ingest_sources_once(user_id: str | None = None) -> IngestResult:
    sources = [source for source in list_sources(user_id) if source["enabled"]]
    fetched = 0
    imported = 0
    errors: list[str] = []

    async with httpx.AsyncClient(headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        for source in sources:
            fetched += 1
            try:
                body, content_type = await _fetch_url(client, source["url"])
                if source["kind"] == "rss" or "xml" in content_type:
                    items = _extract_rss_content(body)
                else:
                    items = _extract_site_content(body, source["url"])

                for item in items:
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

                with get_conn() as conn:
                    conn.execute(
                        "UPDATE ingestion_sources SET last_checked_at = ?, last_status = ? WHERE source_key = ?",
                        (datetime.now(timezone.utc).isoformat(), f"ok:{len(items)}", source["source_key"]),
                    )
            except Exception as exc:
                errors.append(f"{source['source_key']}: {exc}")
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE ingestion_sources SET last_checked_at = ?, last_status = ? WHERE source_key = ?",
                        (datetime.now(timezone.utc).isoformat(), f"error:{exc}", source["source_key"]),
                    )

    return IngestResult(fetched_sources=fetched, imported_entries=imported, errors=errors)


async def background_ingestion_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await ingest_sources_once()
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=DEFAULT_INGEST_INTERVAL_MINUTES * 60)
        except asyncio.TimeoutError:
            continue
