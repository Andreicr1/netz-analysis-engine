from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base


class AllocationBlock(Base, AuditMetaMixin):
    __tablename__ = "allocation_blocks"

    block_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    geography: Mapped[str] = mapped_column(String(50), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    benchmark_ticker: Mapped[str | None] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
