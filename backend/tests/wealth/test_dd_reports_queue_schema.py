"""Tests for the DDReportsQueueOut aggregator schema.

Phase 2 Session C commit 5 — locks in the wire contract of the
``GET /dd-reports/queue`` endpoint.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.domains.wealth.schemas.dd_report import (
    DDReportQueueItem,
    DDReportsQueueOut,
)


def _item(*, status: str, decision: str | None = None) -> DDReportQueueItem:
    return DDReportQueueItem(
        id=uuid.uuid4(),
        instrument_id=uuid.uuid4(),
        instrument_label=f"Fund {status}",
        report_type="dd_report",
        version=1,
        status=status,
        confidence_score=Decimal("0.82"),
        decision_anchor=decision,
        created_at=datetime(2026, 4, 11, 10, 0, 0, tzinfo=timezone.utc),
        approved_at=None,
        progress_pct=None,
        current_chapter=None,
    )


def test_queue_out_round_trip_and_counts() -> None:
    pending = [_item(status="draft")]
    in_progress = [_item(status="generating"), _item(status="pending_approval")]
    completed = [
        _item(status="approved", decision="approve"),
        _item(status="rejected", decision="reject"),
        _item(status="failed"),
    ]
    queue = DDReportsQueueOut(
        pending=pending,
        in_progress=in_progress,
        completed_recent=completed,
        counts={
            "pending": len(pending),
            "in_progress": len(in_progress),
            "completed_recent": len(completed),
        },
    )
    payload = queue.model_dump()
    assert payload["counts"]["pending"] == 1
    assert payload["counts"]["in_progress"] == 2
    assert payload["counts"]["completed_recent"] == 3
    assert len(payload["pending"]) == 1
    assert payload["in_progress"][0]["status"] == "generating"
    assert payload["completed_recent"][2]["status"] == "failed"


def test_queue_out_empty_state_has_counts_of_zero() -> None:
    queue = DDReportsQueueOut(
        pending=[],
        in_progress=[],
        completed_recent=[],
        counts={"pending": 0, "in_progress": 0, "completed_recent": 0},
    )
    assert queue.counts == {"pending": 0, "in_progress": 0, "completed_recent": 0}
    assert queue.pending == []


def test_queue_item_allows_optional_fields() -> None:
    item = DDReportQueueItem(
        id=uuid.uuid4(),
        instrument_id=uuid.uuid4(),
        instrument_label=None,
        report_type="dd_report",
        version=2,
        status="draft",
        confidence_score=None,
        decision_anchor=None,
        created_at=datetime.now(tz=timezone.utc),
        approved_at=None,
    )
    assert item.progress_pct is None
    assert item.current_chapter is None
    assert item.instrument_label is None
