"""Peer Injection — bridge to peer_group engine for DD Report evidence.

Gathers peer group rankings and formats them as annotations for
the performance_analysis chapter.

This file is separate from quant_injection.py because it imports
PeerGroupService (a service entry-point), which the import-linter
contract forbids from quant_injection.py (a helper).
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.orm import Session

logger = structlog.get_logger()


def gather_peer_context(
    db: Session,
    *,
    instrument_id: str,
    organization_id: str,
) -> dict[str, Any]:
    """Gather peer group ranking context for performance_analysis chapter.

    Returns peer percentile annotations for key metrics.
    If peer group cannot be formed, returns empty dict (never fails the chapter).

    Parameters
    ----------
    db : Session
        Sync database session.
    instrument_id : str
        UUID of the instrument.
    organization_id : str
        Tenant organization ID.

    Returns
    -------
    dict
        Peer context with metric annotations and group metadata.
    """
    try:
        from vertical_engines.wealth.peer_group.models import PeerGroupNotFound
        from vertical_engines.wealth.peer_group.service import PeerGroupService

        svc = PeerGroupService()
        result = svc.compute_rankings(
            db,
            uuid.UUID(str(instrument_id)),
            organization_id,
        )

        if isinstance(result, PeerGroupNotFound):
            logger.debug(
                "peer_context_not_available",
                instrument_id=instrument_id,
                reason=result.reason,
            )
            return {}

        annotations: list[str] = []
        for r in result.rankings:
            if r.percentile is not None and r.value is not None:
                pctile_display = round(100.0 - r.percentile) if not r.lower_is_better else round(r.percentile)
                annotations.append(
                    f"{r.metric}: {r.value:.2f} "
                    f"(top {pctile_display}% of {result.peer_count} peers "
                    f"in {result.peer_group_key})"
                )

        return {
            "peer_group_key": result.peer_group_key,
            "peer_count": result.peer_count,
            "fallback_level": result.fallback_level,
            "composite_percentile": result.composite_percentile,
            "annotations": annotations,
        }

    except Exception:
        logger.exception(
            "peer_context_gather_failed",
            instrument_id=instrument_id,
        )
        return {}
