"""Intelligence status management and data persistence.

Implements _set_intelligence_status(), _write_research_output(),
and _write_derived_fields().
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = structlog.get_logger()


def _set_intelligence_status(
    db: Session,
    deal_id: uuid.UUID,
    status: str,
    *,
    generated_at: datetime | None = None,
    auto_commit: bool = True,
) -> None:
    """Update intelligence_status (optionally intelligence_generated_at)."""
    if generated_at:
        db.execute(
            text(
                "UPDATE pipeline_deals "
                "SET intelligence_status = CAST(:status AS intelligence_status_enum), "
                "intelligence_generated_at = :ts "
                "WHERE id = :id",
            ),
            {"status": status, "ts": generated_at, "id": str(deal_id)},
        )
    else:
        db.execute(
            text(
                "UPDATE pipeline_deals "
                "SET intelligence_status = CAST(:status AS intelligence_status_enum) WHERE id = :id",
            ),
            {"status": status, "id": str(deal_id)},
        )
    if auto_commit:
        db.commit()


def _write_research_output(
    db: Session,
    deal_id: uuid.UUID,
    data: dict[str, Any],
    *,
    auto_commit: bool = True,
) -> None:
    """Write structured intelligence to pipeline_deals.research_output."""
    db.execute(
        text(
            "UPDATE pipeline_deals "
            "SET research_output = :data WHERE id = :id",
        ),
        {"data": json.dumps(data, default=str), "id": str(deal_id)},
    )
    if auto_commit:
        db.commit()


def _write_derived_fields(
    db: Session,
    *,
    deal_id: uuid.UUID,
    fund_id: uuid.UUID,
    output: dict[str, Any],
) -> None:
    """Extract summary/risk/terms and write via update_deal_ai_output().

    IMPORTANT — Authority boundary (Unified Underwriting Patch):
    The Pipeline Engine is a SCREENING layer only.  It must NOT write
    an authoritative IC recommendation.  The ``summary`` field is set
    to a neutral screening-complete message.  Final recommendation,
    risk band, confidence, and IC readiness are determined exclusively
    by Deep Review V4 and persisted in ``deal_underwriting_artifacts``.
    """
    from app.domains.credit.modules.deals.deal_intelligence_repo import update_deal_ai_output

    # ── Screening-only summary — NO recommendation authority ──────
    summary = "Screening analysis completed — pending Deep Review."

    risk_map = output.get("risk_map", {})
    if isinstance(risk_map, dict):
        risk_flags = risk_map.get("key_risks", [])
    elif isinstance(risk_map, list):
        risk_flags = risk_map
    else:
        risk_flags = []

    terms = output.get("terms_and_covenants", {})
    key_terms = {
        "covenants": (
            terms.get("financial_covenants", [])
            if isinstance(terms, dict) else []
        ),
        "security_package": (
            terms.get("security_package", "")
            if isinstance(terms, dict) else ""
        ),
        "fees": (
            terms.get("fees", "")
            if isinstance(terms, dict) else ""
        ),
        "key_clauses": (
            terms.get("key_clauses", [])
            if isinstance(terms, dict) else []
        ),
        "red_flags": (
            risk_map.get("red_flags", [])
            if isinstance(risk_map, dict) else []
        ),
        "downside_scenarios": (
            risk_map.get("downside_scenarios", [])
            if isinstance(risk_map, dict) else []
        ),
        "mitigants": (
            risk_map.get("mitigants", [])
            if isinstance(risk_map, dict) else []
        ),
    }

    update_deal_ai_output(
        db,
        deal_id=deal_id,
        fund_id=fund_id,
        summary=summary,
        risk_flags=risk_flags,
        key_terms=key_terms,
    )
    logger.debug("derived_fields_written", deal_id=str(deal_id))
