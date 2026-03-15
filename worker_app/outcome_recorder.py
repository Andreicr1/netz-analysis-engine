"""Outcome Recorder — deal conversion feedback for knowledge flywheel.

Triggered when a deal is converted from pipeline to portfolio
(stage transition).  Links outcome to previously aggregated signal
via ``anonymous_hash``.

Records:
  - anonymous_hash  → links to knowledge_aggregator signal
  - converted       → True/False
  - months_to_conversion → bucketed (0-3, 3-6, 6-12, 12+)
  - irr_bucket      → bucketed (<5%, 5-10%, 10-15%, 15%+)

Enables the engine to learn:
  - Which signal combinations correlated with successful conversions
  - Which INVEST recommendations did not convert (calibration signal)
  - Performance of the critic engine over time
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from worker_app.knowledge_aggregator import (
    _months_to_conversion_bucket,
    compute_anonymous_hash,
)

logger = logging.getLogger(__name__)


def _irr_bucket(irr: float | None) -> str:
    if irr is None:
        return "unknown"
    if irr < 0.05:
        return "<5%"
    if irr < 0.10:
        return "5-10%"
    if irr < 0.15:
        return "10-15%"
    return "15%+"


def build_outcome_record(
    *,
    org_id: UUID,
    deal_id: UUID,
    memo_id: UUID,
    converted: bool,
    months_to_conversion: float | None = None,
    irr: float | None = None,
) -> dict[str, Any]:
    """Build an anonymous outcome record for the knowledge pipeline.

    Parameters
    ----------
    org_id, deal_id, memo_id
        Used ONLY for the anonymous hash.  Not stored in output.
    converted
        Whether the deal was converted from pipeline to portfolio.
    months_to_conversion
        Time from IC memo to conversion (None if not converted).
    irr
        Internal Rate of Return if available.

    Returns
    -------
    dict
        Anonymous outcome record.
    """
    return {
        "anonymous_hash": compute_anonymous_hash(org_id, deal_id, memo_id),
        "timestamp": datetime.now(UTC).isoformat(),
        "converted": converted,
        "months_to_conversion": _months_to_conversion_bucket(months_to_conversion),
        "irr_bucket": _irr_bucket(irr),
    }


async def record_outcome(
    *,
    org_id: UUID,
    deal_id: UUID,
    memo_id: UUID,
    converted: bool,
    months_to_conversion: float | None = None,
    irr: float | None = None,
) -> str:
    """Record a deal outcome and write to storage.

    Returns the storage path written.
    """
    from app.services.storage_client import get_storage_client

    record = build_outcome_record(
        org_id=org_id,
        deal_id=deal_id,
        memo_id=memo_id,
        converted=converted,
        months_to_conversion=months_to_conversion,
        irr=irr,
    )

    storage = get_storage_client()
    anon_hash = record["anonymous_hash"]
    path = f"gold/_global/analysis_patterns/outcomes/{anon_hash[:8]}/{anon_hash}.json"

    await storage.write(
        path,
        json.dumps(record, indent=2).encode("utf-8"),
        content_type="application/json",
    )

    logger.info(
        "Recorded outcome converted=%s hash=%s…",
        converted,
        anon_hash[:12],
    )
    return path
