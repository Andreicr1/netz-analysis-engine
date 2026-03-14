"""KYC domain models — Enhanced KYC screening via KYC Spider v3.

Tables:
  - kyc_screenings       Master screening record (one per entity screened)
  - kyc_screening_matches Individual match rows returned by KYC Spider
  - kyc_monitoring_alerts Ongoing-monitoring alert rows
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, IdMixin


class KYCScreening(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """A single KYC screening request against the KYC Spider API."""

    __tablename__ = "kyc_screenings"

    # ── KYC Spider remote identifiers ─────────────────────────────────
    spider_screening_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True, index=True,
        comment="KYC Spider remote screening ID",
    )

    # ── Entity being screened ─────────────────────────────────────────
    entity_type: Mapped[str] = mapped_column(
        String(32), index=True,
        comment="PERSON | ORGANISATION",
    )
    # Person fields
    first_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    date_of_birth: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    nationality: Mapped[str | None] = mapped_column(String(3), nullable=True, comment="ISO-3166 alpha-2")
    # Organisation fields
    entity_name: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    registration_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country_of_incorporation: Mapped[str | None] = mapped_column(String(3), nullable=True)

    # ── Screening configuration ───────────────────────────────────────
    profile_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    datasets: Mapped[list | None] = mapped_column(JSON, nullable=True, comment='e.g. ["PEP","SANCTIONS","ADVERSE_MEDIA"]')
    fuzziness: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Internal cross-references ─────────────────────────────────────
    # Link to a deal, asset, or counterparty for traceability
    reference_entity_type: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
        comment="deal | asset | counterparty | borrower | guarantor",
    )
    reference_entity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    reference_label: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ── Results summary ───────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING", index=True,
        comment="PENDING | COMPLETED | ERROR | CLEARED | FLAGGED",
    )
    total_matches: Mapped[int] = mapped_column(default=0)
    pep_hits: Mapped[int] = mapped_column(default=0)
    sanctions_hits: Mapped[int] = mapped_column(default=0)
    adverse_media_hits: Mapped[int] = mapped_column(default=0)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Ongoing monitoring ────────────────────────────────────────────
    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    monitoring_last_checked: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # ── Review / decision ─────────────────────────────────────────────
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_decision: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="APPROVED | REJECTED | ESCALATED | PENDING_REVIEW",
    )
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Raw API response (full payload for audit) ─────────────────────
    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────
    matches: Mapped[list[KYCScreeningMatch]] = relationship(
        back_populates="screening",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_kyc_screenings_fund_status", "fund_id", "status"),
        Index("ix_kyc_screenings_ref", "reference_entity_type", "reference_entity_id"),
    )


class KYCScreeningMatch(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """Individual match returned by KYC Spider for a screening."""

    __tablename__ = "kyc_screening_matches"

    screening_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("kyc_screenings.id", ondelete="CASCADE"), index=True,
    )
    spider_match_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True,
        comment="KYC Spider remote match ID",
    )

    # ── Match details ─────────────────────────────────────────────────
    matched_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_type: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
        comment="PEP | SANCTIONS | ADVERSE_MEDIA | WATCHLIST | OTHER",
    )
    dataset_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # ── PEP-specific fields ───────────────────────────────────────────
    pep_tier: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="TIER_1 | TIER_2 | TIER_3 | RCA")
    pep_position: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pep_country: Mapped[str | None] = mapped_column(String(3), nullable=True)

    # ── Sanctions-specific fields ─────────────────────────────────────
    sanction_list: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="e.g. OFAC SDN, EU, UN")
    sanction_program: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # ── Resolution ────────────────────────────────────────────────────
    resolution: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True,
        comment="TRUE_POSITIVE | FALSE_POSITIVE | UNDECIDED",
    )
    resolved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Raw match payload ─────────────────────────────────────────────
    raw_match: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────
    screening: Mapped[KYCScreening] = relationship(back_populates="matches")

    __table_args__ = (
        Index("ix_kyc_matches_screening_type", "screening_id", "match_type"),
    )


class KYCMonitoringAlert(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """Ongoing-monitoring alert from KYC Spider."""

    __tablename__ = "kyc_monitoring_alerts"

    screening_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("kyc_screenings.id", ondelete="CASCADE"), index=True,
    )
    spider_alert_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True, index=True,
    )

    alert_type: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="NEW_MATCH | STATUS_CHANGE | DATA_UPDATE")
    alert_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="HIGH | MEDIUM | LOW")

    # Resolution
    status: Mapped[str] = mapped_column(
        String(32), default="OPEN", index=True,
        comment="OPEN | CONFIRMED | DISMISSED",
    )
    resolved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    raw_alert: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_kyc_alerts_fund_status", "fund_id", "status"),
    )
