---
module: InsiderSignals
date: 2026-03-15
problem_type: logic_error
component: service_object
symptoms:
  - "_check_net_selling analyzes all-time transactions instead of rolling 90-day window"
  - "NET_SELLING_THRESHOLD signals triggered by old insider sales (years ago)"
  - "window_days parameter accepted but never used in transaction filtering"
root_cause: logic_error
resolution_type: code_fix
severity: high
tags: [unused-parameter, silent-bug, insider-trading, edgar, date-filtering, false-positive]
---

# Troubleshooting: window_days Parameter Silently Ignored in _check_net_selling

## Problem

The `_check_net_selling()` function in the EDGAR insider signals module accepted a `window_days` parameter (default 90) but never used it. All historical insider transactions were analyzed instead of only the recent rolling window, causing false positive NET_SELLING_THRESHOLD signals from old sales activity.

## Environment

- Module: `vertical_engines/credit/edgar/insider_signals.py`
- Python: 3.12+
- Affected Component: EDGAR insider signal detection (Form 4 analysis)
- Date: 2026-03-15
- PR: #5 (EDGAR engine upgrade with edgartools)
- Commit: `d9ad16f`

## Symptoms

- `_check_net_selling` analyzes ALL historical transactions instead of the configured 90-day window
- Insiders with >10% cumulative lifetime selling trigger NET_SELLING_THRESHOLD signals — even if the selling happened years ago
- False positive insider signals inflate risk assessment in IC memos and deep review evidence packs
- The `window_days=90` parameter is purely decorative — changing it has zero effect

## What Didn't Work

**Direct solution:** Identified by 3 review agents independently during PR #5 code review. The bug was a classic "parameter exists but is never referenced in the function body" — would be caught by a linter rule for unused function parameters.

## Solution

**Code changes:**

```python
# Before (broken) — insider_signals.py:188-205
def _check_net_selling(
    insider_txns: dict[str, list[dict[str, Any]]],
    entity_name: str,
    signals: list[InsiderSignal],
    *,
    window_days: int = 90,
    threshold: float = 0.10,
) -> None:
    """Detect aggregate insider net selling > threshold of holdings in window."""
    for insider, txns in insider_txns.items():
        sells = [t for t in txns if t["acquired_disposed"] == "D" and not t["is_planned"]]
        # ^^^ No date filtering — analyzes ALL transactions regardless of window_days
        if not sells:
            continue
        total_sold = sum(t["shares"] for t in sells)
        max_after = max((t["shares_after"] for t in sells), default=0)

# After (fixed) — insider_signals.py:188-205
def _check_net_selling(
    insider_txns: dict[str, list[dict[str, Any]]],
    entity_name: str,
    signals: list[InsiderSignal],
    *,
    window_days: int = 90,
    threshold: float = 0.10,
) -> None:
    """Detect aggregate insider net selling > threshold of holdings in window."""
    today = datetime.now(UTC).date().isoformat()
    window_cutoff = _add_days_str(today, -window_days)

    for insider, txns in insider_txns.items():
        sells = [
            t for t in txns
            if t["acquired_disposed"] == "D"
            and not t["is_planned"]
            and t.get("date", "") >= window_cutoff  # <-- DATE FILTER ADDED
        ]
        if not sells:
            continue
        total_sold = sum(t["shares"] for t in sells)
        max_after = max((t["shares_after"] for t in sells), default=0)
```

Uses existing helper:
```python
# insider_signals.py:308-314
def _add_days_str(date_str: str, days: int) -> str:
    """Add days to a YYYY-MM-DD date string. Returns YYYY-MM-DD."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return (dt + timedelta(days=days)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return "9999-12-31"
```

## Why This Works

1. **Root cause:** The function signature had `window_days: int = 90` but the `sells` list comprehension only filtered by `acquired_disposed == "D"` and `not t["is_planned"]`. No date comparison was performed.
2. **Impact of the bug:** An insider who sold 5% of holdings in 2020 and 5% in 2021 would show 10% cumulative selling — triggering the threshold signal even though neither period individually warranted concern. The rolling window should isolate recent activity.
3. **The fix** computes `window_cutoff = today - window_days` and adds `t.get("date", "") >= window_cutoff` to the filter. ISO 8601 date strings (`YYYY-MM-DD`) support lexicographic comparison, so the string comparison is correct.

## Prevention

- **Linter rule for unused parameters:** Enable `ARG001` (ruff) or equivalent to flag function parameters that are never referenced in the function body. Keyword-only parameters (`*`) are especially prone to this — they're added to the signature for future use but never wired.
- **Test the parameter's effect:** For every function parameter, write a test that proves changing the parameter changes the output. If `window_days=30` produces different results than `window_days=365`, the parameter is wired correctly.
- **Docstring contract:** The docstring says "in window" — if the implementation doesn't filter by window, the docstring is lying. Treat docstring/code mismatches as bugs.

## Related Issues

- See also: [Monolith to Modular Package](../architecture-patterns/monolith-to-modular-package-with-library-migration.md) — lists this bug in the "Bugs Caught During Review" table
- See also: [Credit Stress Grading Boundary](credit-stress-grading-boundary-StressSeverity-20260315.md) — another logic error caught by review agents in the same sprint
