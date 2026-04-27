"""Caller-side regression tests for S05-F14 (analytics route MC caller).

Validates:
1. None daily_return values are filtered, not zero-substituted.
2. Deterministic seed derived from entity_id + data window.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import numpy as np
import pytest

from app.domains.wealth.routes.analytics import _build_mc_inputs


# ── helpers ────────────────────────────────────────────────────────────


def _make_nav_rows(
    n: int,
    *,
    none_every: int | None = None,
    base_date: date = date(2023, 1, 1),
) -> list:
    """Create mock NavRow-like objects with optional None daily_return."""
    rows = []
    for i in range(n):
        if none_every and i % none_every == 0:
            ret = None
        else:
            ret = 0.001 + i * 0.0001
        rows.append(MagicMock(daily_return=ret, nav_date=base_date + timedelta(days=i)))
    return rows


# ── F14 angle 1: None values dropped, not zero-substituted ────────────


def test_filters_none_daily_returns():
    """100 rows with 20 None → array len=80, no synthetic zeros."""
    nav_rows = _make_nav_rows(100, none_every=5)
    daily_returns, _ = _build_mc_inputs(nav_rows, "fund-abc")

    assert len(daily_returns) == 80
    assert 0.0 not in daily_returns.tolist()


def test_all_valid_returns_preserved():
    """When no None values, all rows pass through."""
    nav_rows = _make_nav_rows(50)
    daily_returns, _ = _build_mc_inputs(nav_rows, "fund-xyz")

    assert len(daily_returns) == 50


def test_all_none_returns_empty_array():
    """Edge case: all None → empty array (engine will catch T < 42)."""
    nav_rows = _make_nav_rows(10, none_every=1)
    daily_returns, _ = _build_mc_inputs(nav_rows, "fund-empty")

    assert len(daily_returns) == 0


# ── F14 angle 2: deterministic seed from input ────────────────────────


def test_seed_is_deterministic_for_same_inputs():
    """Same entity_id + same nav window → same seed."""
    nav_rows = _make_nav_rows(252)
    _, seed1 = _build_mc_inputs(nav_rows, "fund-abc")
    _, seed2 = _build_mc_inputs(nav_rows, "fund-abc")

    assert seed1 == seed2


def test_seed_differs_for_different_funds():
    nav_rows = _make_nav_rows(252)
    _, seed_a = _build_mc_inputs(nav_rows, "fund-A")
    _, seed_b = _build_mc_inputs(nav_rows, "fund-B")

    assert seed_a != seed_b


def test_seed_differs_when_data_window_changes():
    nav_rows_252 = _make_nav_rows(252)
    nav_rows_253 = _make_nav_rows(253)
    _, seed_252 = _build_mc_inputs(nav_rows_252, "fund-A")
    _, seed_253 = _build_mc_inputs(nav_rows_253, "fund-A")

    assert seed_252 != seed_253


def test_seed_is_positive_int32():
    """Seed must be positive and fit in 31 bits (0x7FFFFFFF mask)."""
    nav_rows = _make_nav_rows(100)
    _, seed = _build_mc_inputs(nav_rows, "fund-test")

    assert seed >= 0
    assert seed <= 0x7FFFFFFF


def test_seed_with_single_row():
    """Edge case: only 1 nav_row still produces valid seed."""
    nav_rows = _make_nav_rows(1)
    _, seed = _build_mc_inputs(nav_rows, "fund-single")

    assert isinstance(seed, int)
    assert seed >= 0
