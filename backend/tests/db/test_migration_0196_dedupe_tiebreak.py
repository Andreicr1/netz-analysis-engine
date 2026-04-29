"""PR-Q128 hotfix #2: migration 0196 dedupe DELETE tiebreak.

Validates that the DELETE ... USING pattern in 0196 correctly deduplicates
pending rebalance_events even when multiple duplicates share the exact
same created_at timestamp.  The tiebreak uses event_id (UUID, lexicographic)
so that exactly one row -- the one with the largest (latest ts, then largest
UUID) -- survives.

This is a pure-logic test that simulates the SQL predicate in Python,
avoiding the need for a live database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import NamedTuple

import pytest


class _Row(NamedTuple):
    """Minimal representation of a pending rebalance_events row."""

    event_id: uuid.UUID
    organization_id: uuid.UUID
    profile: str
    event_type: str
    status: str
    created_at: datetime


def _apply_dedupe_delete(rows: list[_Row]) -> list[_Row]:
    """Simulate the migration 0196 DELETE ... USING predicate.

    For each pair (re_old, re_new) that matches the WHERE clause,
    re_old is marked for deletion.  Returns the surviving rows.

    The predicate (from the fixed migration):
        re_old.organization_id = re_new.organization_id
        AND re_old.profile = re_new.profile
        AND re_old.event_type = re_new.event_type
        AND re_old.status = 'pending'
        AND re_new.status = 'pending'
        AND re_old.event_id != re_new.event_id
        AND (
            re_old.created_at < re_new.created_at
            OR (
                re_old.created_at = re_new.created_at
                AND re_old.event_id < re_new.event_id
            )
        )
    """
    deleted_ids: set[uuid.UUID] = set()

    for re_old in rows:
        for re_new in rows:
            if (
                re_old.organization_id == re_new.organization_id
                and re_old.profile == re_new.profile
                and re_old.event_type == re_new.event_type
                and re_old.status == "pending"
                and re_new.status == "pending"
                and re_old.event_id != re_new.event_id
                and (
                    re_old.created_at < re_new.created_at
                    or (
                        re_old.created_at == re_new.created_at
                        and str(re_old.event_id) < str(re_new.event_id)
                    )
                )
            ):
                deleted_ids.add(re_old.event_id)

    return [r for r in rows if r.event_id not in deleted_ids]


# -- Test: tied timestamps ---------------------------------------------


def test_migration_handles_tied_timestamps():
    """3 duplicates with the SAME created_at -> exactly 1 survives (largest event_id)."""
    org_id = uuid.uuid4()
    ts = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)

    # Create 3 UUIDs and sort them so we know which is largest
    ids = sorted([uuid.uuid4() for _ in range(3)], key=str)
    smallest_id, middle_id, largest_id = ids

    rows = [
        _Row(smallest_id, org_id, "conservative", "drift_rebalance", "pending", ts),
        _Row(middle_id, org_id, "conservative", "drift_rebalance", "pending", ts),
        _Row(largest_id, org_id, "conservative", "drift_rebalance", "pending", ts),
    ]

    survivors = _apply_dedupe_delete(rows)

    assert len(survivors) == 1, (
        f"Expected exactly 1 survivor from 3 tied-timestamp duplicates, got {len(survivors)}"
    )
    assert survivors[0].event_id == largest_id, (
        f"Survivor should be largest event_id {largest_id}, got {survivors[0].event_id}"
    )


# -- Test: different timestamps still work ------------------------------


def test_migration_handles_different_timestamps():
    """3 duplicates with DIFFERENT created_at -> latest survives."""
    org_id = uuid.uuid4()
    ts1 = datetime(2026, 4, 29, 10, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 4, 29, 11, 0, 0, tzinfo=timezone.utc)
    ts3 = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)

    id1, id2, id3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    rows = [
        _Row(id1, org_id, "moderate", "drift_rebalance", "pending", ts1),
        _Row(id2, org_id, "moderate", "drift_rebalance", "pending", ts2),
        _Row(id3, org_id, "moderate", "drift_rebalance", "pending", ts3),
    ]

    survivors = _apply_dedupe_delete(rows)

    assert len(survivors) == 1
    assert survivors[0].event_id == id3, "Latest timestamp should survive"


# -- Test: mixed tied and different timestamps --------------------------


def test_migration_handles_mixed_tied_and_different():
    """2 rows tied at latest ts + 1 earlier -> tied pair resolves by event_id."""
    org_id = uuid.uuid4()
    ts_early = datetime(2026, 4, 29, 10, 0, 0, tzinfo=timezone.utc)
    ts_late = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)

    ids = sorted([uuid.uuid4() for _ in range(2)], key=str)
    smaller_id, larger_id = ids
    early_id = uuid.uuid4()

    rows = [
        _Row(early_id, org_id, "growth", "drift_rebalance", "pending", ts_early),
        _Row(smaller_id, org_id, "growth", "drift_rebalance", "pending", ts_late),
        _Row(larger_id, org_id, "growth", "drift_rebalance", "pending", ts_late),
    ]

    survivors = _apply_dedupe_delete(rows)

    assert len(survivors) == 1
    assert survivors[0].event_id == larger_id, (
        "Among tied latest-timestamp rows, largest event_id should survive"
    )


# -- Test: non-pending rows are untouched ------------------------------


def test_migration_does_not_delete_non_pending():
    """Non-pending rows must survive regardless of duplicates."""
    org_id = uuid.uuid4()
    ts = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)

    pending_id = uuid.uuid4()
    completed_id = uuid.uuid4()

    rows = [
        _Row(pending_id, org_id, "conservative", "drift_rebalance", "pending", ts),
        _Row(completed_id, org_id, "conservative", "drift_rebalance", "completed", ts),
    ]

    survivors = _apply_dedupe_delete(rows)

    assert len(survivors) == 2, "Non-pending row must not be deleted"
    survivor_ids = {r.event_id for r in survivors}
    assert pending_id in survivor_ids
    assert completed_id in survivor_ids


# -- Test: different profiles are independent ---------------------------


def test_migration_treats_profiles_independently():
    """Duplicates in profile A must not affect profile B."""
    org_id = uuid.uuid4()
    ts = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)

    ids_a = sorted([uuid.uuid4() for _ in range(2)], key=str)
    ids_b = sorted([uuid.uuid4() for _ in range(2)], key=str)

    rows = [
        _Row(ids_a[0], org_id, "conservative", "drift_rebalance", "pending", ts),
        _Row(ids_a[1], org_id, "conservative", "drift_rebalance", "pending", ts),
        _Row(ids_b[0], org_id, "moderate", "drift_rebalance", "pending", ts),
        _Row(ids_b[1], org_id, "moderate", "drift_rebalance", "pending", ts),
    ]

    survivors = _apply_dedupe_delete(rows)

    assert len(survivors) == 2, "One survivor per profile"
    survivor_profiles = {r.profile for r in survivors}
    assert survivor_profiles == {"conservative", "moderate"}
    # Each survivor is the largest event_id in its profile group
    for r in survivors:
        if r.profile == "conservative":
            assert r.event_id == ids_a[1]
        else:
            assert r.event_id == ids_b[1]
