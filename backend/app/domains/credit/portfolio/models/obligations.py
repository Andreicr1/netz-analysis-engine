from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, Enum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, IdMixin, OrganizationScopedMixin
from app.domains.credit.portfolio.enums import ObligationStatus, ObligationType


class AssetObligation(Base, IdMixin, OrganizationScopedMixin, AuditMetaMixin):
    """Universal monitoring object.

    Obligations are generated per asset and drive alerts/actions.

    Examples:
    - Fund Investment -> NAV_REPORT quarterly
    - Loan -> COVENANT_TEST monthly

    Fund scoping is enforced via join to PortfolioAsset.
    """

    __tablename__ = "asset_obligations"

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
