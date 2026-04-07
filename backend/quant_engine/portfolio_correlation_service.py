"""Portfolio correlation service — on-the-fly candidate vs portfolio correlation.

Pure sync, no I/O, config as parameter. Same pattern as the other
quant_engine modules (attribution_service, cvar_service,
correlation_regime_service).

Scope
-----
The Portfolio Builder flexible-columns layout (design spec
`docs/superpowers/specs/2026-04-08-portfolio-builder-flexible-columns.md`
§3.4) exposes a `correlation_to_portfolio` column on every row of the
Approved Universe table. The number answers the PM's single most
important diversification question at selection time:

    "If I add this candidate to the portfolio I'm currently building,
     how correlated am I really becoming to what I already have?"

This service computes that correlation. It receives pre-loaded return
series (one per instrument) and a list of `current_holding`
instrument ids, and returns a dict `instrument_id → correlation`. It
does NOT touch the database. The calling route handler is responsible
for loading `nav_timeseries.return_1d` for all relevant instruments
and passing arrays.

Why a dedicated service
-----------------------
The existing `correlation_regime_service` is designed for full N×N
pairwise matrix analysis (contagion, absorption ratio,
Marchenko-Pastur denoising) on a closed set of instruments — it is
not the right tool to correlate M candidates against a single
synthetic target. Keeping the two concerns separate keeps each
service simple and avoids the temptation to bolt candidate-scoring
logic onto the contagion analyzer.

Assumptions
-----------
- The synthetic portfolio is an **equal-weight** combination of the
  `current_holdings` in v1. A follow-up can accept target weights
  per holding (`dict[uuid, Decimal]`) when the Builder exposes them
  to the loader.
- Correlations are computed on the **overlapping** window of daily
  returns available to both the candidate and every holding. Sparse
  histories shrink the window transparently.
- A minimum observation floor (`MIN_OVERLAP_DAYS = 45`) drops
  candidates with insufficient overlap — we return `None` instead of
  a noisy correlation the PM would misread as signal.
- Pearson correlation (not Spearman). Wealth is allocating on
  magnitude, not rank order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

import numpy as np
import structlog

logger = structlog.get_logger()

MIN_OVERLAP_DAYS = 45


@dataclass(frozen=True, slots=True)
class ReturnSeries:
    """Immutable carrier for an instrument's return series.

    `dates` and `returns` must be the same length and aligned. `dates`
    is kept as a tuple of ISO strings so the dataclass stays hashable
    and cheap to compare; the service uses them only to intersect
    overlapping windows across instruments.
    """

    instrument_id: UUID
    dates: tuple[str, ...]
    returns: tuple[float, ...]


def compute_portfolio_correlations(
    *,
    candidates: Sequence[ReturnSeries],
    holdings: Sequence[ReturnSeries],
    min_overlap: int = MIN_OVERLAP_DAYS,
) -> dict[UUID, float | None]:
    """Compute Pearson correlation of each candidate vs the equal-weight
    synthetic portfolio formed by `holdings`.

    Returns a dict `candidate.instrument_id → correlation`. Candidates
    that fail the overlap floor or produce a degenerate series
    (constant returns → std == 0) get `None` rather than NaN so the
    API boundary can serialise cleanly.

    Fast path: if `holdings` is empty, every candidate gets `None` —
    the Builder is empty, there is no portfolio to correlate against.
    """
    if not holdings:
        return {c.instrument_id: None for c in candidates}

    # Build a common date index from the union of all holding dates,
    # then intersect with each candidate individually. This keeps the
    # portfolio series reusable across candidates without re-zipping.
    holding_date_union = _union_dates(h.dates for h in holdings)
    if len(holding_date_union) < min_overlap:
        logger.debug(
            "portfolio_correlation_insufficient_holding_history",
            holding_count=len(holdings),
            union_days=len(holding_date_union),
            min_overlap=min_overlap,
        )
        return {c.instrument_id: None for c in candidates}

    # Align holdings to the union and equal-weight them into a single
    # daily return series. Holdings with missing dates contribute 0
    # for that day — this is the "equal weight of whatever is
    # present" convention used across the quant engine.
    portfolio_series_by_date = _equal_weight_portfolio(
        holding_date_union,
        holdings,
    )

    result: dict[UUID, float | None] = {}
    for candidate in candidates:
        overlap_dates = _intersect_dates(candidate.dates, portfolio_series_by_date)
        if len(overlap_dates) < min_overlap:
            result[candidate.instrument_id] = None
            continue

        candidate_lookup = dict(zip(candidate.dates, candidate.returns, strict=False))
        cand_values = np.fromiter(
            (candidate_lookup[d] for d in overlap_dates),
            dtype=np.float64,
            count=len(overlap_dates),
        )
        port_values = np.fromiter(
            (portfolio_series_by_date[d] for d in overlap_dates),
            dtype=np.float64,
            count=len(overlap_dates),
        )

        cand_std = float(np.std(cand_values))
        port_std = float(np.std(port_values))
        if cand_std == 0.0 or port_std == 0.0:
            # A constant series has no meaningful correlation.
            result[candidate.instrument_id] = None
            continue

        # np.corrcoef returns a 2x2 matrix; [0, 1] is the off-diagonal.
        corr = float(np.corrcoef(cand_values, port_values)[0, 1])
        if np.isnan(corr):
            result[candidate.instrument_id] = None
        else:
            # Clamp to [-1, 1] to absorb floating-point drift.
            result[candidate.instrument_id] = max(-1.0, min(1.0, corr))

    return result


def _union_dates(series_dates: Sequence[tuple[str, ...]] | object) -> tuple[str, ...]:
    """Sorted union of all date strings across a collection of series."""
    union: set[str] = set()
    for dates in series_dates:
        union.update(dates)
    return tuple(sorted(union))


def _intersect_dates(
    candidate_dates: tuple[str, ...],
    portfolio_by_date: dict[str, float],
) -> tuple[str, ...]:
    """Sorted intersection of candidate dates with portfolio-series dates."""
    return tuple(sorted(set(candidate_dates).intersection(portfolio_by_date.keys())))


def _equal_weight_portfolio(
    date_union: tuple[str, ...],
    holdings: Sequence[ReturnSeries],
) -> dict[str, float]:
    """Build an equal-weight portfolio return series indexed by date.

    For each date in `date_union`, average the returns of all holdings
    that have a value for that date (holdings missing a date are
    excluded from the average, not treated as zero — this better
    represents the "what I own and trade today" convention).
    """
    lookups = [dict(zip(h.dates, h.returns, strict=False)) for h in holdings]
    out: dict[str, float] = {}
    for d in date_union:
        vals = [lk[d] for lk in lookups if d in lk]
        if vals:
            out[d] = sum(vals) / len(vals)
    return out
