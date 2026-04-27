"""PR-Q49 — Wave 6 Session 05 Tier 4 cleanup regression tests.

Covers three independent low-severity fixes:
    F06: Legacy compute_bl_returns logs warning on unknown view types.
    F07: Monte Carlo migrated RandomState -> default_rng (Generator API).
    F12: He-Litterman consistency check uses tau-scaled covariance.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
import structlog

from quant_engine.black_litterman_service import compute_bl_returns
from quant_engine.monte_carlo_service import run_monte_carlo

# ── structlog capture (same pattern as test_mu_trace_instrumentation) ────


def _capture_structlog_events() -> tuple[list[dict[str, Any]], Any]:
    events: list[dict[str, Any]] = []

    def _capture(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        events.append(dict(event_dict))
        return event_dict

    return events, _capture


@pytest.fixture
def captured_log_events() -> list[dict[str, Any]]:
    events, processor = _capture_structlog_events()
    original = structlog.get_config()
    structlog.configure(
        processors=[processor, *original["processors"]],
        wrapper_class=original["wrapper_class"],
        context_class=original["context_class"],
        logger_factory=original["logger_factory"],
        cache_logger_on_first_use=False,
    )
    try:
        yield events
    finally:
        structlog.configure(**original)


# ── F06: legacy unknown view type warning ────────────────────────────────


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_legacy_unknown_view_type_logs_warning(
    captured_log_events: list[dict[str, Any]],
) -> None:
    """compute_bl_returns must log warning (not silently skip) on unknown
    view types."""
    sigma = np.eye(2) * 0.04
    w_mkt = np.array([0.5, 0.5])

    views = [
        {"type": "sector_tilt", "asset_idx": 0, "Q": 0.06, "confidence": 0.5},
        {"type": "absolute", "asset_idx": 0, "Q": 0.06, "confidence": 0.5},
    ]

    result = compute_bl_returns(sigma, w_mkt, views=views)

    # Function still returns a posterior (only the absolute view applied)
    assert result.shape == (2,)
    assert all(np.isfinite(result))

    # Warning must have been emitted for the sector_tilt skip
    skip_events = [
        e for e in captured_log_events
        if e.get("event") == "bl_legacy_unknown_view_type_skipped"
    ]
    assert len(skip_events) == 1
    assert skip_events[0]["view_type"] == "sector_tilt"
    assert skip_events[0]["view_index"] == 0


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_legacy_all_unknown_views_returns_equilibrium(
    captured_log_events: list[dict[str, Any]],
) -> None:
    """If all views are unknown types, result equals equilibrium (pi)."""
    sigma = np.eye(2) * 0.04
    w_mkt = np.array([0.5, 0.5])

    views = [
        {"type": "bogus", "Q": 0.10, "confidence": 0.5},
    ]

    result = compute_bl_returns(sigma, w_mkt, views=views)
    pi = 2.5 * sigma @ w_mkt
    np.testing.assert_allclose(result, pi, atol=1e-10)

    skip_events = [
        e for e in captured_log_events
        if e.get("event") == "bl_legacy_unknown_view_type_skipped"
    ]
    assert len(skip_events) == 1


# ── F07: MC uses default_rng (Generator), not RandomState ───────────────


def test_mc_seed_determinism_post_migration() -> None:
    """Same seed must produce identical MC results after RandomState ->
    default_rng migration."""
    rng = np.random.default_rng(42)
    daily = rng.normal(0.0005, 0.01, 300)

    r1 = run_monte_carlo(daily, horizons=[252], seed=42, n_simulations=200)
    r2 = run_monte_carlo(daily, horizons=[252], seed=42, n_simulations=200)

    assert r1.n_simulations > 0
    assert r2.n_simulations > 0
    assert r1.mean == r2.mean
    assert r1.std == r2.std
    assert r1.percentiles == r2.percentiles


def test_mc_different_seeds_differ() -> None:
    """Different seeds produce different results (sanity check)."""
    rng = np.random.default_rng(42)
    daily = rng.normal(0.0005, 0.01, 300)

    r1 = run_monte_carlo(daily, horizons=[252], seed=42, n_simulations=200)
    r2 = run_monte_carlo(daily, horizons=[252], seed=99, n_simulations=200)

    assert r1.n_simulations > 0
    assert r2.n_simulations > 0
    # Very unlikely to be identical with different seeds
    assert r1.mean != r2.mean


# ── F12: He-Litterman tau-scaled consistency check ───────────────────────


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_he_litterman_warning_fires_with_tau_scaled_variance(
    captured_log_events: list[dict[str, Any]],
) -> None:
    """With tau_eff scaling, a view 4 sigma from prior (under tau*Sigma)
    should trigger the He-Litterman warning.

    Pre-fix: warning used unscaled Sigma -> effective threshold was ~13.4 sigma
    -> view at 0.9 sigma (under Sigma) never fired.
    Post-fix: warning fires at documented 3 sigma threshold against tau*Sigma.

    Setup:
        sigma = diag(0.04, 0.04), tau_eff = 0.05
        pi = 2.5 * sigma @ [0.5, 0.5] = [0.05, 0.05]
        Under tau*Sigma: view_std = sqrt(0.05 * 0.04) = 0.04472
        View Q = 0.05 + 0.18 = 0.23 -> z = 0.18 / 0.04472 ~ 4.02 > 3.0
        Under plain Sigma (pre-fix): view_std = 0.2, z = 0.18/0.2 = 0.9 < 3.0
    """
    sigma = np.eye(2) * 0.04
    w_mkt = np.array([0.5, 0.5])
    tau_eff = 0.05

    # View 4 sigma away from prior under tau*Sigma
    views = [
        {"type": "absolute", "asset_idx": 0, "Q": 0.23, "confidence": 0.5},
    ]

    result = compute_bl_returns(sigma, w_mkt, views=views, tau=tau_eff)
    assert result.shape == (2,)

    inconsistent_events = [
        e for e in captured_log_events
        if e.get("event") == "black_litterman_view_inconsistent_with_prior"
    ]
    assert len(inconsistent_events) == 1
    assert inconsistent_events[0]["n_flagged"] == 1
    # z-score should be ~4.0 under tau*Sigma
    assert inconsistent_events[0]["max_z"] > 3.5


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_he_litterman_no_warning_for_mild_view(
    captured_log_events: list[dict[str, Any]],
) -> None:
    """A view within 2 sigma (under tau*Sigma) should NOT trigger the
    He-Litterman warning."""
    sigma = np.eye(2) * 0.04
    w_mkt = np.array([0.5, 0.5])
    tau_eff = 0.05

    # view_std under tau*Sigma = sqrt(0.05 * 0.04) = 0.04472
    # 2 sigma = 0.0894; Q = 0.05 + 0.08 = 0.13 -> z ~ 1.79 < 3.0
    views = [
        {"type": "absolute", "asset_idx": 0, "Q": 0.13, "confidence": 0.5},
    ]

    result = compute_bl_returns(sigma, w_mkt, views=views, tau=tau_eff)
    assert result.shape == (2,)

    inconsistent_events = [
        e for e in captured_log_events
        if e.get("event") == "black_litterman_view_inconsistent_with_prior"
    ]
    assert len(inconsistent_events) == 0
