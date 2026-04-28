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
    * ``abs(value) > MAX_REASONABLE_EXPENSE_RATIO`` (0.15) → assume
      whole percent, divide by 100.
    * Otherwise (``[0, 0.15]``) → already a decimal fraction, keep
      as-is.

    **Band-ambiguity note (PR-Q57, S07-F03):** inputs in ``(0.15, 1.0]``
    are now classified as whole percent rather than fraction. This fixes
    the dominant defect class (N-CEN exports emitting ``0.5`` for 0.5 %)
    but introduces a narrow ambiguity: a value like ``0.10`` intended as
    a decimal fraction (= 10 %) would instead be treated as the whole
    percent 0.10 % (= 0.001 fraction). In practice XBRL canonical
    fractions in this range are extremely rare (virtually all lie below
    0.05), and the false-positive cost (treating 10 % as 0.10 %) is far
    lower than the false-negative cost (treating 0.5 % as 50 %, which
    collapsed fee_efficiency to 0 for ~60 % of index/ETF funds).

    Q71 follow-up: emits ``expense_ratio_ambiguous_percent_or_fraction`` warning
    log when input falls in this band, restoring observability that pre-Q57
    provided via ``expense_ratio_clamped_above_max``.

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
    elif abs_v > MAX_REASONABLE_EXPENSE_RATIO:
        fraction = v / 100.0     # whole percent → fraction
        source_scale = "percent"
        # Q71 fix: emit observability for the (0.15, 1.0] ambiguous band.
        # Per Q57 design, we treat these as whole percent (dominant N-CEN case).
        # But a value of e.g. 0.20 could ALSO be a malformed XBRL fraction (= 20% ER).
        # Pre-Q57 the malformed-fraction case clamped to MAX_REASONABLE_EXPENSE_RATIO
        # with warning; post-Q57 we silently divide by 100. Restore the warning
        # so production audit can detect ingestion-source data quality issues.
        if abs_v <= 1.0:
            logger.warning(
                "expense_ratio_ambiguous_percent_or_fraction",
                raw=value,
                interpreted_as_percent=v,
                interpreted_as_fraction=fraction,
                note=(
                    "Input in (0.15, 1.0] band — assumed whole percent per Q57 "
                    "convention. If source was XBRL fraction, value would have "
                    "represented a high-fee outlier (>15%) and would have been "
                    "clamped pre-Q57. Verify upstream source convention."
                ),
            )
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
