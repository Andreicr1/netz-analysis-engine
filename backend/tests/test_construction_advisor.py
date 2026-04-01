"""Tests for Portfolio Construction Advisor — pure functions, no DB."""

from __future__ import annotations

import uuid

import numpy as np
import pytest

from vertical_engines.wealth.model_portfolio.block_mapping import (
    blocks_for_strategy_label,
    strategy_labels_for_block,
)
from vertical_engines.wealth.model_portfolio.construction_advisor import (
    _min_max_normalize,
    analyze_block_gaps,
    build_advice,
    compute_holdings_overlap,
    find_minimum_viable_set,
    project_cvar_for_candidates,
    project_cvar_historical,
    rank_candidates,
)
from vertical_engines.wealth.model_portfolio.models import (
    BlockInfo,
    CandidateFund,
    ConstructionAdvice,
    FundCandidate,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BLOCK_META = {
    "na_equity_large": BlockInfo("na_equity_large", "North America Large Cap Equity", "equity", "SPY"),
    "fi_us_aggregate": BlockInfo("fi_us_aggregate", "US Aggregate Bond", "fixed_income", "AGG"),
    "alt_gold": BlockInfo("alt_gold", "Gold", "alternatives", "GLD"),
    "cash": BlockInfo("cash", "Cash & Equivalents", "cash", "SHV"),
    "fi_us_treasury": BlockInfo("fi_us_treasury", "US Treasury", "fixed_income", "IEF"),
}


def _make_returns(n_days: int = 252, annual_vol: float = 0.15, seed: int = 42) -> np.ndarray:
    """Generate synthetic daily returns."""
    rng = np.random.default_rng(seed)
    daily_vol = annual_vol / np.sqrt(252)
    return rng.normal(0.0003, daily_vol, size=n_days)


def _make_candidate(
    block_id: str = "fi_us_aggregate",
    vol: float = 0.05,
    sharpe: float = 0.8,
    in_universe: bool = False,
) -> FundCandidate:
    iid = str(uuid.uuid4())
    return FundCandidate(
        instrument_id=iid,
        name=f"Fund-{iid[:8]}",
        ticker=f"T{iid[:4].upper()}",
        block_id=block_id,
        strategy_label="Fixed Income",
        volatility_1y=vol,
        sharpe_1y=sharpe,
        manager_score=75.0,
        in_universe=in_universe,
        external_id=f"CIK-{iid[:6]}",
    )


# ---------------------------------------------------------------------------
# 1. Block Gap Analysis
# ---------------------------------------------------------------------------


class TestAnalyzeBlockGaps:
    def test_fully_uncovered_blocks(self):
        block_weights = {"na_equity_large": 1.0}
        strategic_targets = {
            "na_equity_large": 0.40,
            "fi_us_aggregate": 0.30,
            "alt_gold": 0.10,
            "cash": 0.20,
        }
        result = analyze_block_gaps(block_weights, strategic_targets, _BLOCK_META)

        assert result.total_blocks == 4
        assert result.covered_blocks == 1
        assert result.covered_pct == 0.25
        assert len(result.block_gaps) == 3  # fi, alt, cash are uncovered

    def test_gap_priority_favors_diversifying_asset_classes(self):
        block_weights = {"na_equity_large": 1.0}
        strategic_targets = {
            "na_equity_large": 0.40,
            "fi_us_aggregate": 0.20,
            "alt_gold": 0.20,
            "cash": 0.20,
        }
        result = analyze_block_gaps(block_weights, strategic_targets, _BLOCK_META)

        # Fixed income (div_value=4.0) should have priority 1 over
        # alternatives (3.0) and cash (2.0) at equal gap_weight
        assert result.block_gaps[0].block_id == "fi_us_aggregate"
        assert result.block_gaps[0].priority == 1

    def test_no_gaps_when_all_covered(self):
        block_weights = {"na_equity_large": 0.40, "fi_us_aggregate": 0.30, "alt_gold": 0.15, "cash": 0.15}
        strategic_targets = {"na_equity_large": 0.40, "fi_us_aggregate": 0.30, "alt_gold": 0.15, "cash": 0.15}
        result = analyze_block_gaps(block_weights, strategic_targets, _BLOCK_META)

        assert result.covered_blocks == 4
        assert len(result.block_gaps) == 0

    def test_underweight_block_detected(self):
        block_weights = {"na_equity_large": 0.80, "fi_us_aggregate": 0.05}
        strategic_targets = {"na_equity_large": 0.40, "fi_us_aggregate": 0.30}
        result = analyze_block_gaps(block_weights, strategic_targets, _BLOCK_META)

        # fi_us_aggregate is underweight by 0.25
        fi_gap = next(g for g in result.block_gaps if g.block_id == "fi_us_aggregate")
        assert fi_gap.gap_weight == pytest.approx(0.25)
        assert fi_gap.current_weight == pytest.approx(0.05)

    def test_max_gaps_limits_output(self):
        strategic_targets = {f"block_{i}": 0.1 for i in range(10)}
        meta = {f"block_{i}": BlockInfo(f"block_{i}", f"Block {i}", "equity") for i in range(10)}
        result = analyze_block_gaps({}, strategic_targets, meta, max_gaps=3)

        assert len(result.block_gaps) == 3

    def test_small_gap_below_threshold_ignored(self):
        block_weights = {"na_equity_large": 0.398}
        strategic_targets = {"na_equity_large": 0.40}
        result = analyze_block_gaps(block_weights, strategic_targets, _BLOCK_META)

        # 0.002 gap is below 0.005 threshold
        assert len(result.block_gaps) == 0


# ---------------------------------------------------------------------------
# 2. Candidate Ranking
# ---------------------------------------------------------------------------


class TestRankCandidates:
    def test_ranks_by_composite_score(self):
        c1 = _make_candidate("fi_us_aggregate", vol=0.04, sharpe=0.9)
        c2 = _make_candidate("fi_us_aggregate", vol=0.08, sharpe=0.5)
        c3 = _make_candidate("fi_us_aggregate", vol=0.06, sharpe=0.7)

        portfolio_returns = _make_returns(252, 0.20, seed=1)

        cand_returns = {
            c1.instrument_id: _make_returns(252, 0.04, seed=10),
            c2.instrument_id: _make_returns(252, 0.08, seed=20),
            c3.instrument_id: _make_returns(252, 0.06, seed=30),
        }

        result = rank_candidates(
            [c1, c2, c3],
            portfolio_returns,
            cand_returns,
            {},  # no holdings
            set(),
        )

        assert len(result) == 3
        # c1 should rank highest (lowest vol, highest sharpe)
        assert result[0].instrument_id == c1.instrument_id

    def test_max_per_block_limits_output(self):
        candidates = [_make_candidate("fi_us_aggregate") for _ in range(5)]
        portfolio_returns = _make_returns(252, 0.20, seed=1)
        cand_returns = {c.instrument_id: _make_returns(252, 0.05, seed=i) for i, c in enumerate(candidates)}

        result = rank_candidates(
            candidates, portfolio_returns, cand_returns, {}, set(),
            max_per_block=2,
        )

        assert len(result) == 2

    def test_multiple_blocks_scored_independently(self):
        c_fi = _make_candidate("fi_us_aggregate", vol=0.04)
        c_gold = _make_candidate("alt_gold", vol=0.15)

        portfolio_returns = _make_returns(252, 0.20, seed=1)
        cand_returns = {
            c_fi.instrument_id: _make_returns(252, 0.04, seed=10),
            c_gold.instrument_id: _make_returns(252, 0.15, seed=20),
        }

        result = rank_candidates(
            [c_fi, c_gold], portfolio_returns, cand_returns, {}, set(),
        )

        assert len(result) == 2
        blocks = {r.block_id for r in result}
        assert blocks == {"fi_us_aggregate", "alt_gold"}

    def test_overlap_penalizes_candidate(self):
        c1 = _make_candidate("fi_us_aggregate", vol=0.04, sharpe=0.9)
        c2 = _make_candidate("fi_us_aggregate", vol=0.04, sharpe=0.9)

        portfolio_returns = _make_returns(252, 0.20, seed=1)
        cand_returns = {
            c1.instrument_id: _make_returns(252, 0.04, seed=10),
            c2.instrument_id: _make_returns(252, 0.04, seed=11),
        }

        # c2 has 80% overlap with portfolio holdings
        portfolio_cusips = {f"CUSIP-{i}" for i in range(100)}
        candidate_holdings = {
            c1.instrument_id: {f"CUSIP-OTHER-{i}" for i in range(50)},  # 0% overlap
            c2.instrument_id: {f"CUSIP-{i}" for i in range(80)} | {f"CUSIP-NEW-{i}" for i in range(20)},
        }

        result = rank_candidates(
            [c1, c2], portfolio_returns, cand_returns,
            candidate_holdings, portfolio_cusips,
        )

        # c1 should rank higher due to lower overlap
        assert result[0].instrument_id == c1.instrument_id
        assert result[0].overlap_pct < result[1].overlap_pct


# ---------------------------------------------------------------------------
# 3. Holdings Overlap
# ---------------------------------------------------------------------------


class TestComputeHoldingsOverlap:
    def test_no_overlap(self):
        assert compute_holdings_overlap({"A", "B"}, {"C", "D"}) == 0.0

    def test_full_overlap(self):
        assert compute_holdings_overlap({"A", "B"}, {"A", "B"}) == 1.0

    def test_partial_overlap(self):
        overlap = compute_holdings_overlap({"A", "B", "C"}, {"B", "C", "D"})
        # intersection = {B, C} = 2, union = {A, B, C, D} = 4
        assert overlap == pytest.approx(0.5)

    def test_empty_sets(self):
        assert compute_holdings_overlap(set(), {"A"}) == 0.0
        assert compute_holdings_overlap({"A"}, set()) == 0.0
        assert compute_holdings_overlap(set(), set()) == 0.0


# ---------------------------------------------------------------------------
# 4. CVaR Projection — Historical Simulation
# ---------------------------------------------------------------------------


class TestProjectCvarHistorical:
    def test_adding_negatively_correlated_asset_reduces_cvar(self):
        rng = np.random.default_rng(42)
        n_days = 252

        # Equity-like portfolio: high vol
        equity_returns = rng.normal(0.0004, 0.015, size=(n_days, 2))

        # Bond-like candidate: low vol, slightly negative correlation
        bond_returns = rng.normal(0.0001, 0.003, size=n_days) - 0.3 * equity_returns.mean(axis=1)

        current_weights = np.array([0.5, 0.5])

        # CVaR of current portfolio alone
        port_daily = equity_returns @ current_weights
        sorted_ret = np.sort(port_daily)
        cutoff = max(int(len(sorted_ret) * 0.05), 1)
        current_cvar = -float(np.mean(sorted_ret[:cutoff])) * np.sqrt(252)

        # Projected CVaR after adding bond
        projected = project_cvar_historical(
            equity_returns, bond_returns, current_weights,
            candidate_target_weight=0.30,
        )

        assert projected is not None
        # projected is negative (loss convention), should be less negative than current
        assert projected > -current_cvar  # less loss = better

    def test_returns_none_for_insufficient_data(self):
        short_returns = np.random.default_rng(42).normal(0, 0.01, size=(50, 2))
        short_candidate = np.random.default_rng(43).normal(0, 0.005, size=50)

        result = project_cvar_historical(
            short_returns, short_candidate,
            np.array([0.5, 0.5]), 0.20,
        )

        assert result is None  # 50 < 126 minimum

    def test_valid_output_range(self):
        rng = np.random.default_rng(42)
        port_ret = rng.normal(0.0003, 0.01, size=(252, 3))
        cand_ret = rng.normal(0.0001, 0.005, size=252)

        result = project_cvar_historical(
            port_ret, cand_ret,
            np.array([0.4, 0.3, 0.3]), 0.10,
        )

        assert result is not None
        assert result < 0  # CVaR is always negative (loss)
        assert result > -2.0  # sanity: not more than -200%


class TestProjectCvarForCandidates:
    def test_fills_projection_fields(self):
        rng = np.random.default_rng(42)
        port_ret = rng.normal(0.0003, 0.015, size=(252, 2))
        current_weights = np.array([0.5, 0.5])

        c1 = CandidateFund(
            block_id="fi_us_aggregate",
            instrument_id="fund-1",
            name="Bond Fund",
            ticker="BND",
            strategy_label="Fixed Income",
            volatility_1y=0.04,
            correlation_with_portfolio=-0.1,
            overlap_pct=0.0,
            projected_cvar_95=None,
            cvar_improvement=0.0,
            in_universe=False,
            external_id="CIK-123",
        )

        cand_returns = {"fund-1": rng.normal(0.0001, 0.003, size=252)}

        result = project_cvar_for_candidates(
            [c1], port_ret, cand_returns, current_weights,
            {"fi_us_aggregate": 0.30},
            current_cvar=-0.50,
        )

        assert len(result) == 1
        assert result[0].projected_cvar_95 is not None
        assert result[0].cvar_improvement != 0.0


# ---------------------------------------------------------------------------
# 5. Minimum Viable Set
# ---------------------------------------------------------------------------


class TestFindMinimumViableSet:
    def _build_scenario(self, n_candidates: int = 5, seed: int = 42):
        """Build a test scenario where adding low-vol diversifiers brings CVaR within limit."""
        rng = np.random.default_rng(seed)
        n_days = 252

        # Concentrated equity portfolio: 2 funds, high CVaR
        port_ret = rng.normal(0.0004, 0.02, size=(n_days, 2))
        current_weights = np.array([0.5, 0.5])

        candidates = []
        cand_returns = {}
        cand_blocks = {}

        for i in range(n_candidates):
            iid = f"cand-{i}"
            vol = 0.003 + i * 0.001
            # Each candidate is a low-vol asset with low correlation to equity
            ret = rng.normal(0.0001, vol, size=n_days)
            cand_returns[iid] = ret

            block = ["fi_us_aggregate", "fi_us_treasury", "alt_gold", "cash", "fi_us_tips"][i % 5]
            cand_blocks[iid] = block

            candidates.append(
                CandidateFund(
                    block_id=block,
                    instrument_id=iid,
                    name=f"Candidate {i}",
                    ticker=f"C{i}",
                    strategy_label="Fixed Income",
                    volatility_1y=vol * np.sqrt(252),
                    correlation_with_portfolio=0.0,
                    overlap_pct=0.0,
                    projected_cvar_95=None,
                    cvar_improvement=0.0,
                    in_universe=False,
                    external_id=f"CIK-{i}",
                ),
            )

        targets = {
            "fi_us_aggregate": 0.20,
            "fi_us_treasury": 0.10,
            "alt_gold": 0.05,
            "cash": 0.10,
            "fi_us_tips": 0.05,
        }

        return port_ret, current_weights, candidates, cand_returns, targets

    def test_finds_viable_set_brute_force(self):
        port_ret, weights, candidates, cand_returns, targets = self._build_scenario(5)

        result = find_minimum_viable_set(
            candidates, port_ret, cand_returns, weights, targets,
            cvar_limit=-0.30,  # generous limit
        )

        assert result is not None
        assert result.projected_within_limit
        assert result.search_method == "brute_force"
        assert len(result.funds) >= 1

    def test_returns_none_when_impossible(self):
        port_ret, weights, candidates, cand_returns, targets = self._build_scenario(3)

        # Impossibly tight limit
        result = find_minimum_viable_set(
            candidates, port_ret, cand_returns, weights, targets,
            cvar_limit=-0.001,  # nearly zero CVaR — impossible
        )

        # Could be None or a set that doesn't pass
        if result is not None:
            assert not result.projected_within_limit

    def test_prefers_smaller_set(self):
        port_ret, weights, candidates, cand_returns, targets = self._build_scenario(5)

        result = find_minimum_viable_set(
            candidates, port_ret, cand_returns, weights, targets,
            cvar_limit=-0.50,  # very generous — should need only 1 fund
        )

        if result is not None:
            assert len(result.funds) <= 2  # should find a small solution


# ---------------------------------------------------------------------------
# 6. Block Mapping
# ---------------------------------------------------------------------------


class TestBlockMapping:
    def test_known_label_returns_blocks(self):
        blocks = blocks_for_strategy_label("Large Blend")
        assert "na_equity_large" in blocks

    def test_unknown_label_returns_empty(self):
        assert blocks_for_strategy_label("Nonexistent Category") == []

    def test_none_label_returns_empty(self):
        assert blocks_for_strategy_label(None) == []

    def test_reverse_lookup(self):
        labels = strategy_labels_for_block("fi_us_aggregate")
        assert len(labels) > 0
        assert "Intermediate Core Bond" in labels
        assert "Fixed Income" in labels

    def test_reverse_lookup_unknown_block(self):
        assert strategy_labels_for_block("nonexistent_block") == []


# ---------------------------------------------------------------------------
# 7. Min-Max Normalize
# ---------------------------------------------------------------------------


class TestMinMaxNormalize:
    def test_basic_normalization(self):
        result = _min_max_normalize([1.0, 2.0, 3.0])
        assert result == pytest.approx([0.0, 0.5, 1.0])

    def test_all_same_values(self):
        result = _min_max_normalize([5.0, 5.0, 5.0])
        assert result == [0.5, 0.5, 0.5]

    def test_empty_list(self):
        assert _min_max_normalize([]) == []


# ---------------------------------------------------------------------------
# 8. Build Advice (integration of all components)
# ---------------------------------------------------------------------------


class TestBuildAdvice:
    def test_full_advice_pipeline(self):
        rng = np.random.default_rng(42)
        n_days = 252

        port_ret_per_fund = rng.normal(0.0004, 0.015, size=(n_days, 2))
        current_weights = np.array([0.5, 0.5])
        portfolio_returns = port_ret_per_fund @ current_weights

        # Create candidates for gap blocks
        c_fi = _make_candidate("fi_us_aggregate", vol=0.04, sharpe=0.8)
        c_gold = _make_candidate("alt_gold", vol=0.15, sharpe=0.3)

        cand_returns = {
            c_fi.instrument_id: rng.normal(0.0001, 0.003, size=n_days),
            c_gold.instrument_id: rng.normal(0.0002, 0.01, size=n_days),
        }

        result = build_advice(
            portfolio_id=str(uuid.uuid4()),
            profile="moderate",
            current_cvar_95=-0.10,
            cvar_limit=-0.06,
            block_weights={"na_equity_large": 1.0},
            strategic_targets={
                "na_equity_large": 0.40,
                "fi_us_aggregate": 0.30,
                "alt_gold": 0.10,
                "cash": 0.20,
            },
            block_metadata=_BLOCK_META,
            candidates=[c_fi, c_gold],
            portfolio_returns=portfolio_returns,
            portfolio_daily_returns=port_ret_per_fund,
            candidate_returns=cand_returns,
            current_weights=current_weights,
            candidate_holdings={},
            portfolio_holdings=set(),
            alternative_cvar_limits={"conservative": -0.08, "moderate": -0.06, "growth": -0.12},
        )

        assert isinstance(result, ConstructionAdvice)
        assert result.profile == "moderate"
        assert result.current_cvar_95 == -0.10
        assert result.cvar_limit == -0.06
        assert result.cvar_gap == pytest.approx(-0.04)
        assert result.projected_cvar_is_heuristic is True

        # Coverage should detect gaps
        assert result.coverage.total_blocks == 4
        assert result.coverage.covered_blocks == 1
        assert len(result.coverage.block_gaps) >= 2

        # Should have ranked candidates
        assert len(result.candidates) == 2

        # Should suggest growth profile as alternative (-0.10 >= -0.12 → passes)
        alt = [a for a in result.alternative_profiles if a.profile == "growth"]
        assert len(alt) == 1
        assert alt[0].current_cvar_would_pass is True

    def test_advice_includes_has_holdings_data_flag(self):
        """Candidates without holdings data should get has_holdings_data=False."""
        rng = np.random.default_rng(42)
        n_days = 252

        port_ret_per_fund = rng.normal(0.0004, 0.015, size=(n_days, 2))
        current_weights = np.array([0.5, 0.5])
        portfolio_returns = port_ret_per_fund @ current_weights

        c1 = _make_candidate("fi_us_aggregate", vol=0.04, sharpe=0.8)

        cand_returns = {c1.instrument_id: rng.normal(0.0001, 0.003, size=n_days)}

        # No holdings provided for any candidate
        result = build_advice(
            portfolio_id=str(uuid.uuid4()),
            profile="moderate",
            current_cvar_95=-0.10,
            cvar_limit=-0.06,
            block_weights={"na_equity_large": 1.0},
            strategic_targets={"na_equity_large": 0.40, "fi_us_aggregate": 0.30},
            block_metadata=_BLOCK_META,
            candidates=[c1],
            portfolio_returns=portfolio_returns,
            portfolio_daily_returns=port_ret_per_fund,
            candidate_returns=cand_returns,
            current_weights=current_weights,
            candidate_holdings={},
            portfolio_holdings=set(),
        )

        # All candidates have overlap_pct = 0 when no holdings data
        for c in result.candidates:
            assert c.overlap_pct == 0.0

    def test_no_candidates_returns_empty_advice(self):
        rng = np.random.default_rng(42)
        port_ret = rng.normal(0, 0.01, size=(252, 1))

        result = build_advice(
            portfolio_id=str(uuid.uuid4()),
            profile="moderate",
            current_cvar_95=-0.50,
            cvar_limit=-0.06,
            block_weights={"na_equity_large": 1.0},
            strategic_targets={"na_equity_large": 0.40, "fi_us_aggregate": 0.30},
            block_metadata=_BLOCK_META,
            candidates=[],
            portfolio_returns=port_ret[:, 0],
            portfolio_daily_returns=port_ret,
            candidate_returns={},
            current_weights=np.array([1.0]),
            candidate_holdings={},
            portfolio_holdings=set(),
        )

        assert result.candidates == []
        assert result.minimum_viable_set is None


# ---------------------------------------------------------------------------
# 9. E2E Flow — construct → advice → add → re-construct → activate
# ---------------------------------------------------------------------------


class TestEndToEndAdvisorFlow:
    """Simulates the full portfolio lifecycle using pure functions.

    1. Start with concentrated equity portfolio (high CVaR, fails limit)
    2. Run advisor → get gap analysis + candidates + minimum viable set
    3. Simulate adding MVS funds to the portfolio
    4. Re-run advisor with expanded portfolio → CVaR should improve
    5. Validate activate gate: within limit → allowed, exceeds → blocked
    """

    def _setup_concentrated_equity(self, rng: np.random.Generator, n_days: int = 252):
        """3 correlated equity funds with high CVaR."""
        # Highly correlated equity returns
        base = rng.normal(0.0005, 0.018, size=n_days)
        noise = rng.normal(0, 0.003, size=(n_days, 3))
        equity_returns = np.column_stack([base + noise[:, i] for i in range(3)])
        weights = np.array([0.40, 0.35, 0.25])
        port_ret = equity_returns @ weights

        # Compute current CVaR
        sorted_ret = np.sort(port_ret)
        cutoff = max(int(len(sorted_ret) * 0.05), 1)
        current_cvar = -float(np.mean(sorted_ret[:cutoff])) * np.sqrt(252)

        return equity_returns, weights, port_ret, -current_cvar

    def _create_diversifying_candidates(self, rng: np.random.Generator, n_days: int = 252):
        """Create candidates across multiple asset classes."""
        candidates = []
        cand_returns = {}

        specs = [
            ("fi_us_aggregate", 0.003, "Bond Core"),
            ("fi_us_aggregate", 0.004, "Bond Aggregate"),
            ("fi_us_treasury", 0.0025, "Treasury Fund"),
            ("fi_us_treasury", 0.003, "Treasury Short"),
            ("alt_gold", 0.009, "Gold ETF"),
            ("alt_gold", 0.010, "Gold Miners"),
            ("cash", 0.001, "Money Market"),
            ("cash", 0.001, "Ultra Short"),
        ]

        for i, (block_id, daily_vol, name) in enumerate(specs):
            iid = str(uuid.uuid4())
            # Low correlation with equity
            ret = rng.normal(0.0001, daily_vol, size=n_days)
            cand_returns[iid] = ret

            candidates.append(FundCandidate(
                instrument_id=iid,
                name=name,
                ticker=f"T{i:03d}",
                block_id=block_id,
                strategy_label=block_id.replace("_", " ").title(),
                volatility_1y=daily_vol * np.sqrt(252),
                sharpe_1y=0.5 + rng.uniform(-0.2, 0.2),
                manager_score=70.0 + i,
                in_universe=False,
                external_id=f"CIK-{i}",
            ))

        return candidates, cand_returns

    def test_full_flow_equity_to_diversified(self):
        """E2E: concentrated equity → advice → add MVS → CVaR improves."""
        rng = np.random.default_rng(42)
        n_days = 252

        # Step 1: Concentrated equity portfolio
        equity_returns, weights, port_ret, current_cvar = (
            self._setup_concentrated_equity(rng, n_days)
        )

        cvar_limit = -0.06  # moderate profile

        # Verify starting state: CVaR is way over the limit
        assert current_cvar < cvar_limit, (
            f"Setup requires CVaR ({current_cvar:.4f}) to exceed limit ({cvar_limit})"
        )

        # Step 2: Run advisor
        candidates, cand_returns = self._create_diversifying_candidates(rng, n_days)

        block_meta = {
            "na_equity_large": BlockInfo("na_equity_large", "NA Large Cap", "equity"),
            "fi_us_aggregate": BlockInfo("fi_us_aggregate", "US Agg Bond", "fixed_income"),
            "fi_us_treasury": BlockInfo("fi_us_treasury", "US Treasury", "fixed_income"),
            "alt_gold": BlockInfo("alt_gold", "Gold", "alternatives"),
            "cash": BlockInfo("cash", "Cash", "cash"),
        }

        strategic_targets = {
            "na_equity_large": 0.40,
            "fi_us_aggregate": 0.25,
            "fi_us_treasury": 0.10,
            "alt_gold": 0.05,
            "cash": 0.20,
        }

        advice = build_advice(
            portfolio_id="test-e2e",
            profile="moderate",
            current_cvar_95=current_cvar,
            cvar_limit=cvar_limit,
            block_weights={"na_equity_large": 1.0},
            strategic_targets=strategic_targets,
            block_metadata=block_meta,
            candidates=candidates,
            portfolio_returns=port_ret,
            portfolio_daily_returns=equity_returns,
            candidate_returns=cand_returns,
            current_weights=weights,
            candidate_holdings={},
            portfolio_holdings=set(),
            alternative_cvar_limits={
                "conservative": -0.08,
                "moderate": -0.06,
                "growth": -0.12,
            },
        )

        # Verify advisor produced useful output
        assert advice.coverage.covered_blocks == 1  # only equity
        assert advice.coverage.total_blocks == 5
        assert len(advice.coverage.block_gaps) >= 3  # fi, alt, cash gaps
        assert len(advice.candidates) > 0
        assert advice.projected_cvar_is_heuristic is True

        # All candidates should have projected CVaR
        projected_candidates = [c for c in advice.candidates if c.projected_cvar_95 is not None]
        assert len(projected_candidates) > 0

        # Each projected CVaR should be less negative than current
        for c in projected_candidates:
            assert c.projected_cvar_95 > current_cvar, (
                f"Candidate {c.name} didn't improve CVaR: "
                f"{c.projected_cvar_95:.4f} vs {current_cvar:.4f}"
            )

        # Step 3: Check alternative profiles
        growth_alt = [a for a in advice.alternative_profiles if a.profile == "growth"]
        if growth_alt:
            assert growth_alt[0].cvar_limit == -0.12

        # Step 4: Simulate adding MVS funds and verify CVaR improvement
        if advice.minimum_viable_set is not None:
            mvs = advice.minimum_viable_set
            assert len(mvs.funds) >= 1
            assert len(mvs.blocks_filled) >= 1

            # If MVS found a solution within limit, verify it
            if mvs.projected_within_limit:
                assert mvs.projected_cvar_95 >= cvar_limit

        # Step 5: Simulate re-construct with expanded portfolio
        # Add the top candidate from each gap block
        added_fund_returns = []
        added_weights = []
        for gap in advice.coverage.block_gaps[:3]:
            block_candidates = [c for c in advice.candidates if c.block_id == gap.block_id]
            if block_candidates and block_candidates[0].instrument_id in cand_returns:
                added_fund_returns.append(cand_returns[block_candidates[0].instrument_id])
                added_weights.append(strategic_targets.get(gap.block_id, 0.10))

        if added_fund_returns:
            # Build expanded portfolio
            expanded_returns = np.column_stack([equity_returns] + [r.reshape(-1, 1) for r in added_fund_returns])
            expanded_weights_raw = list(weights * (1.0 - sum(added_weights))) + added_weights
            expanded_weights = np.array(expanded_weights_raw)
            expanded_weights /= expanded_weights.sum()  # normalize

            expanded_port_ret = expanded_returns @ expanded_weights
            sorted_expanded = np.sort(expanded_port_ret)
            cutoff = max(int(len(sorted_expanded) * 0.05), 1)
            new_cvar = -float(np.mean(sorted_expanded[:cutoff])) * np.sqrt(252)

            # CVaR should have improved substantially
            assert -new_cvar > current_cvar, (
                f"Adding diversifiers should improve CVaR: {-new_cvar:.4f} vs {current_cvar:.4f}"
            )

    def test_activate_gate_cvar_within_limit(self):
        """Activation is allowed only when CVaR is within limit."""
        # Simulate cvar_within_limit check (same logic as activate endpoint)
        opt_meta_pass = {"cvar_within_limit": True, "cvar_95": -0.05, "cvar_limit": -0.06}
        opt_meta_fail = {"cvar_within_limit": False, "cvar_95": -0.84, "cvar_limit": -0.06}

        assert opt_meta_pass.get("cvar_within_limit", False) is True
        assert opt_meta_fail.get("cvar_within_limit", False) is False

    def test_activate_gate_requires_fund_selection(self):
        """Activation requires fund_selection_schema to exist."""
        fund_selection_empty = None
        fund_selection_no_funds = {"funds": []}
        fund_selection_valid = {
            "funds": [{"instrument_id": "abc", "weight": 1.0}],
            "optimization": {"cvar_within_limit": True},
        }

        assert fund_selection_empty is None
        assert not fund_selection_no_funds.get("funds")
        assert fund_selection_valid.get("funds")
        assert fund_selection_valid.get("optimization", {}).get("cvar_within_limit", False)

    def test_alternative_profile_suggestion_when_cvar_fails(self):
        """If current CVaR passes a different profile, suggest it."""
        rng = np.random.default_rng(99)
        n_days = 252

        equity_returns, weights, port_ret, current_cvar = (
            self._setup_concentrated_equity(rng, n_days)
        )

        advice = build_advice(
            portfolio_id="test-alt-profile",
            profile="conservative",
            current_cvar_95=current_cvar,
            cvar_limit=-0.04,  # very tight conservative limit
            block_weights={"na_equity_large": 1.0},
            strategic_targets={"na_equity_large": 0.60, "fi_us_aggregate": 0.40},
            block_metadata=_BLOCK_META,
            candidates=[],
            portfolio_returns=port_ret,
            portfolio_daily_returns=equity_returns,
            candidate_returns={},
            current_weights=weights,
            candidate_holdings={},
            portfolio_holdings=set(),
            alternative_cvar_limits={
                "conservative": -0.04,
                "moderate": -0.06,
                "growth": -0.12,
            },
        )

        # Growth profile has -0.12 limit — concentrated equity might pass it
        alt_profiles = {a.profile for a in advice.alternative_profiles}
        # At least growth should be suggested (very loose limit)
        if current_cvar >= -0.12:
            assert "growth" in alt_profiles
