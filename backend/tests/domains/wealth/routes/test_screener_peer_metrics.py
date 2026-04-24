from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.domains.wealth.routes.screener import _pct, get_peer_metrics, router
from app.domains.wealth.schemas.screener_peer import (
    PeerMetricRow,
    PeerMetricsResponse,
)


def test_peer_metrics_response_schema() -> None:
    resp = PeerMetricsResponse(
        fund_id="abc",
        strategy_label="Long/Short Equity",
        peer_count=12,
        subject_sharpe=1.2,
        subject_drawdown=-0.15,
        peer_sharpe_p25=0.8,
        peer_sharpe_p50=1.1,
        peer_sharpe_p75=1.4,
        peer_drawdown_p25=-0.22,
        peer_drawdown_p50=-0.14,
        peer_drawdown_p75=-0.08,
        top_peers=[
            PeerMetricRow(
                ticker="ABCX",
                name="ABC Fund",
                sharpe_ratio=1.3,
                max_drawdown=-0.12,
            ),
        ],
    )

    assert resp.peer_count == 12
    assert resp.subject_sharpe == 1.2
    assert len(resp.top_peers) == 1


def test_peer_metrics_empty_defaults() -> None:
    resp = PeerMetricsResponse(
        fund_id="xyz",
        strategy_label=None,
        peer_count=0,
        subject_sharpe=None,
        subject_drawdown=None,
        peer_sharpe_p25=None,
        peer_sharpe_p50=None,
        peer_sharpe_p75=None,
        peer_drawdown_p25=None,
        peer_drawdown_p50=None,
        peer_drawdown_p75=None,
    )

    assert resp.top_peers == []
    assert resp.strategy_label is None


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def fetchone(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[Any]:
        return self._rows


class _FakeSession:
    def __init__(self, results: list[_Result]) -> None:
        self._results = results
        self.calls: list[dict[str, Any] | None] = []

    async def execute(self, _statement: Any, params: dict[str, Any] | None = None) -> _Result:
        self.calls.append(params)
        return self._results.pop(0)


@pytest.mark.asyncio
async def test_peer_metrics_endpoint_responds_with_distribution() -> None:
    assert any(route.path == "/screener/peer-metrics/{fund_id}" for route in router.routes)

    db = _FakeSession(
        [
            _Result(
                [
                    SimpleNamespace(
                        instrument_id="00000000-0000-0000-0000-000000000001",
                        ticker="ABC",
                        name="ABC Fund",
                        strategy_label="Long/Short Equity",
                    ),
                ],
            ),
            _Result([SimpleNamespace(sharpe_1y=1.2, max_drawdown_1y=-0.15)]),
            _Result(
                [
                    SimpleNamespace(
                        ticker="AAA",
                        name="AAA Fund",
                        sharpe_1y=0.8,
                        max_drawdown_1y=-0.22,
                        manager_score=75,
                    ),
                    SimpleNamespace(
                        ticker="BBB",
                        name="BBB Fund",
                        sharpe_1y=1.1,
                        max_drawdown_1y=-0.14,
                        manager_score=95,
                    ),
                    SimpleNamespace(
                        ticker="CCC",
                        name="CCC Fund",
                        sharpe_1y=1.4,
                        max_drawdown_1y=-0.08,
                        manager_score=85,
                    ),
                ],
            ),
        ],
    )

    resp = await get_peer_metrics("abc", db=db, user=object())

    assert resp.peer_count == 3
    assert resp.subject_sharpe == 1.2
    assert resp.peer_sharpe_p50 == _pct([0.8, 1.1, 1.4], 50)
    assert resp.peer_drawdown_p50 == _pct([-0.22, -0.14, -0.08], 50)
    assert [peer.ticker for peer in resp.top_peers] == ["BBB", "CCC", "AAA"]
