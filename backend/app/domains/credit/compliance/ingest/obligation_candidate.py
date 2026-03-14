"""
Lightweight deterministic obligation-candidate detector.
No LLM required — keyword + frequency-hint matching.
"""
from __future__ import annotations

OBLIGATION_KEYWORDS = [
    "must file",
    "required to file",
    "annual return",
    "regulatory filing",
    "shall notify",
    "submit to cima",
    "audited financial statements",
    "aml reporting",
    "review annually",
    "renewal notice",
    "must report",
    "shall submit",
    "periodic report",
    "licensed under",
    "expiry",
    "deadline",
]

FREQUENCY_HINTS: dict[str, str] = {
    "annual": "ANNUAL",
    "annually": "ANNUAL",
    "quarterly": "QUARTERLY",
    "monthly": "MONTHLY",
    "ad hoc": "AD_HOC",
}


def detect_obligation_candidate(text: str) -> dict:
    """
    Returns::

        {
            "is_candidate": bool,
            "frequency_hint": Optional[str],   # ANNUAL | QUARTERLY | MONTHLY | AD_HOC | None
            "confidence": float,               # 0.0 – 1.0
        }
    """
    lowered = text.lower()
    matched = any(k in lowered for k in OBLIGATION_KEYWORDS)

    if not matched:
        return {"is_candidate": False, "frequency_hint": None, "confidence": 0.0}

    freq: str | None = None
    for key, val in FREQUENCY_HINTS.items():
        if key in lowered:
            freq = val
            break

    return {
        "is_candidate": True,
        "frequency_hint": freq,
        "confidence": 0.75 if freq else 0.6,
    }
