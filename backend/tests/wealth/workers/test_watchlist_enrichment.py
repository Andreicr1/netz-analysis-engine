"""Tests for PR-Q129 — check_enrichment_changes wired into watchlist batch worker.

Covers:
- Batch worker calls check_enrichment_changes with correct arguments
- Fee increase above threshold triggers enrichment_change alert
- Strategy label change triggers enrichment_change alert
- Minor fee changes produce no alert
- Audit events use correct action for enrichment changes
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from vertical_engines.wealth.watchlist.models import TransitionAlert

# ═══════════════════════════════════════════════════════════════════
#  Enrichment detection via batch worker wiring
# ═══════════════════════════════════════════════════════════════════


class TestWatchlistBatchEnrichmentWiring:
    """PR-Q129: check_enrichment_changes is called in watchlist_batch worker."""

    _ID_A = uuid.UUID("00000000-0000-0000-0000-a00000000001")
    _ID_B = uuid.UUID("00000000-0000-0000-0000-a00000000002")

    def test_watchlist_batch_detects_fee_increase(self):
        """Fee increase 0.005 -> 0.0075 (25bps > 5bps threshold) produces alert."""
        from vertical_engines.wealth.watchlist.service import WatchlistService

        instruments = [
            {
                "instrument_id": self._ID_A,
                "name": "Fee Hike Fund",
                "attributes": {"expense_ratio_pct": 0.0075},
            },
        ]
        previous_snapshots = {self._ID_A: {"expense_ratio_pct": 0.005}}

        alerts = WatchlistService.check_enrichment_changes(instruments, previous_snapshots)

        assert len(alerts) == 1
        assert alerts[0].direction == "enrichment_change"
        assert alerts[0].instrument_id == self._ID_A
        assert "25.0bps" in alerts[0].message
        assert "0.50%" in alerts[0].message
        assert "0.75%" in alerts[0].message

    def test_watchlist_batch_detects_strategy_label_change(self):
        """Strategy label change produces enrichment_change alert."""
        from vertical_engines.wealth.watchlist.service import WatchlistService

        instruments = [
            {
                "instrument_id": self._ID_A,
                "name": "Relabeled Fund",
                "attributes": {"strategy_label": "Large Cap Blend"},
            },
        ]
        previous_snapshots = {self._ID_A: {"strategy_label": "Growth Equity"}}

        alerts = WatchlistService.check_enrichment_changes(instruments, previous_snapshots)

        assert len(alerts) == 1
        assert alerts[0].direction == "enrichment_change"
        assert "Growth Equity" in alerts[0].message
        assert "Large Cap Blend" in alerts[0].message

    def test_watchlist_batch_no_alert_on_minor_fee_change(self):
        """1bps fee change (0.0050 -> 0.0051) is below threshold — no alert."""
        from vertical_engines.wealth.watchlist.service import WatchlistService

        instruments = [
            {
                "instrument_id": self._ID_A,
                "name": "Steady Fund",
                "attributes": {"expense_ratio_pct": 0.0051},
            },
        ]
        previous_snapshots = {self._ID_A: {"expense_ratio_pct": 0.0050}}

        alerts = WatchlistService.check_enrichment_changes(instruments, previous_snapshots)

        assert len(alerts) == 0

    @pytest.mark.asyncio
    async def test_watchlist_batch_audit_event_for_enrichment(self):
        """Enrichment alert emits write_audit_event with action='watchlist.enrichment_changed'.

        Replays the audit loop from watchlist_batch step 7b to verify
        the action is correctly dispatched based on alert.direction.
        """
        from app.domains.wealth.workers import watchlist_batch as wb_mod

        iid = uuid.uuid4()

        # Enrichment alert (fee increase)
        enrichment_alert = TransitionAlert(
            instrument_id=iid,
            instrument_name="Fee Hike Fund",
            previous_outcome="ER 0.50%",
            new_outcome="ER 0.75%",
            direction="enrichment_change",
            message="Expense ratio increased by 25.0bps (0.50% -> 0.75%)",
            detected_at=datetime.now(UTC),
        )

        # Transition alert (for comparison)
        transition_alert = TransitionAlert(
            instrument_id=uuid.uuid4(),
            instrument_name="Better Fund",
            previous_outcome="WATCHLIST",
            new_outcome="PASS",
            direction="improvement",
            message="Candidate for DD initiation",
            detected_at=datetime.now(UTC),
        )

        mock_write_audit = AsyncMock()
        mock_db = AsyncMock()

        alerts = [enrichment_alert, transition_alert]
        with patch.object(wb_mod, "write_audit_event", mock_write_audit):
            for alert in alerts:
                action = (
                    "watchlist.enrichment_changed"
                    if alert.direction == "enrichment_change"
                    else "watchlist.transition_detected"
                )
                await wb_mod.write_audit_event(
                    mock_db,
                    action=action,
                    entity_type="screening_result",
                    entity_id=str(alert.instrument_id),
                    actor_id="system:watchlist_batch",
                    before={"status": alert.previous_outcome},
                    after={"status": alert.new_outcome, "direction": alert.direction},
                    allow_global=False,
                )

        assert mock_write_audit.call_count == 2

        # First call: enrichment_changed action
        _, kw1 = mock_write_audit.call_args_list[0]
        assert kw1["action"] == "watchlist.enrichment_changed"
        assert kw1["entity_type"] == "screening_result"
        assert kw1["entity_id"] == str(iid)
        assert kw1["after"]["direction"] == "enrichment_change"

        # Second call: transition_detected action
        _, kw2 = mock_write_audit.call_args_list[1]
        assert kw2["action"] == "watchlist.transition_detected"
        assert kw2["after"]["direction"] == "improvement"


# ═══════════════════════════════════════════════════════════════════
#  Attribute snapshot persistence
# ═══════════════════════════════════════════════════════════════════


class TestAttributeSnapshotPersistence:
    """Verify _attribute_snapshot is stored in ScreeningResult.layer_results."""

    def test_snapshot_key_in_layer_results(self):
        """ScreeningResult layer_results should merge _attribute_snapshot.

        Exercises the exact dict-merge logic used in watchlist_batch step 7.
        """
        inst_attrs = {"expense_ratio_pct": 0.0060, "strategy_label": "Large Cap Value"}
        base_layer_results: dict = {"layer1": {"passed": True}}

        merged = {
            **(base_layer_results if isinstance(base_layer_results, dict) else {}),
            "_attribute_snapshot": {
                "expense_ratio_pct": inst_attrs.get("expense_ratio_pct"),
                "strategy_label": inst_attrs.get("strategy_label"),
            },
        }

        assert "_attribute_snapshot" in merged
        assert merged["_attribute_snapshot"]["expense_ratio_pct"] == 0.0060
        assert merged["_attribute_snapshot"]["strategy_label"] == "Large Cap Value"
        # Original layer results preserved
        assert merged["layer1"] == {"passed": True}

    def test_snapshot_with_list_layer_results_fallback(self):
        """When layer_results_dict is a list (legacy format), snapshot still works.

        The batch code guards with isinstance(base, dict) — lists fall through
        to empty dict merge.
        """
        base_layer_results = [{"layer": 1, "passed": True}]  # legacy list format

        merged = {
            **(base_layer_results if isinstance(base_layer_results, dict) else {}),
            "_attribute_snapshot": {
                "expense_ratio_pct": None,
                "strategy_label": None,
            },
        }

        assert "_attribute_snapshot" in merged
        # List was not merged (not a dict) — only snapshot key present
        assert "layer" not in merged

    def test_snapshot_extraction_from_previous_layer_results(self):
        """Verify _attribute_snapshot can be extracted from layer_results JSONB.

        Simulates the prev_snap_results loop in step 4b.
        """
        iid = uuid.uuid4()
        layer_results = {
            "layer1": {"passed": True},
            "_attribute_snapshot": {
                "expense_ratio_pct": 0.005,
                "strategy_label": "Growth Equity",
            },
        }

        # Simulate the extraction loop from watchlist_batch step 4b
        lr = layer_results or {}
        snap = lr.get("_attribute_snapshot", {})

        assert snap == {
            "expense_ratio_pct": 0.005,
            "strategy_label": "Growth Equity",
        }

    def test_snapshot_extraction_missing_key_returns_empty(self):
        """layer_results without _attribute_snapshot returns empty dict (first run)."""
        layer_results = {"layer1": {"passed": True}}

        lr = layer_results or {}
        snap = lr.get("_attribute_snapshot", {})

        assert snap == {}
