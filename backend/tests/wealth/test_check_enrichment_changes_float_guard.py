"""Regression tests for S08-F07 — check_enrichment_changes non-numeric guard."""

from __future__ import annotations

import uuid

from vertical_engines.wealth.watchlist.service import WatchlistService


def test_non_numeric_curr_expense_ratio_skipped_no_crash() -> None:
    """curr_er = 'N/A' -> skip the fee delta check, no crash, no false alert."""
    inst_id = uuid.uuid4()
    instruments = [{
        "instrument_id": inst_id,
        "name": "Test Fund",
        "attributes": {"expense_ratio_pct": "N/A"},
    }]
    previous = {inst_id: {"expense_ratio_pct": "0.005"}}
    alerts = WatchlistService.check_enrichment_changes(instruments, previous)
    # No crash; no fee alert (skipped). Strategy_label unchanged -> no alert either.
    assert len(alerts) == 0


def test_non_numeric_prev_expense_ratio_skipped() -> None:
    """prev_er non-numeric -> skip."""
    inst_id = uuid.uuid4()
    instruments = [{
        "instrument_id": inst_id,
        "name": "Test Fund",
        "attributes": {"expense_ratio_pct": "0.006"},
    }]
    previous = {inst_id: {"expense_ratio_pct": ""}}
    alerts = WatchlistService.check_enrichment_changes(instruments, previous)
    assert len(alerts) == 0


def test_strategy_label_change_still_detected_when_fee_skipped() -> None:
    """Even if expense_ratio is non-numeric (skipped), strategy_label change still alerts."""
    inst_id = uuid.uuid4()
    instruments = [{
        "instrument_id": inst_id,
        "name": "Test Fund",
        "attributes": {"expense_ratio_pct": "N/A", "strategy_label": "Long/Short Equity"},
    }]
    previous = {inst_id: {"expense_ratio_pct": "0.005", "strategy_label": "Multi-Strategy"}}
    alerts = WatchlistService.check_enrichment_changes(instruments, previous)
    # Fee skipped; strategy alert fires.
    assert len(alerts) == 1
    assert alerts[0].direction == "enrichment_change"
    assert "Strategy label" in alerts[0].message


def test_valid_numeric_fee_increase_unchanged() -> None:
    """Regression guard: valid numeric input still triggers fee alert when delta > 5bps."""
    inst_id = uuid.uuid4()
    instruments = [{
        "instrument_id": inst_id,
        "name": "Test Fund",
        "attributes": {"expense_ratio_pct": 0.012},  # 1.2%
    }]
    previous = {inst_id: {"expense_ratio_pct": 0.005}}  # 0.5%
    alerts = WatchlistService.check_enrichment_changes(instruments, previous)
    # 0.012 - 0.005 = 0.007 > 0.0005 -> alert
    assert len(alerts) == 1
    assert "increased" in alerts[0].message.lower()
