"""PR-A22 — Block Coverage Validator.

Pre-run check that hard-fails portfolio construction when any block in
the profile's ``StrategicAllocation`` has zero approved candidates in
the org's universe. Replaces the silent fallback where the optimizer
would redistribute missing-block weight across blocks that DO have
candidates, producing a portfolio that violates the declared mandate
without any operator signal.

Called as the first step of ``construction_run_executor`` — before
universe loading, before statistical inputs, before the solver. If the
report ``is_sufficient = False`` the run is marked ``failed`` with
``winner_signal = 'block_coverage_insufficient'`` and a structured
gap report is persisted to ``cascade_telemetry.coverage_report``.

Design principles
-----------------
* **No threshold.** Any block with ``target_weight > 0`` and
  ``n_candidates = 0`` fails the validator. If the operator wants to
  run with a gap they must explicitly set the block's
  ``target_weight`` to zero in their ``StrategicAllocation`` — an
  explicit mandate decision, not a silent substitution.
* **Deduplicate strategic_allocation rows.** The profile may
  transiently have more than one row per block (historical defect).
  The validator reduces to one row per ``block_id`` by keeping the
  max ``target_weight`` so a true coverage picture surfaces.
* **Catalog suggestions are best-effort.** Operator sees counts plus
  the top-5 tickers by AUM so they can go to the universe editor and
  import candidates — the validator never auto-imports.
"""
from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vertical_engines.wealth.model_portfolio.block_mapping import (
    strategy_labels_for_block,
)


class BlockCoverageGap(BaseModel):
    """One entry per uncovered block in the report."""

    block_id: str
    target_weight: float
    suggested_strategy_labels: list[str] = Field(default_factory=list)
    catalog_candidates_available: int = 0
    example_tickers: list[str] = Field(default_factory=list)


class CoverageReport(BaseModel):
    """Coverage status for one ``(organization_id, profile)`` pair."""

    organization_id: uuid.UUID
    profile: str
    is_sufficient: bool
    total_target_weight_at_risk: float = 0.0
    gaps: list[BlockCoverageGap] = Field(default_factory=list)


_STRATEGIC_ALLOCATION_SQL = text(
    """
    SELECT block_id, MAX(target_weight) AS target_weight
      FROM strategic_allocation
     WHERE profile = :profile
       AND organization_id = :organization_id
       AND target_weight > 0
       AND (effective_to IS NULL OR effective_to > CURRENT_DATE)
     GROUP BY block_id
    """
)

_APPROVED_COUNT_SQL = text(
    """
    SELECT COUNT(*)
      FROM instruments_org io
      JOIN instruments_universe iu
        ON iu.instrument_id = io.instrument_id
     WHERE io.organization_id = :organization_id
       AND io.approval_status = 'approved'
       AND iu.is_active = TRUE
       AND iu.attributes->>'strategy_label' = ANY(CAST(:labels AS text[]))
    """
)

_CATALOG_CANDIDATES_SQL = text(
    """
    SELECT ticker
      FROM instruments_universe
     WHERE is_active = TRUE
       AND is_institutional = TRUE
       AND attributes->>'strategy_label' = ANY(CAST(:labels AS text[]))
     ORDER BY
        COALESCE(NULLIF(attributes->>'aum_usd', '')::numeric, 0) DESC
          NULLS LAST
     LIMIT 5
    """
)

_CATALOG_COUNT_SQL = text(
    """
    SELECT COUNT(*)
      FROM instruments_universe
     WHERE is_active = TRUE
       AND is_institutional = TRUE
       AND attributes->>'strategy_label' = ANY(CAST(:labels AS text[]))
    """
)


async def _count_approved(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    labels: list[str],
) -> int:
    if not labels:
        return 0
    row = await db.execute(
        _APPROVED_COUNT_SQL,
        {"organization_id": organization_id, "labels": labels},
    )
    return int(row.scalar_one() or 0)


async def _catalog_snapshot(
    db: AsyncSession,
    *,
    labels: list[str],
) -> tuple[int, list[str]]:
    """Return ``(count, top5_tickers)`` for a given set of strategy labels.

    Gracefully degrades to ``(0, [])`` when ``labels`` is empty so the
    caller never has to special-case an unmapped block.
    """
    if not labels:
        return 0, []
    count_row = await db.execute(_CATALOG_COUNT_SQL, {"labels": labels})
    count = int(count_row.scalar_one() or 0)
    if count == 0:
        return 0, []
    tickers_row = await db.execute(_CATALOG_CANDIDATES_SQL, {"labels": labels})
    tickers = [r[0] for r in tickers_row.fetchall() if r[0]]
    return count, tickers


async def validate_block_coverage(
    db: AsyncSession,
    organization_id: uuid.UUID,
    profile: str,
) -> CoverageReport:
    """Build a :class:`CoverageReport` for the given org + profile.

    Pure read-only — never writes. Uses the RLS-aware session passed
    by the caller (``construction_run_executor``). Does not raise on
    empty allocations — an empty allocation simply returns
    ``is_sufficient=True`` with no gaps (semantically "nothing to
    cover", which is a different defect surfaced elsewhere).
    """
    rows = (
        await db.execute(
            _STRATEGIC_ALLOCATION_SQL,
            {"profile": profile, "organization_id": organization_id},
        )
    ).fetchall()

    gaps: list[BlockCoverageGap] = []
    weight_at_risk = 0.0
    for block_id, target_weight in rows:
        labels = strategy_labels_for_block(block_id)
        n_candidates = await _count_approved(
            db,
            organization_id=organization_id,
            labels=labels,
        )
        if n_candidates > 0:
            continue
        catalog_count, example_tickers = await _catalog_snapshot(
            db, labels=labels,
        )
        tw = float(target_weight or 0.0)
        weight_at_risk += tw
        gaps.append(
            BlockCoverageGap(
                block_id=block_id,
                target_weight=tw,
                suggested_strategy_labels=labels,
                catalog_candidates_available=catalog_count,
                example_tickers=example_tickers,
            )
        )

    return CoverageReport(
        organization_id=organization_id,
        profile=profile,
        is_sufficient=not gaps,
        total_target_weight_at_risk=weight_at_risk,
        gaps=gaps,
    )


def build_coverage_operator_message(report: CoverageReport) -> dict[str, Any]:
    """Backend-owned copy for the ``block_coverage_insufficient`` signal.

    Mirrors ``build_operator_message`` in ``schemas/sanitized.py`` —
    frontend renders verbatim (smart-backend / dumb-frontend).
    """
    pct = report.total_target_weight_at_risk * 100
    lines = [
        (
            f"Portfolio construction aborted: {pct:.1f}% of the declared "
            "mandate is uncovered. The following blocks have zero approved "
            "candidates in your universe:"
        ),
        "",
    ]
    for gap in report.gaps:
        gap_pct = gap.target_weight * 100
        tickers = ", ".join(gap.example_tickers) if gap.example_tickers else "none"
        lines.append(
            f"  • {gap.block_id} (target {gap_pct:.1f}%): "
            f"{gap.catalog_candidates_available} candidates available in "
            f"the global catalog. Examples: {tickers}."
        )
    lines.append("")
    lines.append(
        "Action: review your approved universe and either import "
        "candidates for the uncovered blocks or adjust the "
        "StrategicAllocation to set their target_weight to zero."
    )
    return {
        "title": "Coverage insufficient — mandate cannot be honoured",
        "body": "\n".join(lines),
        "severity": "error",
        "action_hint": "expand_universe_or_zero_weight",
    }
