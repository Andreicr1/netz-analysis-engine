from __future__ import annotations

import uuid

from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import (
    AuditMetaMixin,
    Base,
    FundScopedMixin,
    IdMixin,
    OrganizationScopedMixin,
)
from app.domains.credit.deals.enums import DealStage, DealType, RejectionCode


class Deal(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """Canonical record of every opportunity ever reviewed.
    Deals are never deleted, even if rejected.
    """

    __tablename__ = "deals"

    deal_type: Mapped[DealType] = mapped_column(
        Enum(DealType, name="deal_type_enum"),
        nullable=False,
    )

    stage: Mapped[DealStage] = mapped_column(
        Enum(DealStage, name="deal_stage_enum"),
        default=DealStage.INTAKE,
        nullable=False,
    )

    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    sponsor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    rejection_code: Mapped[RejectionCode | None] = mapped_column(
        Enum(RejectionCode, name="rejection_code_enum"),
        nullable=True,
    )

    rejection_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- AI monitoring output (populated by Portfolio AI) ---
    monitoring_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # --- Marketing thesis (populated by presentation_thesis_generator) ---
    marketing_thesis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # --- Pipeline back-reference ---
    pipeline_deal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pipeline_deals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # --- Financial term fields (populated during structuring) ---
    tenor_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    spread_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    covenant_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    covenant_frequency: Mapped[str | None] = mapped_column(String(50), nullable=True)
    collateral_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ltv_ratio: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    agreement_language: Mapped[str | None] = mapped_column(Text, nullable=True)

