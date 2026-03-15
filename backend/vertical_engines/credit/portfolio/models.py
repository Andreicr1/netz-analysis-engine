"""Portfolio engine leaf models — constants and pure helper functions.

LEAF MODULE — zero sibling imports within the portfolio package.
"""
from __future__ import annotations

import re

PORTFOLIO_CONTAINER = "portfolio-active-investments"


def safe_float(value: object | None) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except Exception:
        return None


def extract_percent(text: str | None) -> float | None:
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None
