"""Codex catch #3 — watchlist peer cohort uses full universe, not watchlist subset.

PR-Q70: watchlist_batch.py pre-filtered instruments to approval_status='watchlist'
before building peer cohorts. A watchlist fund's percentile rank was computed
against other watchlist funds (self-selected weak/borderline cohort), not the
broader universe. Created artificial PASS/FAIL transitions driven by watchlist
composition rather than true market-relative standing.

Post-Q70: peer_values built from full active universe; evaluation targets
restricted to watchlist subset.
"""

from __future__ import annotations

import uuid

from app.domains.wealth.services.screener_peer_values_builder import (
    METRIC_NAMES_BY_TYPE,
    build_per_instrument_peer_values,
)


def _make_instrument(
    *, strategy_label: str = "Long/Short Equity",
    instrument_type: str = "fund",
) -> dict:
    return {
        "instrument_id": uuid.uuid4(),
        "instrument_type": instrument_type,
        "attributes": {"strategy_label": strategy_label},
    }


def test_watchlist_target_peer_values_from_full_universe() -> None:
    """Watchlist fund's peer_values should reflect FULL universe, not watchlist subset.

    Setup: 3 'watchlist' funds + 7 non-watchlist in same strategy_label cohort.
    Build peer_values from full universe (10 instruments).
    Assert: each watchlist fund sees all 10 cohort members in its peer values.
    """
    # 3 watchlist instruments
    watchlist = [_make_instrument() for _ in range(3)]
    # 7 non-watchlist (approved / pending / etc)
    non_watchlist = [_make_instrument() for _ in range(7)]

    full_universe = watchlist + non_watchlist

    # Assign sharpe metrics to all 10
    metric_dicts = {}
    for idx, inst in enumerate(full_universe):
        metric_dicts[inst["instrument_id"]] = {
            "sharpe_ratio": 0.5 + idx * 0.1,
            "max_drawdown": -(30 - idx * 2.0),
            "pct_positive_months": 50.0 + idx,
            "annual_volatility_pct": 10.0 + idx,
        }

    # Build peer_values from FULL universe (post-Q70 correct behavior)
    full_peer_values = build_per_instrument_peer_values(
        instruments=full_universe,
        instrument_metrics_by_id=metric_dicts,
        metric_names_by_type=METRIC_NAMES_BY_TYPE,
    )

    # Build peer_values from watchlist-only (pre-Q70 bug)
    watchlist_only_peer_values = build_per_instrument_peer_values(
        instruments=watchlist,
        instrument_metrics_by_id={k: v for k, v in metric_dicts.items()
                                  if k in {w["instrument_id"] for w in watchlist}},
        metric_names_by_type=METRIC_NAMES_BY_TYPE,
    )

    # Assert: full universe peer values have more data points
    wl_id = watchlist[0]["instrument_id"]
    full_sharpe_peers = full_peer_values.get(wl_id, {}).get("sharpe_ratio", [])
    wl_only_sharpe_peers = watchlist_only_peer_values.get(wl_id, {}).get("sharpe_ratio", [])

    assert len(full_sharpe_peers) == 10, (
        f"Full universe cohort should have 10 members, got {len(full_sharpe_peers)}"
    )
    assert len(wl_only_sharpe_peers) == 3, (
        f"Watchlist-only cohort should have 3 members, got {len(wl_only_sharpe_peers)}"
    )


def test_watchlist_cohort_size_affects_percentile_rank() -> None:
    """A fund's percentile rank differs between watchlist-only and full-universe cohorts.

    Demonstrates that the restricted cohort produces a different (less meaningful) rank.
    """
    from vertical_engines.wealth.screener.quant_metrics import composite_score

    # Fund at bottom of its 3-member watchlist cohort but mid-pack in 10-member universe
    fund_metrics = {"sharpe_ratio": 0.5}

    # Watchlist-only cohort: fund is the worst of 3
    wl_peers = {"sharpe_ratio": [0.5, 0.7, 0.9]}
    wl_score = composite_score(fund_metrics, wl_peers, {"sharpe_ratio": 1.0})

    # Full universe cohort: fund is low but not extreme
    full_peers = {"sharpe_ratio": [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2]}
    full_score = composite_score(fund_metrics, full_peers, {"sharpe_ratio": 1.0})

    assert wl_score is not None
    assert full_score is not None
    # Full universe gives a more favorable (but accurate) rank since there are
    # instruments below this fund
    assert full_score > wl_score, (
        f"Full universe rank ({full_score:.3f}) should differ from "
        f"watchlist-only rank ({wl_score:.3f})"
    )
