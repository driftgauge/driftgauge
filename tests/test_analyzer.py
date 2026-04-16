from datetime import datetime, timedelta, timezone

from app.analyzer import analyze_entries
from app.models import Entry


def _entry(idx: int, text: str, dt: datetime) -> Entry:
    return Entry(id=idx, user_id="u1", source="journal", text=text, created_at=dt)


def test_analyzer_flags_multi_signal_deviation() -> None:
    now = datetime(2026, 3, 17, 2, 0, tzinfo=timezone.utc)
    baseline = [
        _entry(1, "Calm day. Worked, ate dinner, going to bed.", now - timedelta(days=5)),
        _entry(2, "Quiet morning. One task list and one short note.", now - timedelta(days=4)),
        _entry(3, "Normal day, nothing unusual, logging off early.", now - timedelta(days=3)),
        _entry(4, "Feeling steady. Saving ideas for later.", now - timedelta(days=2)),
        _entry(5, "Brief note before sleep.", now - timedelta(days=1)),
    ]
    recent = [
        _entry(6, "I feel unstoppable tonight and need to post immediately!!!", now - timedelta(hours=3)),
        _entry(7, "This is urgent and people may be watching what I do right now.", now - timedelta(hours=2)),
        _entry(8, "My mind is moving fast and I cannot stop writing because this feels huge.", now - timedelta(hours=1)),
    ]

    alert = analyze_entries(baseline + recent, window_size=3)

    assert alert.level in {"moderate", "high"}
    assert alert.risk_score >= 40
    assert "baseline" in alert.explanation.lower()


def test_analyzer_can_return_none_for_steady_samples() -> None:
    now = datetime(2026, 3, 17, 20, 0, tzinfo=timezone.utc)
    entries = [
        _entry(1, "Calm day. Finished errands and read a bit.", now - timedelta(days=5)),
        _entry(2, "Pretty normal. Answered messages and made dinner.", now - timedelta(days=4)),
        _entry(3, "Steady mood today. No big changes.", now - timedelta(days=3)),
        _entry(4, "Another regular day with work and a walk.", now - timedelta(days=2)),
        _entry(5, "Usual evening note before bed.", now - timedelta(days=1)),
        _entry(6, "Today also felt normal and manageable.", now - timedelta(hours=3)),
    ]

    alert = analyze_entries(entries, window_size=3)

    assert alert.level in {"none", "low"}
    assert alert.risk_score < 40
