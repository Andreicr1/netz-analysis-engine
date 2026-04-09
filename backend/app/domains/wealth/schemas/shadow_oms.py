"""Shadow OMS Pydantic schemas — Phase 9 Block D.

Request/response models for the execute-trades and actual-holdings
endpoints. All use Pydantic v2 ``model_validate()`` per CLAUDE.md.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# ── Execute Trades ────────────────────────────────────────────────


class TradeTicketRequest(BaseModel):
    """Single trade instruction within an execute-trades batch."""

    instrument_id: str
    action: str = Field(..., pattern="^(BUY|SELL)$")
    delta_weight: float = Field(..., gt=0, le=1.0)


class ExecuteTradesRequest(BaseModel):
    """Batch payload for POST /model-portfolios/{id}/execute-trades."""

    tickets: list[TradeTicketRequest] = Field(..., min_length=1, max_length=200)
    expected_version: int = Field(
        ...,
        description="Current holdings_version for optimistic locking. "
        "The request is rejected with 409 if it doesn't match.",
    )


class TradeTicketResponse(BaseModel):
    """Persisted trade ticket returned after execution."""

    id: str
    instrument_id: str
    action: str
    delta_weight: float
    executed_at: datetime
    execution_venue: str | None = None
    fill_status: str = "simulated"


class ExecuteTradesResponse(BaseModel):
    """Response for a successful execute-trades batch."""

    portfolio_id: str
    trades_executed: int
    tickets: list[TradeTicketResponse]
    message: str = "Trades executed successfully"


# ── Actual Holdings ───────────────────────────────────────────────


class HoldingWeight(BaseModel):
    """Single fund weight within actual holdings."""

    instrument_id: str
    fund_name: str
    instrument_type: str | None = None
    block_id: str
    weight: float
    score: float = 0.0


class ActualHoldingsResponse(BaseModel):
    """Response for GET /model-portfolios/{id}/actual-holdings."""

    portfolio_id: str
    source: str = Field(
        ...,
        description=(
            "'actual' when real holdings exist, 'target_fallback' when "
            "returning fund_selection_schema as zero-drift baseline"
        ),
    )
    holdings: list[HoldingWeight]
    last_rebalanced_at: datetime | None = None


# ── Trade Tickets Listing ────────────────────────────────────────


class TradeTicketPage(BaseModel):
    """Paginated response for GET /model-portfolios/{id}/trade-tickets."""

    items: list[TradeTicketResponse]
    total: int
    page: int
    page_size: int
    has_next: bool
