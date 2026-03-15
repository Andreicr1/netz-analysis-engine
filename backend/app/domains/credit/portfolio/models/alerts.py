from __future__ import annotations

import uuid

from sqlalchemy import Enum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, IdMixin, OrganizationScopedMixin
from app.domains.credit.portfolio.enums import AlertSeverity, AlertType


class Alert(Base, IdMixin, OrganizationScopedMixin, AuditMetaMixin):
    """Alert objects are generated when an obligation is missed or breached.
    Alerts are always linked to an asset and optionally to an obligation.

    Fund scoping is enforced via join to PortfolioAsset.
    """

    __tablename__ = "alerts"

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
