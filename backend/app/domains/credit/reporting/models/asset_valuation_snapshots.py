from __future__ import annotations

import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, OrganizationScopedMixin, IdMixin
from app.domains.credit.reporting.enums import ValuationMethod


class AssetValuationSnapshot(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "asset_valuation_snapshots"

    nav_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("nav_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    asset_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    valuation_usd: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    valuation_method: Mapped[ValuationMethod] = mapped_column(
        SAEnum(ValuationMethod, name="valuation_method_enum"),
        nullable=False,
        index=True,
    )

    supporting_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        Index("ix_asset_valuation_snapshots_fund_nav", "fund_id", "nav_snapshot_id"),
        Index("ix_asset_valuation_snapshots_nav_asset", "nav_snapshot_id", "asset_id"),
    )
