"""Placeholder tests for Discovery Analysis holdings endpoints (Task 6.1).

These tests require seeded production data (sec_nport_holdings, sec_13f_holdings,
sec_managers) plus the ``dev_headers`` and ``sample_nport_fund_id`` fixtures
which do not yet exist in the test harness. Skipped for now; enable once
integration fixtures land.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason="requires seeded prod data + dev_headers/sample_nport_fund_id fixtures",
)


def test_analysis_holdings_top_returns_positions() -> None:
    # GET /wealth/discovery/funds/{external_id}/analysis/holdings/top
    # Expect: {top_holdings: [...], sector_breakdown: [...], as_of: date,
    #          disclosure: {has_holdings: True}, fund: {...}}
    pass


def test_analysis_holdings_style_drift_returns_snapshots() -> None:
    # GET /wealth/discovery/funds/{external_id}/analysis/holdings/style-drift?quarters=8
    # Expect: {snapshots: [{quarter, sectors: [{name, weight}]}, ...]}
    pass


def test_analysis_reverse_lookup_returns_network() -> None:
    # GET /wealth/discovery/holdings/{cusip}/reverse-lookup?limit=30
    # Expect: {nodes: [target + holders], edges: [holder->target], target_cusip}
    pass
