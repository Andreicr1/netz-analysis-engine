"""Portfolio covenant surveillance — build covenant status register."""
from __future__ import annotations

import datetime as dt
import uuid

import structlog
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domains.credit.modules.ai.models import (
    ActiveInvestment,
    CovenantStatusRegister,
)
from app.domains.credit.modules.portfolio.models import (
    Covenant,
    CovenantBreach,
    CovenantTest,
)

logger = structlog.get_logger()


def build_covenant_surveillance(
    db: Session,
    *,
    fund_id: uuid.UUID,
    as_of: dt.datetime,
    actor_id: str = "ai-engine",
) -> list[CovenantStatusRegister]:
    logger.info("build_covenant_surveillance.start", fund_id=str(fund_id))

    investments = list(db.execute(select(ActiveInvestment).where(ActiveInvestment.fund_id == fund_id)).scalars().all())
    covenants = list(db.execute(select(Covenant).where(Covenant.fund_id == fund_id)).scalars().all())

    db.execute(delete(CovenantStatusRegister).where(CovenantStatusRegister.fund_id == fund_id))

    all_tests = list(db.execute(
        select(CovenantTest).where(CovenantTest.fund_id == fund_id)
        .order_by(CovenantTest.covenant_id, CovenantTest.tested_at.desc()),
    ).scalars().all())
    latest_test_by_covenant: dict[uuid.UUID, CovenantTest] = {}
    for t in all_tests:
        if t.covenant_id not in latest_test_by_covenant:
            latest_test_by_covenant[t.covenant_id] = t

    test_ids = [t.id for t in latest_test_by_covenant.values()]
    all_breaches = list(db.execute(
        select(CovenantBreach).where(
            CovenantBreach.fund_id == fund_id,
            CovenantBreach.covenant_test_id.in_(test_ids),
        ),
    ).scalars().all()) if test_ids else []
    breach_by_test: dict[uuid.UUID, CovenantBreach] = {b.covenant_test_id: b for b in all_breaches}

    saved: list[CovenantStatusRegister] = []
    for inv in investments:
        matched = covenants
        if matched:
            for covenant in matched:
                latest_test = latest_test_by_covenant.get(covenant.id)
                breach = breach_by_test.get(latest_test.id) if latest_test else None

                status = "PASS"
                severity = "LOW"
                details = "Latest covenant test passed or no breach evidence registered."
                if breach is not None:
                    status = "BREACH"
                    severity = "HIGH" if (breach.severity or "").lower() in {"critical", "high"} else "MEDIUM"
                    details = f"Breach detected with severity {breach.severity}."
                elif latest_test is None:
                    status = "NOT_TESTED"
                    severity = "MEDIUM"
                    details = "No covenant test found for current monitoring cycle."
                elif latest_test.passed is False:
                    status = "WARNING"
                    severity = "MEDIUM"
                    details = latest_test.notes or "Covenant test failed and requires review."

                last_tested_at = None
                if latest_test and latest_test.tested_at:
                    last_tested_at = dt.datetime.combine(latest_test.tested_at, dt.time.min, tzinfo=dt.UTC)
                next_due = (last_tested_at + dt.timedelta(days=30)) if last_tested_at else None

                row = CovenantStatusRegister(
                    fund_id=fund_id,
                    access_level="internal",
                    investment_id=inv.id,
                    covenant_id=covenant.id,
                    covenant_test_id=latest_test.id if latest_test else None,
                    breach_id=breach.id if breach else None,
                    covenant_name=covenant.name,
                    status=status,
                    severity=severity,
                    details=details,
                    last_tested_at=last_tested_at,
                    next_test_due_at=next_due,
                    as_of=as_of,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
                db.add(row)
                saved.append(row)
        else:
            db.add(
                CovenantStatusRegister(
                    fund_id=fund_id,
                    access_level="internal",
                    investment_id=inv.id,
                    covenant_id=None,
                    covenant_test_id=None,
                    breach_id=None,
                    covenant_name="Portfolio Covenant Set",
                    status="NOT_CONFIGURED",
                    severity="MEDIUM",
                    details="No covenant configuration found for fund; monitoring requires covenant setup.",
                    last_tested_at=None,
                    next_test_due_at=None,
                    as_of=as_of,
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
            )

    db.flush()
    result = list(db.execute(select(CovenantStatusRegister).where(CovenantStatusRegister.fund_id == fund_id)).scalars().all())
    logger.info("build_covenant_surveillance.done", fund_id=str(fund_id), count=len(result))
    return result
