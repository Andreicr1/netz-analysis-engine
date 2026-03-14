from __future__ import annotations

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, IdMixin
from app.domains.credit.portfolio.enums import AssetType, Strategy


class PortfolioAsset(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """
    Canonical asset object (asset-first).

    All subtype tables (e.g. FundInvestment) must link 1:1 via asset_id.
    """

    __tablename__ = "portfolio_assets"

    asset_type: Mapped[AssetType] = mapped_column(Enum(AssetType, name="asset_type_enum"), nullable=False, index=True)
    strategy: Mapped[Strategy] = mapped_column(Enum(Strategy, name="strategy_enum"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

