"""Tests for quant_engine/peer_group_service.py — eVestment Section IV."""

from __future__ import annotations

import numpy as np
import pytest

from quant_engine.peer_group_service import (
    PeerGroupResult,
    compute_peer_rankings,
)

# ── Fixtures ──────────────────────────────────────────────────────────


def _make_fund_metrics(sharpe: float = 1.2, sortino: float = 1.5) -> dict:
    return {
        "sharpe_1y": sharpe,
        "sortino_1y": sortino,
        "return_1y": 0.12,
        "max_drawdown_1y": -0.08,
        "volatility_1y": 0.10,
        "alpha_1y": 0.02,
        "manager_score": 75.0,
    }


def _make_peer_metrics(n: int = 50, seed: int = 42) -> list[dict]:
    rng = np.random.RandomState(seed)
    peers = []
    for _ in range(n):
        peers.append({
            "sharpe_1y": float(rng.normal(0.8, 0.4)),
            "sortino_1y": float(rng.normal(1.0, 0.5)),
            "return_1y": float(rng.normal(0.08, 0.06)),
            "max_drawdown_1y": float(rng.normal(-0.12, 0.05)),
            "volatility_1y": float(rng.normal(0.12, 0.04)),
            "alpha_1y": float(rng.normal(0.0, 0.02)),
            "manager_score": float(rng.normal(60, 15)),
        })
    return peers


# ── Basic functionality ──────────────────────────────────────────────


class TestComputePeerRankings:
    def test_returns_result_type(self):
        result = compute_peer_rankings(
            fund_metrics=_make_fund_metrics(),
            peer_metrics=_make_peer_metrics(),
            strategy_label="Long/Short Equity",
        )
        assert isinstance(result, PeerGroupResult)

    def test_correct_number_of_rankings(self):
        result = compute_peer_rankings(
            fund_metrics=_make_fund_metrics(),
            peer_metrics=_make_peer_metrics(),
        )
        # Default metrics: sharpe, sortino, return, max_dd, vol, alpha, manager_score
        assert len(result.rankings) == 7

    def test_strategy_label_persisted(self):
        result = compute_peer_rankings(
            fund_metrics=_make_fund_metrics(),
            peer_metrics=_make_peer_metrics(),
            strategy_label="Global Macro",
        )
        assert result.strategy_label == "Global Macro"

    def test_peer_count(self):
        peers = _make_peer_metrics(n=30)
        result = compute_peer_rankings(
            fund_metrics=_make_fund_metrics(),
            peer_metrics=peers,
        )
        assert result.peer_count == 30


# ── Percentile and Quartile ──────────────────────────────────────────


class TestPercentileRanking:
    def test_top_performer_high_percentile(self):
        """A fund with sharpe=3.0 should rank above most peers."""
        fund = _make_fund_metrics(sharpe=3.0)
        peers = _make_peer_metrics(n=100)
        result = compute_peer_rankings(fund_metrics=fund, peer_metrics=peers)
        sharpe_ranking = next(r for r in result.rankings if r.metric_name == "sharpe_1y")
        assert sharpe_ranking.percentile >= 90.0

    def test_bottom_performer_low_percentile(self):
        """A fund with sharpe=-1.0 should rank below most peers."""
        fund = _make_fund_metrics(sharpe=-1.0)
        peers = _make_peer_metrics(n=100)
        result = compute_peer_rankings(fund_metrics=fund, peer_metrics=peers)
        sharpe_ranking = next(r for r in result.rankings if r.metric_name == "sharpe_1y")
        assert sharpe_ranking.percentile <= 20.0

    def test_percentile_range(self):
        """All percentiles should be in [0, 100]."""
        result = compute_peer_rankings(
            fund_metrics=_make_fund_metrics(),
            peer_metrics=_make_peer_metrics(),
        )
        for r in result.rankings:
            assert 0.0 <= r.percentile <= 100.0

    def test_quartile_from_percentile(self):
        """Quartile should match percentile bracket."""
        result = compute_peer_rankings(
            fund_metrics=_make_fund_metrics(),
            peer_metrics=_make_peer_metrics(),
        )
        for r in result.rankings:
            if r.percentile >= 75:
                assert r.quartile == 1
            elif r.percentile >= 50:
                assert r.quartile == 2
            elif r.percentile >= 25:
                assert r.quartile == 3
            else:
                assert r.quartile == 4


# ── Lower-is-better metrics ─────────────────────────────────────────


class TestLowerIsBetter:
    def test_low_drawdown_high_rank(self):
        """Fund with low max_drawdown (-0.02) should rank well (higher percentile)."""
        fund = {"max_drawdown_1y": -0.02, "sharpe_1y": 1.0, "sortino_1y": 1.0,
                "return_1y": 0.1, "volatility_1y": 0.08, "alpha_1y": 0.01, "manager_score": 70.0}
        peers = _make_peer_metrics(n=50)
        result = compute_peer_rankings(fund_metrics=fund, peer_metrics=peers)
        dd_ranking = next(r for r in result.rankings if r.metric_name == "max_drawdown_1y")
        # -0.02 is better than peer average of -0.12, so percentile should be high
        assert dd_ranking.percentile >= 70.0

    def test_low_volatility_high_rank(self):
        """Fund with very low volatility should rank well."""
        fund = {"volatility_1y": 0.03, "sharpe_1y": 1.0, "sortino_1y": 1.0,
                "return_1y": 0.1, "max_drawdown_1y": -0.05, "alpha_1y": 0.01, "manager_score": 70.0}
        peers = _make_peer_metrics(n=50)
        result = compute_peer_rankings(fund_metrics=fund, peer_metrics=peers)
        vol_ranking = next(r for r in result.rankings if r.metric_name == "volatility_1y")
        assert vol_ranking.percentile >= 70.0


# ── Edge Cases ───────────────────────────────────────────────────────


class TestEdgeCases:
    def test_no_peers(self):
        result = compute_peer_rankings(
            fund_metrics=_make_fund_metrics(),
            peer_metrics=[],
            strategy_label="Empty",
        )
        assert result.peer_count == 0
        assert len(result.rankings) == 7

    def test_fund_metric_none(self):
        """Fund with None metric should still produce ranking (value=None)."""
        fund = {**_make_fund_metrics(), "sharpe_1y": None}
        result = compute_peer_rankings(
            fund_metrics=fund,
            peer_metrics=_make_peer_metrics(),
        )
        sharpe_r = next(r for r in result.rankings if r.metric_name == "sharpe_1y")
        assert sharpe_r.value is None

    def test_peer_all_none_for_metric(self):
        """If all peers have None for a metric, peer stats should still work."""
        peers = [{"sharpe_1y": None, "sortino_1y": 1.0, "return_1y": 0.1,
                  "max_drawdown_1y": -0.1, "volatility_1y": 0.1, "alpha_1y": 0.0,
                  "manager_score": 60.0} for _ in range(10)]
        result = compute_peer_rankings(
            fund_metrics=_make_fund_metrics(),
            peer_metrics=peers,
        )
        sharpe_r = next(r for r in result.rankings if r.metric_name == "sharpe_1y")
        assert sharpe_r.peer_count == 0

    def test_custom_metrics(self):
        """Custom metrics_to_rank should be respected."""
        result = compute_peer_rankings(
            fund_metrics=_make_fund_metrics(),
            peer_metrics=_make_peer_metrics(),
            metrics_to_rank=["sharpe_1y", "return_1y"],
        )
        assert len(result.rankings) == 2
        assert result.rankings[0].metric_name == "sharpe_1y"
        assert result.rankings[1].metric_name == "return_1y"

    def test_frozen_dataclass(self):
        result = compute_peer_rankings(
            fund_metrics=_make_fund_metrics(),
            peer_metrics=_make_peer_metrics(),
        )
        with pytest.raises(AttributeError):
            result.peer_count = 0  # type: ignore[misc]

    def test_peer_median_between_p25_and_p75(self):
        """Peer median should be between P25 and P75."""
        result = compute_peer_rankings(
            fund_metrics=_make_fund_metrics(),
            peer_metrics=_make_peer_metrics(n=100),
        )
        for r in result.rankings:
            if r.peer_count > 0:
                assert r.peer_p25 <= r.peer_median + 1e-6
                assert r.peer_median <= r.peer_p75 + 1e-6
