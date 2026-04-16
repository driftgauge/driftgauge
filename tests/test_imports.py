from pathlib import Path

from app.connectors.files import import_from_directory


def test_import_from_directory_reads_md_and_jsonl(tmp_path: Path) -> None:
    (tmp_path / "note.md").write_text("hello world", encoding="utf-8")
    (tmp_path / "batch.jsonl").write_text(
        '{"text":"one","created_at":"2026-03-17T01:00:00Z"}\n{"text":"two"}\n',
        encoding="utf-8",
    )

    items = import_from_directory(tmp_path, user_id="u1", source="journal")

    assert len(items) == 3
    assert items[0].entry.user_id == "u1"
    assert any(item.entry.text == "hello world" for item in items)
    assert any(item.entry.text == "one" for item in items)
