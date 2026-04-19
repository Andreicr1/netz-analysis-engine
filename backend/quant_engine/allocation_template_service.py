"""PR-A25 — Template Completeness Validator.

Pre-run check that hard-fails portfolio construction when a
``(organization_id, profile)`` pair is missing any canonical
``allocation_blocks`` row. The 18 canonical blocks define the
institutional template every profile must share — profiles differ on
risk (CVaR limit + per-block bands), not on asset-class universe.

Called BEFORE :func:`validate_block_coverage` inside
``construction_run_executor`` so the stricter "template incomplete"
failure short-circuits the cascade before the coverage gate's
per-block candidate count check runs.

Design principles
-----------------
* **Structural, not quantitative.** This validator does NOT inspect
  ``target_weight``. The coverage validator owns weight-level checks;
  this one only answers "does this profile carry every canonical block
  row?". Missing rows should be impossible post-migration 0153 — their
  presence indicates the trigger failed or an admin bypassed it.
* **Informational extras.** Non-canonical blocks (historical drift)
  are reported but do not fail the validator — the rename path in
  0153 preserves history for auditability.
* Pure read-only — never writes. Uses the RLS-aware session passed by
  the caller.
"""
from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class TemplateGap(BaseModel):
    """One entry per missing canonical block in the report."""

    block_id: str


class TemplateReport(BaseModel):
    """Template completeness status for one ``(org, profile)`` pair."""

    organization_id: uuid.UUID
    profile: str
    is_complete: bool
    missing_canonical_blocks: list[str] = Field(default_factory=list)
    # Informational: non-canonical blocks present in the allocation (e.g.
    # historical aliases kept for audit). Does NOT fail the validator.
    extra_non_canonical_blocks: list[str] = Field(default_factory=list)


_MISSING_CANONICAL_SQL = text(
    """
    SELECT ab.block_id
      FROM allocation_blocks ab
      LEFT JOIN strategic_allocation sa
        ON sa.block_id = ab.block_id
       AND sa.organization_id = :organization_id
       AND sa.profile = :profile
     WHERE ab.is_canonical = true
       AND sa.allocation_id IS NULL
     ORDER BY ab.block_id
    """
)

_EXTRA_NON_CANONICAL_SQL = text(
    """
    SELECT DISTINCT sa.block_id
      FROM strategic_allocation sa
      JOIN allocation_blocks ab ON ab.block_id = sa.block_id
     WHERE sa.organization_id = :organization_id
       AND sa.profile = :profile
       AND ab.is_canonical = false
     ORDER BY sa.block_id
    """
)


async def validate_template_completeness(
    db: AsyncSession,
    organization_id: uuid.UUID,
    profile: str,
) -> TemplateReport:
    """Build a :class:`TemplateReport` for the given org + profile.

    The report is ``is_complete = True`` iff every canonical block has
    a matching ``strategic_allocation`` row for the pair. Missing rows
    carry no weight information on purpose — this validator is strictly
    structural.
    """
    missing_rows = (
        await db.execute(
            _MISSING_CANONICAL_SQL,
            {"organization_id": organization_id, "profile": profile},
        )
    ).fetchall()
    extra_rows = (
        await db.execute(
            _EXTRA_NON_CANONICAL_SQL,
            {"organization_id": organization_id, "profile": profile},
        )
    ).fetchall()

    missing = [r[0] for r in missing_rows]
    extras = [r[0] for r in extra_rows]

    return TemplateReport(
        organization_id=organization_id,
        profile=profile,
        is_complete=not missing,
        missing_canonical_blocks=missing,
        extra_non_canonical_blocks=extras,
    )


def build_template_operator_message(report: TemplateReport) -> dict[str, Any]:
    """Backend-owned operator copy for ``template_incomplete`` signal.

    Mirrors ``build_coverage_operator_message`` so the frontend
    renders the same envelope shape for both pre-solve failures.
    """
    n_missing = len(report.missing_canonical_blocks)
    missing_list = ", ".join(report.missing_canonical_blocks) or "none"
    body_lines = [
        (
            f"Portfolio construction aborted: profile '{report.profile}' "
            f"is missing {n_missing} canonical allocation block(s). Expected "
            "18 blocks per profile per the institutional template; "
            f"{n_missing} are absent."
        ),
        "",
        f"Missing blocks: {missing_list}",
        "",
        (
            "Action: this should never happen post-migration 0153. "
            "Contact engineering if you see this message — it indicates "
            "the template trigger failed."
        ),
    ]
    return {
        "title": "Template incomplete — canonical blocks missing",
        "body": "\n".join(body_lines),
        "severity": "error",
        "action_hint": "contact_engineering_template_trigger_failed",
    }
