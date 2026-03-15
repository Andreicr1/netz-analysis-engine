from __future__ import annotations

import uuid

from sqlalchemy import JSON, ForeignKey, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, IdMixin, OrganizationScopedMixin
from app.domains.credit.reporting.enums import ReportSectionType


class ReportPackSection(Base, IdMixin, OrganizationScopedMixin, AuditMetaMixin):
    __tablename__ = "report_pack_sections"

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

