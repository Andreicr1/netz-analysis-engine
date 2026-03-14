from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, IdMixin, OrganizationScopedMixin
from app.domains.credit.portfolio.enums import ActionStatus


class Action(Base, IdMixin, OrganizationScopedMixin, AuditMetaMixin):
    """Execution layer.
    Every alert requires an action to be resolved with evidence.

    IMPORTANT: Actions must never exist without an Alert.
    Fund scoping is enforced via join to PortfolioAsset.
    """

    __tablename__ = "actions"

    asset_id: Mapped[uuid.UUID] = mapped_column(index=True)
    alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[ActionStatus] = mapped_column(
        Enum(ActionStatus, name="action_status_enum"),
        default=ActionStatus.OPEN,
        nullable=False,
    )

    evidence_required: Mapped[bool] = mapped_column(Boolean, default=True)

    evidence_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
