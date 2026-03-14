"""Lipper fund ratings (populated when FEATURE_LIPPER_ENABLED=true).

Stores Lipper Leader ratings (1-5 scale) for fund evaluation.
Table is created empty and ready to receive data when the
Lipper/LSEG API key and documentation become available.
"""

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, OrganizationScopedMixin


class LipperRating(OrganizationScopedMixin, Base):
    __tablename__ = "lipper_ratings"

    fund_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funds_universe.fund_id"), primary_key=True
    )
    rating_date: Mapped[date] = mapped_column(Date, primary_key=True)
    overall_rating: Mapped[int | None] = mapped_column(Integer)
    consistent_return: Mapped[int | None] = mapped_column(Integer)
    preservation: Mapped[int | None] = mapped_column(Integer)
    total_return: Mapped[int | None] = mapped_column(Integer)
    expense: Mapped[int | None] = mapped_column(Integer)
    tax_efficiency: Mapped[int | None] = mapped_column(Integer)
    fund_classification: Mapped[str | None] = mapped_column(String(80))
    source: Mapped[str | None] = mapped_column(String(30), server_default="lipper")
