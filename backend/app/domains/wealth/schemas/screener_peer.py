from __future__ import annotations

from pydantic import BaseModel, Field


class PeerMetricRow(BaseModel):
    ticker: str
    name: str
    sharpe_ratio: float | None
    max_drawdown: float | None


class PeerMetricsResponse(BaseModel):
    fund_id: str
    strategy_label: str | None
    peer_count: int
    subject_sharpe: float | None
    subject_drawdown: float | None
    peer_sharpe_p25: float | None
    peer_sharpe_p50: float | None
    peer_sharpe_p75: float | None
    peer_drawdown_p25: float | None
    peer_drawdown_p50: float | None
    peer_drawdown_p75: float | None
    top_peers: list[PeerMetricRow] = Field(default_factory=list)
