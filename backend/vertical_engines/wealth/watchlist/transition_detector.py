"""Transition detector — pure function for watchlist outcome comparison.

No DB access. Compares previous and new screening outcomes to determine
transition direction and human-readable message.
"""

from __future__ import annotations


def detect_transition(
    previous_outcome: str,
    new_outcome: str,
) -> tuple[str, str]:
    """Detect transition direction between screening outcomes.

    Args:
        previous_outcome: Previous screening outcome (typically "watchlist").
        new_outcome: New screening outcome ("pass", "fail", or "watchlist").

    Returns:
        Tuple of (direction, message) where direction is one of
        "improvement", "deterioration", or "stable".

    """
    previous_norm = previous_outcome.strip().upper()
    new_norm = new_outcome.strip().upper()

    if previous_norm == new_norm:
        return ("stable", f"Remains {new_norm} — no change detected")

    if new_norm == "PASS":
        return ("improvement", "Candidate for DD initiation")

    if new_norm == "FAIL":
        return ("deterioration", "Candidate for removal")

    # Any other transition (e.g. FAIL -> WATCHLIST, PASS -> WATCHLIST)
    if previous_norm == "FAIL" and new_norm == "WATCHLIST":
        return ("improvement", "Moved from FAIL to WATCHLIST — monitor closely")

    if previous_norm == "PASS" and new_norm == "WATCHLIST":
        return ("deterioration", "Moved from PASS to WATCHLIST — monitor closely")

    return ("stable", f"Transition from {previous_norm} to {new_norm}")
