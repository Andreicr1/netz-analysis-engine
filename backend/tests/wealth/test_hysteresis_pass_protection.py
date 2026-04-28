"""Regression tests for S08-F09 — hysteresis PASS-history symmetric protection (PR-Q66)."""

from __future__ import annotations

from vertical_engines.wealth.screener.layer_evaluator import determine_status

# ── F09 regression: the canonical asymmetry ─────────────────────────────


def test_pass_fund_at_039_demotes_to_watchlist_not_fail() -> None:
    """PASS fund at score 0.39 stays as WATCHLIST (matches WATCHLIST fund behavior).

    Pre-fix: 0.39 < 0.55 → True; 0.39 >= 0.40 → False → FAIL
    Post-fix: 0.39 < 0.55 → True; 0.39 >= 0.35 → True → WATCHLIST
    """
    assert determine_status(0.39, "PASS") == "WATCHLIST"


def test_watchlist_fund_at_039_stays_watchlist() -> None:
    """WATCHLIST fund at 0.39 stays — no change pre/post fix (regression guard)."""
    assert determine_status(0.39, "WATCHLIST") == "WATCHLIST"


def test_pass_and_watchlist_funds_at_same_score_have_same_outcome() -> None:
    """Symmetric hysteresis: PASS and WATCHLIST funds at the same score should
    have the same demotion outcome (the PASS history is a signal of quality,
    not a reason for harsher treatment)."""
    for score in [0.36, 0.39, 0.42, 0.45, 0.50]:
        pass_outcome = determine_status(score, "PASS")
        watchlist_outcome = determine_status(score, "WATCHLIST")
        # Either both stay/promote or both demote consistently
        # PASS at 0.42 stays PASS (above 0.55 demotion threshold? no, 0.42<0.55)
        # PASS at 0.42 → demote check: 0.42<0.55 True → 0.42>=0.35 True → WATCHLIST
        # WATCHLIST at 0.42 → 0.42 >= 0.65? No, 0.42 < 0.35? No → stays WATCHLIST
        # Both → WATCHLIST. Symmetric ✓
        # PASS at 0.50 → 0.50<0.55 True → 0.50>=0.35 True → WATCHLIST
        # WATCHLIST at 0.50 → 0.50>=0.65? No, 0.50<0.35? No → stays WATCHLIST
        # Both → WATCHLIST. Symmetric ✓
        assert pass_outcome == watchlist_outcome, (
            f"Asymmetry at score={score}: PASS→{pass_outcome}, WATCHLIST→{watchlist_outcome}"
        )


# ── F09 regression: catastrophic drops still earn FAIL ─────────────────


def test_pass_fund_at_catastrophic_drop_earns_fail() -> None:
    """PASS fund at score 0.30 (well below watchlist_threshold - hysteresis = 0.35)
    earns FAIL — buffer doesn't protect from genuine catastrophic drops."""
    assert determine_status(0.30, "PASS") == "FAIL"


def test_pass_fund_just_below_buffer_earns_fail() -> None:
    """Score 0.34 < 0.35 (watch - hysteresis) → FAIL even from PASS."""
    assert determine_status(0.34, "PASS") == "FAIL"


def test_pass_fund_at_buffer_boundary_stays_watchlist() -> None:
    """Score 0.36 (above watchlist - hysteresis ≈ 0.350…003) → WATCHLIST.

    Note: 0.40 - 0.05 = 0.35000000000000003 in IEEE 754, so exact 0.35
    falls just below the boundary for both PASS and WATCHLIST paths.
    Use 0.36 as the unambiguous inclusive-boundary test.
    """
    assert determine_status(0.36, "PASS") == "WATCHLIST"
    # Verify symmetry: WATCHLIST fund at 0.35 also gets FAIL (same float)
    assert determine_status(0.35, "PASS") == determine_status(0.35, "WATCHLIST")


# ── F09 regression: PASS stays PASS above demotion threshold ───────────


def test_pass_fund_above_demotion_threshold_stays_pass() -> None:
    """Score 0.55 (= pass - hysteresis boundary) → stays PASS."""
    # 0.55 < 0.55 is False → return "PASS"
    assert determine_status(0.55, "PASS") == "PASS"


def test_pass_fund_at_pass_threshold_stays_pass() -> None:
    """Score 0.60 → PASS."""
    assert determine_status(0.60, "PASS") == "PASS"


# ── First-screening / no-prior-status unchanged ────────────────────────


def test_first_screening_uses_raw_thresholds() -> None:
    """No previous status → raw threshold check, no hysteresis."""
    assert determine_status(0.65, None) == "PASS"
    assert determine_status(0.50, None) == "WATCHLIST"
    assert determine_status(0.30, None) == "FAIL"


def test_previous_fail_uses_raw_thresholds() -> None:
    """Previous FAIL → no hysteresis on re-entry."""
    assert determine_status(0.65, "FAIL") == "PASS"
    assert determine_status(0.50, "FAIL") == "WATCHLIST"
    assert determine_status(0.30, "FAIL") == "FAIL"


# ── score=None unchanged ──────────────────────────────────────────────


def test_score_none_returns_watchlist() -> None:
    """Insufficient data → WATCHLIST (Charter §3 default)."""
    assert determine_status(None, "PASS") == "WATCHLIST"
    assert determine_status(None, "WATCHLIST") == "WATCHLIST"
    assert determine_status(None, None) == "WATCHLIST"
