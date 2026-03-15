from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.domains.credit.portfolio.enums import AlertSeverity, AlertType, ObligationStatus
from app.domains.credit.portfolio.models.actions import Action
from app.domains.credit.portfolio.models.alerts import Alert
from app.domains.credit.portfolio.models.assets import PortfolioAsset
from app.domains.credit.portfolio.models.obligations import AssetObligation


async def check_overdue_obligations(db: AsyncSession) -> int:
    """Workflow loop: detect overdue obligations and generate Alerts + Actions.

    Auditability:
    - writes audit events with actor_id='system' and request_id='workflow'
    Idempotency:
    - does not duplicate alerts/actions for the same obligation
    """
    today = date.today()

    result = await db.execute(
        select(AssetObligation, PortfolioAsset.fund_id)
        .join(PortfolioAsset, PortfolioAsset.id == AssetObligation.asset_id)
        .where(
            AssetObligation.status == ObligationStatus.OPEN,
            AssetObligation.due_date < today,
        ),
    )
    overdue = result.all()

    overdue_ob_ids = [ob.id for ob, _ in overdue]
    existing_alerts_map: dict = {}
    if overdue_ob_ids:
        alerts_result = await db.execute(
            select(Alert).where(
                Alert.obligation_id.in_(overdue_ob_ids),
                Alert.alert_type == AlertType.OBLIGATION_OVERDUE,
            ),
        )
        existing_alerts_map = {
            a.obligation_id: a
            for a in alerts_result.scalars().all()
        }

    generated = 0
    for ob, fund_id in overdue:
        existing_alert = existing_alerts_map.get(ob.id)
        if existing_alert:
            # Ensure obligation is marked overdue even if alert exists.
            if ob.status != ObligationStatus.OVERDUE:
                before = {"status": ob.status.value}
                ob.status = ObligationStatus.OVERDUE
                await db.flush()
                await write_audit_event(
                    db=db,
                    fund_id=fund_id,
                    actor_id="system",
                    request_id="workflow",
                    action="obligation.status_overdue",
                    entity_type="AssetObligation",
                    entity_id=str(ob.id),
                    before=before,
                    after={"status": ob.status.value},
                )
            continue

        alert = Alert(
            asset_id=ob.asset_id,
            obligation_id=ob.id,
            alert_type=AlertType.OBLIGATION_OVERDUE,
            severity=AlertSeverity.HIGH,
        )
        db.add(alert)
        await db.flush()

        await write_audit_event(
            db=db,
            fund_id=fund_id,
            actor_id="system",
            request_id="workflow",
            action="alert.generated.overdue_obligation",
            entity_type="Alert",
            entity_id=str(alert.id),
            before=None,
            after={
                "asset_id": str(ob.asset_id),
                "obligation_id": str(ob.id),
                "alert_type": AlertType.OBLIGATION_OVERDUE.value,
                "severity": AlertSeverity.HIGH.value,
            },
        )

        action = Action(
            asset_id=ob.asset_id,
            alert_id=alert.id,
            title=f"Resolve overdue obligation: {ob.obligation_type.value}",
            evidence_required=True,
        )
        db.add(action)
        await db.flush()

        await write_audit_event(
            db=db,
            fund_id=fund_id,
            actor_id="system",
            request_id="workflow",
            action="action.generated.from_alert",
            entity_type="Action",
            entity_id=str(action.id),
            before=None,
            after={
                "asset_id": str(ob.asset_id),
                "alert_id": str(alert.id),
                "title": action.title,
                "evidence_required": True,
            },
        )

        before = {"status": ob.status.value}
        ob.status = ObligationStatus.OVERDUE
        await db.flush()

        await write_audit_event(
            db=db,
            fund_id=fund_id,
            actor_id="system",
            request_id="workflow",
            action="obligation.updated",
            entity_type="AssetObligation",
            entity_id=str(ob.id),
            before=before,
            after={"status": ob.status.value},
        )

        generated += 1

    if generated > 0:
        await db.commit()

    return generated
