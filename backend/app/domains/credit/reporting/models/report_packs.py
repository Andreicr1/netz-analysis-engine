from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.domains.credit.reporting.enums import MonthlyPackType, ReportPackStatus


class MonthlyReportPack(Base):
    __tablename__ = "monthly_report_packs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    fund_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    # EPIC 11 linkage/output metadata (nullable for backward compatibility with EPIC 8/legacy packs)
    nav_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("nav_snapshots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    blob_path: Mapped[str | None] = mapped_column(String(800), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    generated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pack_type: Mapped[MonthlyPackType | None] = mapped_column(
        SAEnum(MonthlyPackType, name="monthly_pack_type_enum"),
        nullable=True,
        index=True,
    )

    status: Mapped[ReportPackStatus] = mapped_column(
        SAEnum(ReportPackStatus, name="report_pack_status_enum"),
        default=ReportPackStatus.DRAFT,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    title: Mapped[str] = mapped_column(String(255), default="Monthly Report Pack", nullable=False)

