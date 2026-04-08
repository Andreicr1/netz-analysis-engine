"""Expense-ratio unit normalisation (S4-QW4).

The ``expense_ratio_pct`` column arrives in three incompatible shapes
depending on the upstream source:

* **Decimal fraction** (canonical) — e.g. ``0.015`` for 1.5 %. XBRL
  N-CSR OEF taxonomy feeds produce this.
* **Whole percent** — e.g. ``1.5`` for 1.5 %. Some N-CEN CSV exports
  and manual overrides live here.
* **Basis points** — e.g. ``150`` for 1.5 %. Rare, but occasionally
  surfaces from bulk adviser filings.

Any consumer that assumes a single shape silently explodes on the
others. The fee-drag service multiplied whatever it saw by 100 to
produce "percentage points": a legitimate ``1.5`` (percent) therefore
became **150 pp** of fees, a 7 500 bps drag that wiped the gross return
on a single fund in a single day. That is the bug this module exists
to prevent.

``to_decimal_fraction`` is the single entry point. It inspects the
numeric magnitude, converts to a decimal fraction, clamps the result
into a sane institutional range and returns ``None`` when the input
cannot be made sense of. Callers should prefer the fraction form and
scale it to percent / bps at the presentation layer.
"""

from __future__ import annotations

import math
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Institutional sanity bounds for fund expense ratios, expressed as a
# decimal fraction (0.15 = 15 %). The highest documented institutional
# fund fee is ~10 %; 15 % is a conservative upper guard. Anything above
# this is almost certainly a data-entry or unit-conversion bug.
MAX_REASONABLE_EXPENSE_RATIO = 0.15  # 15 %
MIN_REASONABLE_EXPENSE_RATIO = 0.0   # negative fees would be a bug


def to_decimal_fraction(value: Any) -> float | None:
    """Normalise an expense-ratio value to a decimal fraction.

    Scale detection rules (applied in order):

    * ``None`` / empty string / non-numeric → ``None``.
    * ``NaN`` / ``±inf`` → ``None`` (defensive — upstream sometimes
      emits these when a division collapses).
    * ``abs(value) > 100`` → assume basis points, divide by 10 000.
    * ``abs(value) > 1.0`` → assume whole percent, divide by 100.
    * Otherwise → already a decimal fraction, keep as-is.

    After conversion the result is clamped into the
    ``[MIN_REASONABLE_EXPENSE_RATIO, MAX_REASONABLE_EXPENSE_RATIO]``
    interval. Values outside the interval emit a warning log and are
    clamped (not nullified) so downstream calculations still have a
    defensible number — the caller may still surface the warning.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None

    # ── Scale detection ──────────────────────────────────────────────
    abs_v = abs(v)
    if abs_v > 100.0:
        fraction = v / 10_000.0  # basis points → fraction
        source_scale = "bps"
    elif abs_v > 1.0:
        fraction = v / 100.0     # whole percent → fraction
        source_scale = "percent"
    else:
        fraction = v             # already a fraction
        source_scale = "fraction"

    # ── Clamp to institutional range ─────────────────────────────────
    if fraction < MIN_REASONABLE_EXPENSE_RATIO:
        logger.warning(
            "expense_ratio_clamped_below_zero",
            raw=value,
            detected_scale=source_scale,
            clamped_to=MIN_REASONABLE_EXPENSE_RATIO,
        )
        return MIN_REASONABLE_EXPENSE_RATIO
    if fraction > MAX_REASONABLE_EXPENSE_RATIO:
        logger.warning(
            "expense_ratio_clamped_above_max",
            raw=value,
            detected_scale=source_scale,
            clamped_to=MAX_REASONABLE_EXPENSE_RATIO,
        )
        return MAX_REASONABLE_EXPENSE_RATIO

    return fraction
