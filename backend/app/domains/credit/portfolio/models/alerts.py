from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.domains.credit.portfolio.enums import AlertSeverity, AlertType


class Alert(Base):
    """
    Alert objects are generated when an obligation is missed or breached.
    Alerts are always linked to an asset and optionally to an obligation.

    IMPORTANT: Alerts must not contain fund_id directly.
    Fund scoping is enforced via join to PortfolioAsset.
    """

    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    asset_id: Mapped[uuid.UUID] = mapped_column(index=True)
    obligation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    alert_type: Mapped[AlertType] = mapped_column(
        Enum(AlertType, name="alert_type_enum"),
        nullable=False,
    )

    severity: Mapped[AlertSeverity] = mapped_column(
        Enum(AlertSeverity, name="alert_severity_enum"),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

