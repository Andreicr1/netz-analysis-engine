from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.domains.credit.deals.enums import DealStage
from app.domains.credit.deals.models.deals import Deal
from app.domains.credit.deals.models.ic_memos import ICMemo

# ---------------------------------------------------------------------------
# Valid stage transitions
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[DealStage, list[DealStage]] = {
    DealStage.INTAKE: [DealStage.QUALIFIED, DealStage.REJECTED],
    DealStage.QUALIFIED: [DealStage.IC_REVIEW, DealStage.REJECTED],
    DealStage.IC_REVIEW: [DealStage.APPROVED, DealStage.CONDITIONAL, DealStage.REJECTED],
    DealStage.CONDITIONAL: [DealStage.CONDITIONAL, DealStage.APPROVED, DealStage.REJECTED],
    DealStage.APPROVED: [DealStage.CONVERTED_TO_ASSET, DealStage.CLOSED],
    DealStage.CONVERTED_TO_ASSET: [DealStage.CLOSED],
    DealStage.REJECTED: [],   # terminal
    DealStage.CLOSED: [],      # terminal
}


async def _get_latest_memo(db: AsyncSession, deal_id: uuid.UUID) -> ICMemo | None:
    """Return the most recent ICMemo for a deal, ordered by version DESC."""
    result = await db.execute(
        select(ICMemo).where(ICMemo.deal_id == deal_id).order_by(ICMemo.version.desc()),
    )
    return result.scalar_one_or_none()


def _open_conditions(memo: ICMemo) -> list[str]:
    """Return titles of conditions still ``open`` in a memo."""
    conditions = memo.conditions or []
    return [
        c.get("title", c.get("id", "unknown"))
        for c in conditions
        if c.get("status", "open") == "open"
    ]


async def transition_deal_stage(
    db: AsyncSession,
    deal: Deal,
    new_stage: DealStage,
    *,
    actor_id: str,
    fund_id: uuid.UUID,
    extra_audit: dict | None = None,
) -> None:
    """Validate and execute a deal stage transition.

    * Writes an audit event.
    * Sets ``deal.updated_at``.
    * Calls ``db.flush()`` — the caller is responsible for ``db.commit()``.

    Raises ``ValueError`` with a descriptive message if the transition is invalid.
    """

    from_stage = deal.stage
    allowed = VALID_TRANSITIONS.get(from_stage, [])

    if new_stage not in allowed:
        raise ValueError(
            f"Invalid stage transition: {from_stage.value} → {new_stage.value}. "
            f"Allowed targets from {from_stage.value}: "
            f"{[s.value for s in allowed] if allowed else '(terminal — none)'}.",
        )

    # --- Guard: CONDITIONAL requires a memo with non-empty conditions ---
    if new_stage == DealStage.CONDITIONAL:
        memo = await _get_latest_memo(db, deal.id)
        if not memo or not memo.conditions:
            raise ValueError(
                "Cannot transition to CONDITIONAL: the deal has no IC Memo "
                "with pending conditions. Create a CONDITIONAL memo first.",
            )

    # --- Guard: APPROVED from CONDITIONAL requires all conditions resolved ---
    if new_stage == DealStage.APPROVED and from_stage == DealStage.CONDITIONAL:
        memo = await _get_latest_memo(db, deal.id)
        if memo:
            open_titles = _open_conditions(memo)
            if open_titles:
                titles_str = "; ".join(open_titles)
                raise ValueError(
                    f"Cannot approve deal with {len(open_titles)} open condition(s): "
                    f"{titles_str}. Resolve or waive all conditions first.",
                )

    # --- Execute transition ---
    before = {
        "stage": from_stage.value,
        "rejection_code": deal.rejection_code.value if deal.rejection_code else None,
        "rejection_notes": deal.rejection_notes,
    }

    deal.stage = new_stage
    deal.updated_at = datetime.now(UTC)
    await db.flush()

    after: dict = {"stage": new_stage.value}
    if extra_audit:
        after.update(extra_audit)

    await write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor_id,
        action=f"deal.stage.transition.{from_stage.value.lower()}_to_{new_stage.value.lower()}",
        entity_type="Deal",
        entity_id=str(deal.id),
        before=before,
        after=after,
    )

    from app.domains.credit.modules.deals.models import DealStageHistory

    history_entry = DealStageHistory(
        deal_id=deal.id,
        fund_id=fund_id,
        from_stage=from_stage.value,
        to_stage=new_stage.value,
        rationale=extra_audit.get("rejection_notes") if extra_audit else None,
    )
    db.add(history_entry)
    await db.flush()
