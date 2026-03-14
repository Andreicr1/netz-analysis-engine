from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.domains.credit.portfolio.enums import ObligationStatus, ObligationType


class AssetObligation(Base):
    """Universal monitoring object.

    Obligations are generated per asset and drive alerts/actions.

    Examples:
    - Fund Investment → NAV_REPORT quarterly
    - Loan → COVENANT_TEST monthly

    IMPORTANT: AssetObligation must never contain fund_id directly.
    Fund scoping is enforced via join to PortfolioAsset.

    """

    __tablename__ = "asset_obligations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    asset_id: Mapped[uuid.UUID] = mapped_column(index=True)

    obligation_type: Mapped[ObligationType] = mapped_column(
        Enum(ObligationType, name="obligation_type_enum"),
        nullable=False,
    )

    status: Mapped[ObligationStatus] = mapped_column(
        Enum(ObligationStatus, name="obligation_status_enum"),
        default=ObligationStatus.OPEN,
        nullable=False,
    )

    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

