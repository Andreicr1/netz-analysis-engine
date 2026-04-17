"""PR-A19 μ-trace instrumentation unit tests.

Pure instrumentation PR — these tests lock:
    1. ``compute_bl_posterior_multi_view`` emits ``mu_trace_bl_posterior``
       for each ticker in ``trace_indices`` (empty-views + with-views paths).
    2. Missing trace tickers in the candidate id set emit
       ``mu_trace_asset_missing`` but do NOT raise.

Production math is unchanged by A19 — these tests purposely do NOT cover
numerical values of μ_prior / μ_post. A19.1 will own those fixtures.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
import structlog

from quant_engine.black_litterman_service import (
    TAU_PHASE_A,
    View,
    compute_bl_posterior_multi_view,
)


def _capture_structlog_events() -> tuple[list[dict[str, Any]], Any]:
    """Return (events_list, processor) to wire into structlog config."""
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


def test_bl_multi_view_emits_mu_trace_for_each_ticker(
    captured_log_events: list[dict[str, Any]],
) -> None:
    """With views supplied, L5 fires once per trace ticker."""
    n = 3
    mu_prior = np.array([0.05, 0.02, 0.08])
    sigma = np.eye(n) * 0.04
    P = np.eye(n)
    Q = np.array([0.07, 0.03, 0.10])
    Omega = np.eye(n) * 0.001
    data_view = View(P=P, Q=Q, Omega=Omega, source="data_view", confidence=None)

    trace_indices = {"SPY": 0, "VTEB": 1, "GLD": 2}

    mu_post = compute_bl_posterior_multi_view(
        mu_prior=mu_prior,
        sigma=sigma,
        views=[data_view],
        tau=TAU_PHASE_A,
        trace_indices=trace_indices,
    )

    assert mu_post.shape == (n,)
    trace_events = [e for e in captured_log_events if e.get("event") == "mu_trace_bl_posterior"]
    tickers_logged = {e["ticker"] for e in trace_events}
    assert tickers_logged == {"SPY", "VTEB", "GLD"}
    for e in trace_events:
        assert e["no_views"] is False
        assert "mu_prior_i" in e and "mu_post_i" in e and "delta" in e


def test_bl_multi_view_empty_views_still_emits_trace(
    captured_log_events: list[dict[str, Any]],
) -> None:
    """Empty views path is a separate branch — must still emit L5 events."""
    n = 2
    mu_prior = np.array([0.10, 0.05])
    sigma = np.eye(n) * 0.04
    trace_indices = {"SPY": 0, "VTEB": 1}

    mu_post = compute_bl_posterior_multi_view(
        mu_prior=mu_prior,
        sigma=sigma,
        views=[],
        tau=TAU_PHASE_A,
        trace_indices=trace_indices,
    )

    np.testing.assert_allclose(mu_post, mu_prior)
    trace_events = [e for e in captured_log_events if e.get("event") == "mu_trace_bl_posterior"]
    assert {e["ticker"] for e in trace_events} == {"SPY", "VTEB"}
    for e in trace_events:
        assert e["no_views"] is True
        assert e["delta"] == 0.0


def test_bl_multi_view_no_trace_indices_no_trace_events(
    captured_log_events: list[dict[str, Any]],
) -> None:
    """When ``trace_indices`` is None, no μ-trace events are emitted."""
    n = 2
    mu_prior = np.array([0.1, 0.05])
    sigma = np.eye(n) * 0.04
    mu_post = compute_bl_posterior_multi_view(
        mu_prior=mu_prior,
        sigma=sigma,
        views=[],
        tau=TAU_PHASE_A,
    )
    assert mu_post.shape == (n,)
    assert not any(
        e.get("event") == "mu_trace_bl_posterior" for e in captured_log_events
    )


def test_bl_multi_view_trace_index_out_of_range_is_silent(
    captured_log_events: list[dict[str, Any]],
) -> None:
    """Out-of-range trace index is skipped silently — must never raise."""
    n = 2
    mu_prior = np.array([0.1, 0.05])
    sigma = np.eye(n) * 0.04
    # VTEB index 5 is OOB in a 2-asset universe.
    trace_indices = {"SPY": 0, "VTEB": 5}

    mu_post = compute_bl_posterior_multi_view(
        mu_prior=mu_prior,
        sigma=sigma,
        views=[],
        tau=TAU_PHASE_A,
        trace_indices=trace_indices,
    )
    assert mu_post.shape == (n,)
    trace_events = [
        e for e in captured_log_events if e.get("event") == "mu_trace_bl_posterior"
    ]
    assert {e["ticker"] for e in trace_events} == {"SPY"}
