"""UniverseService — manages the approved fund universe.

Entry point for all universe operations. Helpers in fund_approval.py
handle the low-level approval logic.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.wealth.models.fund import Fund
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.instrument_org import InstrumentOrg
from app.domains.wealth.models.universe_approval import UniverseApproval
from vertical_engines.wealth.asset_universe.fund_approval import (
    create_pending_approval,
    decide_approval,
    validate_dd_report,
)
from vertical_engines.wealth.asset_universe.models import (
    ApprovalDecision,
    ApprovalRequest,
    DeactivationResult,
    UniverseAsset,
)
from vertical_engines.wealth.rebalancing.models import RebalanceResult

logger = structlog.get_logger()


class UniverseService:
    """Manages the approved fund universe with governance controls."""

    def add_fund(
        self,
        db: Session,
        *,
        instrument_id: uuid.UUID,
        analysis_report_id: uuid.UUID,
        created_by: str,
        organization_id: str,
    ) -> UniverseApproval:
        """Submit a fund for universe approval. Requires a completed DD Report.

        Creates a pending UniverseApproval record. The fund must have a
        completed (or escalated) DD Report before it can be submitted.
        """
        # Verify the fund exists (check Instrument first, fallback to Fund)
        inst = db.execute(
            select(Instrument).where(Instrument.instrument_id == instrument_id),
        ).scalar_one_or_none()
        if inst is None:
            fund = db.execute(
                select(Fund).where(Fund.fund_id == instrument_id),
            ).scalar_one_or_none()
            if fund is None:
                raise ValueError(f"Fund {instrument_id} not found")
            fund.approval_status = "dd_complete"
        else:
            # Update approval_status on InstrumentOrg (org-scoped)
            inst_org = db.execute(
                select(InstrumentOrg).where(
                    InstrumentOrg.instrument_id == instrument_id,
                    InstrumentOrg.organization_id == organization_id,
                ),
            ).scalar_one_or_none()
            if inst_org:
                inst_org.approval_status = "dd_complete"

        # Verify DD report is valid
        validate_dd_report(db, analysis_report_id, instrument_id)

        request = ApprovalRequest(
            instrument_id=instrument_id,
            analysis_report_id=analysis_report_id,
            created_by=created_by,
            organization_id=organization_id,
        )
        approval = create_pending_approval(db, request)

        logger.info(
            "universe_fund_submitted",
            instrument_id=str(instrument_id),
            approval_id=str(approval.id),
            organization_id=organization_id,
        )
        return approval

    def approve_fund(
        self,
        db: Session,
        *,
        approval_id: uuid.UUID,
        decision: str,
        rationale: str | None,
        decided_by: str,
    ) -> UniverseApproval:
        """Approve, reject, or watchlist a fund in the universe.

        Enforces self-approval prevention (decided_by != created_by).
        Uses SELECT FOR UPDATE to prevent concurrent state corruption.
        """
        decision_obj = ApprovalDecision(
            approval_id=approval_id,
            decision=decision,
            rationale=rationale,
            decided_by=decided_by,
        )
        approval = decide_approval(db, decision_obj)

        logger.info(
            "universe_fund_decided",
            approval_id=str(approval_id),
            decision=decision,
            decided_by=decided_by,
        )
        return approval

    def list_universe(
        self,
        db: Session,
        *,
        organization_id: str,
        block_id: str | None = None,
        geography: str | None = None,
        asset_class: str | None = None,
    ) -> list[UniverseAsset]:
        """List approved funds in the universe with optional filters."""
        stmt = (
            select(Instrument, InstrumentOrg, UniverseApproval)
            .join(
                InstrumentOrg,
                InstrumentOrg.instrument_id == Instrument.instrument_id,
            )
            .join(
                UniverseApproval,
                (UniverseApproval.instrument_id == Instrument.instrument_id)
                & (UniverseApproval.is_current.is_(True))
                & (UniverseApproval.decision == "approved"),
            )
            .where(
                Instrument.is_active.is_(True),
                InstrumentOrg.organization_id == organization_id,
            )
        )

        if block_id is not None:
            stmt = stmt.where(InstrumentOrg.block_id == block_id)
        if geography is not None:
            stmt = stmt.where(Instrument.geography == geography)
        if asset_class is not None:
            stmt = stmt.where(Instrument.asset_class == asset_class)

        stmt = stmt.order_by(Instrument.name)

        rows = db.execute(stmt).all()
        return [
            UniverseAsset(
                instrument_id=inst.instrument_id,
                fund_name=inst.name,
                block_id=inst_org.block_id,
                geography=inst.geography,
                investment_geography=inst.investment_geography,
                asset_class=inst.asset_class,
                approval_status=inst_org.approval_status,
                approval_decision=approval.decision,
                approved_at=approval.decided_at,
            )
            for inst, inst_org, approval in rows
        ]

    def list_pending(
        self,
        db: Session,
        *,
        organization_id: str,
    ) -> list[UniverseApproval]:
        """List pending approvals for an organization."""
        result = db.execute(
            select(UniverseApproval).where(
                UniverseApproval.organization_id == organization_id,
                UniverseApproval.is_current.is_(True),
                UniverseApproval.decision == "pending",
            ).order_by(UniverseApproval.created_at.desc()),
        )
        return list(result.scalars().all())

    def deactivate_asset(
        self,
        db: Session,
        *,
        instrument_id: uuid.UUID,
        organization_id: str,
    ) -> tuple[DeactivationResult, RebalanceResult | None]:
        """Remove a fund from the active universe.

        Sets Instrument.is_active = False and marks current approval as not current.
        Returns (DeactivationResult, RebalanceResult | None). RebalanceResult
        is computed when the fund was previously approved.
        """
        inst = db.execute(
            select(Instrument)
            .join(InstrumentOrg, InstrumentOrg.instrument_id == Instrument.instrument_id)
            .where(
                Instrument.instrument_id == instrument_id,
                InstrumentOrg.organization_id == organization_id,
            ).with_for_update(),
        ).scalar_one_or_none()

        if inst is None:
            # Fallback to legacy Fund table
            fund = db.execute(
                select(Fund).where(
                    Fund.fund_id == instrument_id,
                    Fund.organization_id == organization_id,
                ).with_for_update(),
            ).scalar_one_or_none()
            if fund is None:
                raise ValueError(f"Fund {instrument_id} not found")
            was_active = fund.is_active
            fund.is_active = False
        else:
            was_active = inst.is_active
            inst.is_active = False

        # Check if fund was approved (rebalance needed)
        approval = db.execute(
            select(UniverseApproval).where(
                UniverseApproval.instrument_id == instrument_id,
                UniverseApproval.organization_id == organization_id,
                UniverseApproval.is_current.is_(True),
                UniverseApproval.decision == "approved",
            ),
        ).scalar_one_or_none()

        rebalance_needed = approval is not None

        # Mark current approval as not current
        if approval is not None:
            approval.is_current = False

        db.flush()

        logger.info(
            "universe_asset_deactivated",
            instrument_id=str(instrument_id),
            was_active=was_active,
            rebalance_needed=rebalance_needed,
        )

        deactivation = DeactivationResult(
            instrument_id=instrument_id,
            was_active=was_active,
            rebalance_needed=rebalance_needed,
        )

        # Trigger rebalancing if fund was approved
        rebalance_result: RebalanceResult | None = None
        if rebalance_needed:
            from vertical_engines.wealth.rebalancing.service import RebalancingService

            svc = RebalancingService()
            rebalance_result = svc.compute_rebalance_impact(
                db=db,
                instrument_id=instrument_id,
                organization_id=organization_id,
                trigger="deactivation",
            )
            logger.info(
                "rebalance_triggered_on_deactivation",
                instrument_id=str(instrument_id),
                affected_portfolios=len(rebalance_result.impact.affected_portfolios),
                all_feasible=rebalance_result.all_feasible,
            )

        return deactivation, rebalance_result
