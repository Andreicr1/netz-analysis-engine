from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class ICMemo(Base):
    """
    Institutional Investment Committee memo record.
    Stores structured metadata, narrative, recommendation and conditions.

    IC memos must persist forever.  Reprocessed deals create new versions
    (incremented ``version``), not updates to existing rows.
    """

    __tablename__ = "ic_memos"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    deal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), index=True, nullable=False
    )

    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)

    risks: Mapped[str | None] = mapped_column(Text, nullable=True)

    mitigants: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Recommendation & conditions (added for CONDITIONAL pipeline) ---

    recommendation: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="APPROVED | CONDITIONAL | REJECTED",
    )

    conditions: Mapped[list] = mapped_column(
        JSONB,
        server_default="[]",
        nullable=False,
        comment="List of pending conditions for a CONDITIONAL recommendation",
    )

    version: Mapped[int] = mapped_column(
        Integer,
        server_default="1",
        nullable=False,
        comment="Memo version — incremented on each reprocessing",
    )

    memo_blob_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="URL of the generated PDF in Azure Blob Storage",
    )

    condition_history: Mapped[list] = mapped_column(
        JSONB,
        server_default="[]",
        nullable=False,
        comment="Append-only log of condition resolution events",
    )

    # ── Adobe Sign e-signature fields ─────────────────────────────
    adobe_sign_agreement_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Adobe Sign agreement ID for committee voting",
    )

    committee_members: Mapped[list | None] = mapped_column(
        JSONB,
        server_default="[]",
        nullable=True,
        comment="List of committee member emails",
    )

    committee_votes: Mapped[list | None] = mapped_column(
        JSONB,
        server_default="[]",
        nullable=True,
        comment="Per-member vote log [{email, vote, signed_at, signer_status}]",
    )

    esignature_status: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="E-signature workflow status: NOT_SENT|SENT|IN_PROCESS|SIGNED|CANCELLED|ERROR",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
