"""Macroeconomic data time-series (FRED, etc.).

Stores raw FRED observations (VIX, Treasury rates, CPI, Fed Funds)
and derived series (yield curve spread, CPI YoY).
Regular PostgreSQL table — not a TimescaleDB hypertable, since
only ~5 series at daily/monthly frequency produce ~12,500 rows/decade.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class MacroData(Base):
    __tablename__ = "macro_data"

    series_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    obs_date: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    source: Mapped[str | None] = mapped_column(String(30), server_default="fred")
    is_derived: Mapped[bool] = mapped_column(Boolean, server_default="false")
