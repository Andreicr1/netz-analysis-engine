"""PR-A19.1 Section B.2 — μ sanity gate unit tests.

Exercises ``_apply_mu_sanity_gate`` in isolation, no DB required.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.domains.wealth.services.quant_queries import (
    MU_SANITY_BOUND_DEFAULT,
    NAV_DAYS_1Y_MIN,
    _apply_mu_sanity_gate,
)

AS_OF = date(2026, 4, 17)


def _flat_returns(daily: float, n_days: int) -> dict[date, float]:
    """Build a fund_returns[sid] dict with ``n_days`` consecutive trading days."""
    return {AS_OF - timedelta(days=i): daily for i in range(n_days)}


def test_keeps_fund_within_bound_and_history() -> None:
    fr = {"keep": _flat_returns(0.0003, 250)}  # ≈ 7.6% annualized
    kept, drops = _apply_mu_sanity_gate(fr, ["keep"], AS_OF)
    assert kept == ["keep"]
    assert drops == []


def test_drops_mu_outlier_above_bound() -> None:
    fr = {"bad": _flat_returns(0.002, 250)}  # ≈ 50% annualized
    kept, drops = _apply_mu_sanity_gate(fr, ["bad"], AS_OF)
    assert kept == []
    assert drops[0][1] == "mu_outlier"
    assert drops[0][2] is not None
    assert abs(drops[0][2]) > MU_SANITY_BOUND_DEFAULT


def test_drops_short_history() -> None:
    fr = {"newish": _flat_returns(0.0003, NAV_DAYS_1Y_MIN - 10)}
    kept, drops = _apply_mu_sanity_gate(fr, ["newish"], AS_OF)
    assert kept == []
    assert drops[0][1] == "short_history"


def test_negative_mu_outlier_also_dropped() -> None:
    fr = {"crash": _flat_returns(-0.002, 250)}  # ≈ -50% annualized
    kept, drops = _apply_mu_sanity_gate(fr, ["crash"], AS_OF)
    assert kept == []
    assert drops[0][1] == "mu_outlier"


def test_custom_bound_is_respected() -> None:
    # 25% annualized would pass default 40% bound but fails tighter 20%.
    fr = {"edge": _flat_returns(0.001, 250)}
    kept, _ = _apply_mu_sanity_gate(fr, ["edge"], AS_OF, mu_sanity_bound=0.20)
    assert kept == []


def test_multiple_funds_mixed_outcomes() -> None:
    fr = {
        "good": _flat_returns(0.0003, 250),
        "levered": _flat_returns(0.0025, 250),  # ≈ 63% annualized
        "new": _flat_returns(0.0003, 50),
    }
    kept, drops = _apply_mu_sanity_gate(
        fr, ["good", "levered", "new"], AS_OF,
    )
    assert kept == ["good"]
    reasons = {d[0]: d[1] for d in drops}
    assert reasons == {"levered": "mu_outlier", "new": "short_history"}


@pytest.mark.parametrize("bound", [0.1, 0.4, 0.6])
def test_keeps_exactly_at_bound(bound: float) -> None:
    # Annualized 9% always under any reasonable bound.
    fr = {"stable": _flat_returns(0.00035, 250)}
    kept, _ = _apply_mu_sanity_gate(fr, ["stable"], AS_OF, mu_sanity_bound=bound)
    assert kept == ["stable"]
