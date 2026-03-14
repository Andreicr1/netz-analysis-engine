from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.domains.credit.reporting.enums import ReportSectionType


class ReportPackSection(Base):
    __tablename__ = "report_pack_sections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    report_pack_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monthly_report_packs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    section_type: Mapped[ReportSectionType] = mapped_column(
        SAEnum(ReportSectionType, name="report_section_type_enum"),
        nullable=False,
    )

    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

