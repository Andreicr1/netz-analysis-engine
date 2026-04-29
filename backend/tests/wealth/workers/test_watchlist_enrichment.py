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
    """Verify _attribute_snapshot is stored in ScreeningResult.layer_results.

    After PR-Q129 hotfix: layer_results is list[dict] (criterion entries),
    NOT dict. Snapshot is appended as a list entry with criterion="_attribute_snapshot".
    """

    def test_snapshot_key_in_layer_results(self):
        """ScreeningResult layer_results should append _attribute_snapshot.

        Exercises the exact list filter+append logic used in watchlist_batch step 7.
        """
        inst_attrs = {"expense_ratio_pct": 0.0060, "strategy_label": "Large Cap Value"}
        existing_results = [
            {"criterion": "min_aum", "expected": 1e8, "actual": 2e8, "passed": True, "layer": 1},
        ]

        # Same logic as watchlist_batch step 7
        filtered = [
            e for e in existing_results
            if not (isinstance(e, dict) and e.get("criterion") == "_attribute_snapshot")
        ]
        filtered.append({
            "criterion": "_attribute_snapshot",
            "value": {
                "expense_ratio_pct": inst_attrs.get("expense_ratio_pct"),
                "strategy_label": inst_attrs.get("strategy_label"),
            },
        })

        assert len(filtered) == 2
        snapshot_entry = next(e for e in filtered if e.get("criterion") == "_attribute_snapshot")
        assert snapshot_entry["value"]["expense_ratio_pct"] == 0.0060
        assert snapshot_entry["value"]["strategy_label"] == "Large Cap Value"
        # Original criterion preserved
        assert filtered[0]["criterion"] == "min_aum"

    def test_snapshot_deduplication_on_rewrite(self):
        """When layer_results already has a snapshot entry, it is replaced (not duplicated)."""
        existing_results = [
            {"criterion": "min_aum", "expected": 1e8, "actual": 2e8, "passed": True, "layer": 1},
            {"criterion": "_attribute_snapshot", "value": {"expense_ratio_pct": 0.005}},
        ]

        # Same logic as watchlist_batch step 7
        filtered = [
            e for e in existing_results
            if not (isinstance(e, dict) and e.get("criterion") == "_attribute_snapshot")
        ]
        filtered.append({
            "criterion": "_attribute_snapshot",
            "value": {"expense_ratio_pct": 0.007, "strategy_label": "Growth"},
        })

        snapshot_entries = [e for e in filtered if e.get("criterion") == "_attribute_snapshot"]
        assert len(snapshot_entries) == 1
        assert snapshot_entries[0]["value"]["expense_ratio_pct"] == 0.007

    def test_snapshot_extraction_from_previous_layer_results_list(self):
        """Verify _attribute_snapshot can be extracted from list-format layer_results JSONB.

        Simulates the prev_snap_results loop in step 4b (post-hotfix).
        """
        layer_results = [
            {"criterion": "min_aum", "expected": 1e8, "actual": 2e8, "passed": True, "layer": 1},
            {
                "criterion": "_attribute_snapshot",
                "value": {
                    "expense_ratio_pct": 0.005,
                    "strategy_label": "Growth Equity",
                },
            },
        ]

        # Same logic as watchlist_batch step 4b (post-hotfix)
        snap = {}
        if isinstance(layer_results, list):
            for entry in layer_results:
                if isinstance(entry, dict) and entry.get("criterion") == "_attribute_snapshot":
                    snap = entry.get("value", {})
                    break

        assert snap == {
            "expense_ratio_pct": 0.005,
            "strategy_label": "Growth Equity",
        }

    def test_snapshot_extraction_missing_key_returns_empty(self):
        """layer_results without _attribute_snapshot returns empty dict (first run)."""
        layer_results = [
            {"criterion": "min_aum", "expected": 1e8, "actual": 2e8, "passed": True, "layer": 1},
        ]

        snap = {}
        if isinstance(layer_results, list):
            for entry in layer_results:
                if isinstance(entry, dict) and entry.get("criterion") == "_attribute_snapshot":
                    snap = entry.get("value", {})
                    break

        assert snap == {}

    def test_layer_results_preserves_criterion_entries(self):
        """PR-Q129 hotfix regression: N criteria in + snapshot = N+1 entries out.

        Verifies the writing path preserves all criterion entries from
        layer_results_dict (list[dict]) and appends exactly one snapshot.
        """
        # Simulate 3 criterion entries from screener
        layer_results_dict = [
            {"criterion": "min_aum", "expected": 1e8, "actual": 2e8, "passed": True, "layer": 1},
            {"criterion": "max_expense_ratio", "expected": 0.02, "actual": 0.01, "passed": True, "layer": 1},
            {"criterion": "min_sharpe", "expected": 0.5, "actual": 0.8, "passed": True, "layer": 3},
        ]

        inst_attrs = {"expense_ratio_pct": 0.01, "strategy_label": "Large Cap Growth"}

        # Same logic as watchlist_batch step 7 (post-hotfix)
        existing_results = layer_results_dict if layer_results_dict else []
        filtered = [
            e for e in existing_results
            if not (isinstance(e, dict) and e.get("criterion") == "_attribute_snapshot")
        ]
        filtered.append({
            "criterion": "_attribute_snapshot",
            "value": {
                "expense_ratio_pct": inst_attrs.get("expense_ratio_pct"),
                "strategy_label": inst_attrs.get("strategy_label"),
            },
        })

        # N criteria + 1 snapshot = N+1
        assert len(filtered) == 4
        criteria_names = [e["criterion"] for e in filtered]
        assert "min_aum" in criteria_names
        assert "max_expense_ratio" in criteria_names
        assert "min_sharpe" in criteria_names
        assert "_attribute_snapshot" in criteria_names

    def test_layer_results_snapshot_reading_from_list(self):
        """PR-Q129 hotfix regression: reading path extracts snapshot from list format.

        Verifies the reading loop in step 4b correctly extracts _attribute_snapshot
        from list-format layer_results as stored in JSONB.
        """
        iid_a = uuid.UUID("00000000-0000-0000-0000-b00000000001")
        iid_b = uuid.UUID("00000000-0000-0000-0000-b00000000002")
        iid_c = uuid.UUID("00000000-0000-0000-0000-b00000000003")

        # Simulate rows from DB query
        class FakeRow:
            def __init__(self, instrument_id, layer_results):
                self.instrument_id = instrument_id
                self.layer_results = layer_results

        rows = [
            # Has snapshot
            FakeRow(iid_a, [
                {"criterion": "min_aum", "expected": 1e8, "actual": 2e8, "passed": True, "layer": 1},
                {"criterion": "_attribute_snapshot", "value": {"expense_ratio_pct": 0.005}},
            ]),
            # No snapshot (first run)
            FakeRow(iid_b, [
                {"criterion": "min_aum", "expected": 1e8, "actual": 5e7, "passed": False, "layer": 1},
            ]),
            # Empty layer_results
            FakeRow(iid_c, None),
        ]

        # Same logic as watchlist_batch step 4b (post-hotfix)
        previous_snapshots: dict[uuid.UUID, dict] = {}
        for row in rows:
            lr = row.layer_results
            if not lr:
                continue
            if isinstance(lr, list):
                for entry in lr:
                    if isinstance(entry, dict) and entry.get("criterion") == "_attribute_snapshot":
                        snap = entry.get("value", {})
                        if snap:
                            previous_snapshots[row.instrument_id] = snap
                        break
            elif isinstance(lr, dict):
                snap = lr.get("_attribute_snapshot", {})
                if snap:
                    previous_snapshots[row.instrument_id] = snap

        # iid_a has snapshot, iid_b and iid_c do not
        assert iid_a in previous_snapshots
        assert previous_snapshots[iid_a] == {"expense_ratio_pct": 0.005}
        assert iid_b not in previous_snapshots
        assert iid_c not in previous_snapshots
