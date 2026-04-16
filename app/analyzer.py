from __future__ import annotations

from collections import Counter
from statistics import mean

from .models import Alert, Entry, FeatureSummary

ELEVATED_TERMS = {
    "unstoppable",
    "brilliant",
    "genius",
    "destined",
    "limitless",
    "invincible",
    "special",
    "transcendent",
    "perfect",
}
PARANOIA_TERMS = {
    "watching",
    "following",
    "targeting",
    "against me",
    "surveillance",
    "plot",
    "tracked",
    "conspiracy",
}
URGENCY_TERMS = {
    "right now",
    "immediately",
    "urgent",
    "cannot stop",
    "need to post",
    "everyone must",
    "tonight",
}


def _tokenize(text: str) -> list[str]:
    return [part.strip(".,!?;:-_()[]{}\"'").lower() for part in text.split() if part.strip()]


def _term_hits(text: str, terms: set[str]) -> int:
    lowered = text.lower()
    return sum(1 for term in terms if term in lowered)


def _punctuation_density(text: str) -> float:
    punct = sum(1 for char in text if char in "!?...")
    return punct / max(len(text), 1)


def _coherence_signal(texts: list[str]) -> float:
    """Cheap proxy: high repetition + abrupt vocabulary spread lowers coherence."""
    tokens = [_tokenize(text) for text in texts]
    all_tokens = [tok for sub in tokens for tok in sub]
    if not all_tokens:
        return 1.0
    counts = Counter(all_tokens)
    repeated = sum(count for _, count in counts.items() if count > 2)
    unique_ratio = len(counts) / len(all_tokens)
    raw = 1.0 - min(0.8, (repeated / len(all_tokens)) * 0.7 + max(0.0, unique_ratio - 0.75))
    return round(max(0.0, min(1.0, raw)), 3)


def _late_night_ratio(entries: list[Entry]) -> float:
    if not entries:
        return 0.0
    late = sum(1 for entry in entries if entry.created_at.hour < 5 or entry.created_at.hour >= 23)
    return late / len(entries)


def analyze_entries(entries: list[Entry], window_size: int = 10) -> Alert:
    if len(entries) < 3:
        raise ValueError("Need at least 3 entries for analysis")

    ordered = sorted(entries, key=lambda item: item.created_at)
    window = ordered[-window_size:]
    baseline = ordered[:-window_size] or ordered[:-3]
    if not baseline:
        baseline = window[: max(1, len(window) // 2)]

    window_lengths = [len(entry.text.split()) for entry in window]
    baseline_lengths = [len(entry.text.split()) for entry in baseline]

    avg_window_len = mean(window_lengths)
    avg_baseline_len = mean(baseline_lengths)
    avg_length_delta = (avg_window_len - avg_baseline_len) / max(avg_baseline_len, 1)

    window_by_day = Counter(entry.created_at.date().isoformat() for entry in window)
    baseline_by_day = Counter(entry.created_at.date().isoformat() for entry in baseline)
    posting_volume_ratio = (mean(window_by_day.values()) / max(mean(baseline_by_day.values() or [1]), 1))

    late_night_ratio = _late_night_ratio(window)
    baseline_late = _late_night_ratio(baseline)

    texts = [entry.text for entry in window]
    combined = "\n".join(texts)

    elevated_hits = _term_hits(combined, ELEVATED_TERMS)
    paranoia_hits = _term_hits(combined, PARANOIA_TERMS)
    urgency_hits = _term_hits(combined, URGENCY_TERMS)

    window_punct = mean(_punctuation_density(entry.text) for entry in window)
    baseline_punct = mean(_punctuation_density(entry.text) for entry in baseline)
    punctuation_delta = window_punct - baseline_punct
    coherence_signal = _coherence_signal(texts)

    score = 0
    if posting_volume_ratio >= 1.75:
        score += 20
    elif posting_volume_ratio >= 1.35:
        score += 10

    if avg_length_delta >= 0.8:
        score += 15
    elif avg_length_delta >= 0.35:
        score += 8

    if late_night_ratio - baseline_late >= 0.35:
        score += 15
    elif late_night_ratio >= 0.4:
        score += 8

    score += min(15, elevated_hits * 4)
    score += min(18, paranoia_hits * 6)
    score += min(12, urgency_hits * 4)

    if punctuation_delta >= 0.015:
        score += 8
    if coherence_signal < 0.55:
        score += 12
    elif coherence_signal < 0.72:
        score += 6

    score = max(0, min(100, round(score)))
    level = "none"
    if score >= 65:
        level = "high"
    elif score >= 40:
        level = "moderate"
    elif score >= 20:
        level = "low"

    features = FeatureSummary(
        posting_volume_ratio=round(posting_volume_ratio, 2),
        late_night_ratio=round(late_night_ratio, 2),
        average_length_delta=round(avg_length_delta, 2),
        elevated_language_hits=elevated_hits,
        paranoia_language_hits=paranoia_hits,
        urgency_language_hits=urgency_hits,
        punctuation_intensity_delta=round(punctuation_delta, 4),
        coherence_signal=coherence_signal,
    )

    changes: list[str] = []
    if features.posting_volume_ratio >= 1.35:
        changes.append("activity volume is higher than your recent baseline")
    if features.late_night_ratio >= 0.4:
        changes.append("more recent activity is happening late at night")
    if features.average_length_delta >= 0.35:
        changes.append("recent writing is noticeably longer than usual")
    if elevated_hits:
        changes.append("recent text includes more elevated or grandiose language")
    if paranoia_hits:
        changes.append("recent text includes more suspicious or persecution-themed language")
    if urgency_hits:
        changes.append("recent text shows more urgency and pressure")
    if coherence_signal < 0.72:
        changes.append("recent writing looks less coherent than your usual baseline")

    if not changes:
        explanation = "No meaningful multi-signal deviation from the current baseline was detected."
    else:
        explanation = "A few recent patterns look different from your usual baseline: " + "; ".join(changes[:4]) + "."

    recommendations = [
        "Pause posting for 30 minutes before sending anything high-stakes.",
        "Check sleep, stimulants, stress, and any recent medication changes.",
        "Read your last few entries side-by-side and ask whether the tone feels like you.",
        "If the pattern continues, message a trusted person or follow your support plan.",
    ]

    return Alert(
        user_id=window[-1].user_id,
        risk_score=score,
        level=level,
        explanation=explanation,
        recommendations=recommendations,
        feature_summary=features,
    )
