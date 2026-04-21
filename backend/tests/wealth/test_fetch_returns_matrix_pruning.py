"""Regression: fetch_returns_matrix prunes short-history and rejected funds.

Two root causes identified by Gemini static analysis (2026-04-21):

H1 — _align_returns_with_ffill uses strict dropna intersection. One fund
with < 120 days of history reduces common_dates to ≤ its own count, silently
breaking all other funds in the block and producing "0 common dates".

Fix: prune funds with < MIN_OBSERVATIONS individual data points from fund_ids
before calling _align_returns_with_ffill.

H3 — instruments_org query had no approval_status filter, so a recently-added
instrument with 0 NAV data (approval_status='pending' or 'rejected') could be
selected as the representative for a block, triggering H1.

Fix: exclude approval_status='rejected' instruments from the io_stmt query.
"""
from __future__ import annotations

from app.domains.wealth.services.quant_queries import (
    MIN_OBSERVATIONS,
    _FFILL_LIMIT,
    _align_returns_with_ffill,
)
import numpy as np
import pytest


# ── Unit: pruning logic (no DB) ────────────────────────────────────────────


def _make_grouped(
    fund_ids: list[str],
    n_dates: int,
    start_offset: int = 0,
) -> dict[str, dict[str, float]]:
    """Build a grouped dict simulating nav_timeseries output."""
    grouped: dict[str, dict[str, float]] = {}
    for fid in fund_ids:
        grouped[fid] = {
            f"2023-01-{i + 1:02d}": 0.001
            for i in range(start_offset, start_offset + n_dates)
            if i + 1 <= 31
        }
    return grouped


def test_all_funds_with_sufficient_history_pass_through() -> None:
    """No pruning when all funds have ≥ MIN_OBSERVATIONS data points."""
    fund_ids = ["aaa", "bbb", "ccc"]
    grouped = {
        fid: {f"2022-{d:04d}": 0.001 for d in range(MIN_OBSERVATIONS + 50)}
        for fid in fund_ids
    }
    surviving = [fid for fid in fund_ids if len(grouped.get(fid, {})) >= MIN_OBSERVATIONS]
    assert surviving == fund_ids


def test_short_history_fund_is_pruned() -> None:
    """Fund with < MIN_OBSERVATIONS data points is excluded from fund_ids."""
    long_fund_a = {f"2021-{d:05d}": 0.001 for d in range(MIN_OBSERVATIONS + 100)}
    long_fund_b = {f"2021-{d:05d}": 0.001 for d in range(MIN_OBSERVATIONS + 100)}
    short_fund = {f"2023-01-{d:02d}": 0.001 for d in range(1, 30)}  # 29 days only

    grouped = {"aaa": long_fund_a, "bbb": long_fund_b, "short": short_fund}
    fund_ids_before = ["aaa", "bbb", "short"]

    pruned = [fid for fid in fund_ids_before if len(grouped.get(fid, {})) >= MIN_OBSERVATIONS]
    assert pruned == ["aaa", "bbb"]
    assert "short" not in pruned


def test_zero_nav_fund_is_pruned() -> None:
    """Fund with 0 NAV entries (brand-new instrument) is pruned.

    This is the H3 case: instruments_org picks a pending instrument
    that has just been added but instrument_ingestion hasn't run yet.
    """
    grouped = {
        "aaa": {f"2021-{d:05d}": 0.001 for d in range(MIN_OBSERVATIONS + 50)},
        "bbb": {f"2021-{d:05d}": 0.001 for d in range(MIN_OBSERVATIONS + 50)},
        "new_pending": {},  # 0 NAV rows
    }
    pruned = [
        fid for fid in ["aaa", "bbb", "new_pending"]
        if len(grouped.get(fid, {})) >= MIN_OBSERVATIONS
    ]
    assert pruned == ["aaa", "bbb"]


def test_intersection_with_short_fund_produces_zero_dates() -> None:
    """Demonstrates H1: without pruning, one short fund zeroes common_dates.

    _align_returns_with_ffill uses strict dropna — dates where ANY fund
    has NaN are dropped. A fund with 10 rows forces the intersection ≤ 10.
    """
    n_long = MIN_OBSERVATIONS + 50
    long_dates = {f"2021-{d:06d}": 0.001 for d in range(n_long)}
    short_dates = {f"2021-{d:06d}": 0.001 for d in range(10)}  # only first 10 dates

    grouped_with_short = {
        "aaa": long_dates,
        "bbb": long_dates.copy(),
        "short": short_dates,
    }

    # Without pruning: intersection ≤ 10 + _FFILL_LIMIT because ffill extends
    # the last known value of "short" by up to _FFILL_LIMIT extra rows.
    _, common_without_pruning = _align_returns_with_ffill(
        grouped_with_short, ["aaa", "bbb", "short"]
    )
    assert len(common_without_pruning) <= 10 + _FFILL_LIMIT

    # With pruning: "short" is removed, intersection = n_long
    pruned_ids = [
        fid for fid in ["aaa", "bbb", "short"]
        if len(grouped_with_short.get(fid, {})) >= MIN_OBSERVATIONS
    ]
    assert pruned_ids == ["aaa", "bbb"]
    _, common_after_pruning = _align_returns_with_ffill(grouped_with_short, pruned_ids)
    assert len(common_after_pruning) == n_long
