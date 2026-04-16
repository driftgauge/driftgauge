from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.models import EntryCreate

SUPPORTED_EXTENSIONS = {".txt", ".md", ".jsonl"}


@dataclass
class ImportedItem:
    source_path: str
    entry: EntryCreate


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_text_file(path: Path, user_id: str, source: str) -> EntryCreate:
    text = path.read_text(encoding="utf-8").strip()
    return EntryCreate(user_id=user_id, source=source, text=text)


def parse_jsonl_file(path: Path, user_id: str, default_source: str) -> list[EntryCreate]:
    entries: list[EntryCreate] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        entries.append(
            EntryCreate(
                user_id=user_id,
                source=obj.get("source", default_source),
                text=obj["text"],
                created_at=_parse_timestamp(obj.get("created_at")),
            )
        )
    return entries


def import_from_directory(base_dir: str | Path, user_id: str, source: str) -> list[ImportedItem]:
    root = Path(base_dir)
    items: list[ImportedItem] = []
    if not root.exists():
        return items

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if path.suffix.lower() == ".jsonl":
            parsed = parse_jsonl_file(path, user_id=user_id, default_source=source)
            items.extend(ImportedItem(source_path=str(path), entry=entry) for entry in parsed)
        else:
            items.append(ImportedItem(source_path=str(path), entry=parse_text_file(path, user_id=user_id, source=source)))
    return items


def iter_demo_files(root: str | Path) -> Iterable[Path]:
    path = Path(root)
    if not path.exists():
        return []
    return sorted(p for p in path.rglob("*") if p.is_file())
