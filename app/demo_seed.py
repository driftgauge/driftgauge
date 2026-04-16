from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .storage import init_db, insert_entry


def seed() -> None:
    init_db()
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    baseline_texts = [
        "Worked a normal day. Need to reply to two emails and finish laundry.",
        "Pretty calm today. I want an early night and less screen time.",
        "Journal note: steady mood, dinner was fine, nothing unusual.",
        "Drafted one post, then decided to save it for tomorrow.",
        "Light work day. Going to sleep soon.",
        "I had coffee, answered messages, and wrapped things up by 9.",
    ]
    for index, text in enumerate(baseline_texts, start=12):
        insert_entry(
            user_id="demo-user",
            source="journal",
            text=text,
            created_at=now - timedelta(days=6 - index % 5, hours=index),
        )

    recent_texts = [
        "I have so many ideas right now and I need to post immediately because this could change everything.",
        "Nobody gets it yet but I can see the whole pattern. I feel brilliant and almost unstoppable tonight!!!",
        "I should probably keep writing because the connections are coming fast and people may be watching what I say.",
        "It is 2am and I am still going because I cannot stop and this feels important right now.",
    ]
    for offset, text in enumerate(recent_texts, start=1):
        insert_entry(
            user_id="demo-user",
            source="drafts",
            text=text,
            created_at=now - timedelta(hours=offset),
        )


if __name__ == "__main__":
    seed()
