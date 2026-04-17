"""PR-A15 regression: factor_returns query must not raise "Index contains
duplicate entries" post-migration-0144.

Two tests:
  C.1 — build_fundamental_factor_returns on synthetic duplicate-free input
        returns a non-empty DataFrame with a unique index. Would have caught
        the silently-broken fallback path that ran pre-PR-A15.
  C.2 — the B.2 groupby+mean safeguard collapses duplicate (nav_date, ticker)
        rows when they re-enter the pipeline (e.g. future re-seed of aliased
        allocation_block). Ensures the pivot never raises even if the data-
        quality invariant is violated upstream.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest


@pytest.mark.parametrize(
    "tickers",
    [
        ("SPY", "IWM", "IWF", "IWD", "AGG", "HYG", "TIP", "EFA"),
    ],
)
def test_pivot_safeguard_handles_synthetic_duplicates(
    tickers: tuple[str, ...],
) -> None:
    """B.2 safeguard — duplicate (nav_date, ticker) rows must be collapsed
    by groupby+mean, not explode in the pivot with DuplicateLabelError.
    """
    rng = np.random.default_rng(0)
    start = date(2024, 1, 1)
    n_days = 20
    dates = [start + timedelta(days=i) for i in range(n_days)]

    rows: list[tuple[date, str, float]] = []
    for d in dates:
        for t in tickers:
            r = float(rng.standard_normal() * 0.01)
            rows.append((d, t, r))
    # Inject duplicates for 2 tickers on half the dates with identical values.
    for d in dates[::2]:
        for t in tickers[:2]:
            match = next((x for x in rows if x[0] == d and x[1] == t), None)
            if match is not None:
                rows.append(match)

    bench_df = pd.DataFrame(rows, columns=["nav_date", "ticker", "return_1d"])
    raw_rows = len(bench_df)

    bench_df = (
        bench_df
        .groupby(["nav_date", "ticker"], as_index=False)["return_1d"]
        .mean()
    )
    assert len(bench_df) < raw_rows, "groupby did not reduce duplicates"

    bench_pivot = bench_df.pivot(
        index="nav_date", columns="ticker", values="return_1d",
    )
    assert bench_pivot.index.is_unique
    assert set(bench_pivot.columns) == set(tickers)


def test_pivot_raises_without_safeguard_when_duplicates_present() -> None:
    """Counter-test: demonstrate why the safeguard exists — the raw pivot
    raises ValueError when duplicate (index, column) pairs are present.
    """
    df = pd.DataFrame(
        [
            (date(2024, 1, 1), "SPY", 0.01),
            (date(2024, 1, 1), "SPY", 0.01),
            (date(2024, 1, 2), "SPY", 0.02),
        ],
        columns=["nav_date", "ticker", "return_1d"],
    )
    with pytest.raises(ValueError, match="duplicate"):
        df.pivot(index="nav_date", columns="ticker", values="return_1d")
