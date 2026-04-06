"""Market Data WebSocket schemas.

Defines the wire format for real-time price ticks over WebSocket
and the client→server subscription protocol.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Client → Server messages ────────────────────────────────


class SubscribeRequest(BaseModel):
    """Client subscribes to a set of tickers."""

    action: Literal["subscribe"] = "subscribe"
    tickers: list[str] = Field(..., min_length=1, max_length=50)


class UnsubscribeRequest(BaseModel):
    """Client unsubscribes from specific tickers."""

    action: Literal["unsubscribe"] = "unsubscribe"
    tickers: list[str] = Field(..., min_length=1)


class PingRequest(BaseModel):
    """Client heartbeat ping."""

    action: Literal["ping"] = "ping"


# ── Server → Client messages ────────────────────────────────


class PriceTick(BaseModel):
    """Single price update for one instrument.

    Published by workers to ``market:prices`` Redis channel.
    Forwarded to subscribed WebSocket clients.
    """

    model_config = ConfigDict(from_attributes=True)

    ticker: str
    price: Decimal = Field(..., description="Latest price (adjusted close for EOD)")
    change: Decimal = Field(default=Decimal("0"), description="Absolute change from previous close")
    change_pct: Decimal = Field(default=Decimal("0"), description="Percentage change from previous close")
    volume: int | None = Field(default=None, description="Trade volume (null for mutual funds)")
    aum_usd: Decimal | None = Field(default=None, description="AUM in USD (from nav_timeseries)")
    timestamp: str = Field(..., description="ISO-8601 timestamp of this tick")
    source: str = Field(default="db", description="Data source: db | tiingo | yahoo")


class PortfolioHoldingSummary(BaseModel):
    """Enriched holding for the dashboard — price + instrument metadata."""

    model_config = ConfigDict(from_attributes=True)

    instrument_id: str
    ticker: str
    name: str
    price: Decimal
    change: Decimal = Decimal("0")
    change_pct: Decimal = Decimal("0")
    weight: Decimal = Decimal("0")
    aum_usd: Decimal | None = None
    asset_class: str = ""
    currency: str = "USD"


class WsServerMessage(BaseModel):
    """Envelope for all server→client WebSocket messages."""

    type: Literal["price", "snapshot", "pong", "error", "subscribed"]
    data: dict | list | None = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


# ── REST schemas (dashboard SSR) ────────────────────────────


class DashboardSnapshot(BaseModel):
    """Full dashboard snapshot for SSR initial load."""

    holdings: list[PortfolioHoldingSummary]
    total_aum: Decimal
    total_return_pct: Decimal | None = None
    as_of: str = Field(..., description="ISO-8601 timestamp of the latest data point")


# ── Portfolio Holdings (tax-lot aware) ─────────────────────


class Position(BaseModel):
    """Single position in a portfolio — cost-basis aware for P&L."""

    model_config = ConfigDict(from_attributes=True)

    instrument_id: str
    ticker: str
    name: str
    asset_class: str = ""
    currency: str = "USD"

    # Static fields (from model portfolio + nav_timeseries)
    weight: Decimal = Field(..., description="Allocation weight 0.0-1.0")
    quantity: Decimal = Field(default=Decimal("0"), description="Notional units (weight * portfolio_nav / price)")
    avg_cost: Decimal = Field(default=Decimal("0"), description="Average cost basis per unit")

    # Pricing
    last_price: Decimal = Field(default=Decimal("0"), description="Latest NAV/price")
    previous_close: Decimal = Field(default=Decimal("0"), description="Previous trading day close")
    price_date: str | None = None

    # AUM
    aum_usd: Decimal | None = None


class PortfolioHoldingsResponse(BaseModel):
    """Response for GET /portfolio/{id}/holdings."""

    portfolio_id: str
    profile: str
    holdings: list[Position]
    cash_balance: Decimal = Decimal("0")
    portfolio_nav: Decimal = Decimal("0")
    as_of: str


# ── Screener Asset Catalog ─────────────────────────────────


class ScreenerAsset(BaseModel):
    """Single asset row in the live screener catalog."""

    model_config = ConfigDict(from_attributes=True)

    external_id: str
    ticker: str | None = None
    name: str
    asset_class: str = ""
    region: str = ""
    fund_type: str = ""
    strategy_label: str | None = None
    currency: str | None = None

    # Static metrics
    aum: Decimal | None = None
    expense_ratio_pct: Decimal | None = None
    inception_date: str | None = None

    # Latest price (for SSR seed — live updates come via WS)
    last_price: Decimal | None = None
    change: Decimal | None = None
    change_pct: Decimal | None = None


class ScreenerAssetPage(BaseModel):
    """Paginated response for GET /screener/catalog/assets."""

    items: list[ScreenerAsset]
    total: int
    page: int
    page_size: int
    has_next: bool
