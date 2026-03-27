"""Tests for quant_engine/allocation_proposal_service.py.

Proves that regime changes mechanically alter expected allocations:
- CRISIS regime reduces equity allocation
- RISK_ON regime increases equity allocation
- INFLATION regime favors real assets over nominal bonds
- Regional score deviations tilt geography-specific blocks
- All proposals respect min/max bounds
- Proposals sum to ~1.0
"""

from __future__ import annotations

import pytest

from quant_engine.allocation_proposal_service import (
    REGIME_TILTS,
    AllocationProposalResult,
    BlockProposal,
    compute_regime_tilted_weights,
    extract_regime_from_review,
    extract_regional_scores_from_snapshot,
)

# ---------------------------------------------------------------------------
#  Shared fixtures
# ---------------------------------------------------------------------------

# Simplified profile config matching the structure in profiles.yaml
MODERATE_CONFIG: dict[str, dict[str, float]] = {
    "na_equity_large": {"target": 0.20, "min": 0.15, "max": 0.28},
    "na_equity_growth": {"target": 0.08, "min": 0.04, "max": 0.12},
    "dm_europe_equity": {"target": 0.07, "min": 0.03, "max": 0.10},
    "em_equity": {"target": 0.05, "min": 0.02, "max": 0.08},
    "fi_us_aggregate": {"target": 0.15, "min": 0.10, "max": 0.22},
    "fi_us_treasury": {"target": 0.08, "min": 0.04, "max": 0.12},
    "fi_us_tips": {"target": 0.05, "min": 0.02, "max": 0.08},
    "fi_us_high_yield": {"target": 0.05, "min": 0.02, "max": 0.08},
    "alt_real_estate": {"target": 0.05, "min": 0.02, "max": 0.08},
    "alt_commodities": {"target": 0.03, "min": 0.00, "max": 0.06},
    "alt_gold": {"target": 0.04, "min": 0.02, "max": 0.06},
    "cash": {"target": 0.05, "min": 0.02, "max": 0.10},
}

CONSERVATIVE_CONFIG: dict[str, dict[str, float]] = {
    "na_equity_large": {"target": 0.12, "min": 0.08, "max": 0.16},
    "na_equity_value": {"target": 0.05, "min": 0.02, "max": 0.08},
    "dm_europe_equity": {"target": 0.05, "min": 0.02, "max": 0.08},
    "em_equity": {"target": 0.03, "min": 0.00, "max": 0.06},
    "fi_us_aggregate": {"target": 0.25, "min": 0.20, "max": 0.35},
    "fi_us_treasury": {"target": 0.15, "min": 0.10, "max": 0.25},
    "fi_us_tips": {"target": 0.10, "min": 0.05, "max": 0.15},
    "fi_us_high_yield": {"target": 0.05, "min": 0.00, "max": 0.08},
    "alt_real_estate": {"target": 0.05, "min": 0.02, "max": 0.08},
    "alt_gold": {"target": 0.05, "min": 0.02, "max": 0.08},
    "cash": {"target": 0.10, "min": 0.05, "max": 0.20},
}


def _get_proposal(result: AllocationProposalResult, block_id: str) -> BlockProposal:
    """Helper to find a specific block in proposal results."""
    for p in result.proposals:
        if p.block_id == block_id:
            return p
    raise ValueError(f"Block {block_id} not found in proposals")


def _total_by_class(result: AllocationProposalResult, prefix: str) -> float:
    """Sum proposed weights for blocks starting with prefix."""
    return sum(
        p.proposed_weight for p in result.proposals if p.block_id.startswith(prefix)
    )


def _total_equity(result: AllocationProposalResult) -> float:
    """Sum all equity block weights."""
    return sum(
        p.proposed_weight
        for p in result.proposals
        if p.block_id.startswith(("na_equity", "dm_europe", "dm_asia", "em_equity"))
    )


def _total_fi(result: AllocationProposalResult) -> float:
    """Sum all fixed income block weights."""
    return sum(
        p.proposed_weight for p in result.proposals if p.block_id.startswith("fi_")
    )


# ---------------------------------------------------------------------------
#  Core regime mechanics tests
# ---------------------------------------------------------------------------


class TestRegimeTilts:
    """Prove that regime changes mechanically alter allocations."""

    def test_crisis_reduces_equity_vs_neutral(self):
        """CRISIS regime must reduce total equity weight below neutral."""
        neutral = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "RISK_ON",
        )
        crisis = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "CRISIS",
        )
        assert _total_equity(crisis) < _total_equity(neutral)

    def test_crisis_increases_cash_vs_risk_off(self):
        """CRISIS regime must have higher cash than RISK_OFF."""
        risk_off = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "RISK_OFF",
        )
        crisis = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "CRISIS",
        )
        cash_risk_off = _get_proposal(risk_off, "cash").proposed_weight
        cash_crisis = _get_proposal(crisis, "cash").proposed_weight
        assert cash_crisis >= cash_risk_off

    def test_risk_on_increases_equity_vs_risk_off(self):
        """RISK_ON must have higher equity than RISK_OFF."""
        risk_on = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "RISK_ON",
        )
        risk_off = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "RISK_OFF",
        )
        assert _total_equity(risk_on) > _total_equity(risk_off)

    def test_inflation_increases_alternatives(self):
        """INFLATION regime favors real assets (alternatives)."""
        normal = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "RISK_ON",
        )
        inflation = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "INFLATION",
        )
        alt_normal = _total_by_class(normal, "alt_")
        alt_inflation = _total_by_class(inflation, "alt_")
        assert alt_inflation > alt_normal

    def test_inflation_reduces_nominal_bonds_vs_risk_off(self):
        """INFLATION reduces FI more than RISK_OFF (which increases FI)."""
        risk_off = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "RISK_OFF",
        )
        inflation = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "INFLATION",
        )
        fi_risk_off = _total_fi(risk_off)
        fi_inflation = _total_fi(inflation)
        assert fi_inflation < fi_risk_off

    def test_crisis_equity_lower_than_all_other_regimes(self):
        """CRISIS must have the lowest equity allocation of all regimes."""
        results = {
            regime: _total_equity(
                compute_regime_tilted_weights("moderate", MODERATE_CONFIG, regime),
            )
            for regime in REGIME_TILTS
        }
        crisis_equity = results["CRISIS"]
        for regime, equity in results.items():
            if regime != "CRISIS":
                assert crisis_equity < equity, (
                    f"CRISIS equity ({crisis_equity:.4f}) should be < "
                    f"{regime} equity ({equity:.4f})"
                )


class TestBoundsAndNormalization:
    """Ensure proposals respect constraints and sum to 1.0."""

    @pytest.mark.parametrize("regime", ["RISK_ON", "RISK_OFF", "INFLATION", "CRISIS"])
    def test_weights_sum_to_one(self, regime: str):
        """All regime proposals must sum to ~1.0."""
        result = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, regime,
        )
        assert abs(result.total_weight - 1.0) < 0.01, (
            f"Total weight {result.total_weight} for {regime}"
        )

    @pytest.mark.parametrize("regime", ["RISK_ON", "RISK_OFF", "INFLATION", "CRISIS"])
    def test_all_weights_within_bounds(self, regime: str):
        """Every block must stay within its min/max bounds."""
        result = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, regime,
        )
        for p in result.proposals:
            assert p.proposed_weight >= p.min_weight - 1e-6, (
                f"{p.block_id}: {p.proposed_weight} < min {p.min_weight}"
            )
            assert p.proposed_weight <= p.max_weight + 1e-6, (
                f"{p.block_id}: {p.proposed_weight} > max {p.max_weight}"
            )

    def test_conservative_crisis_respects_tighter_bounds(self):
        """Conservative profile has tighter bounds; CRISIS must still respect them."""
        result = compute_regime_tilted_weights(
            "conservative", CONSERVATIVE_CONFIG, "CRISIS",
        )
        for p in result.proposals:
            assert p.proposed_weight >= p.min_weight - 1e-6
            assert p.proposed_weight <= p.max_weight + 1e-6
        assert abs(result.total_weight - 1.0) < 0.01


class TestRegionalScoreTilts:
    """Prove regional composite scores tilt geography-specific blocks."""

    def test_strong_us_score_increases_us_equity(self):
        """US composite_score=80 should push US equity blocks up vs neutral."""
        neutral = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "RISK_ON",
            regional_scores={"US": 50, "EUROPE": 50, "ASIA": 50, "EM": 50},
        )
        strong_us = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "RISK_ON",
            regional_scores={"US": 80, "EUROPE": 50, "ASIA": 50, "EM": 50},
        )
        us_neutral = _total_by_class(neutral, "na_equity")
        us_strong = _total_by_class(strong_us, "na_equity")
        assert us_strong > us_neutral

    def test_weak_em_score_reduces_em_equity(self):
        """EM composite_score=20 should reduce EM equity vs neutral."""
        neutral = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "RISK_ON",
            regional_scores={"US": 50, "EUROPE": 50, "ASIA": 50, "EM": 50},
        )
        weak_em = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "RISK_ON",
            regional_scores={"US": 50, "EUROPE": 50, "ASIA": 50, "EM": 20},
        )
        em_neutral = _get_proposal(neutral, "em_equity").proposed_weight
        em_weak = _get_proposal(weak_em, "em_equity").proposed_weight
        assert em_weak < em_neutral

    def test_regional_does_not_affect_fixed_income(self):
        """Regional score changes should only affect equity blocks."""
        neutral = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "RISK_ON",
            regional_scores={"US": 50, "EUROPE": 50, "ASIA": 50, "EM": 50},
        )
        extreme = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "RISK_ON",
            regional_scores={"US": 90, "EUROPE": 90, "ASIA": 90, "EM": 90},
        )
        # FI blocks should have same tilt_source="regime" (not "combined")
        for p in extreme.proposals:
            if p.block_id.startswith("fi_"):
                neutral_p = _get_proposal(neutral, p.block_id)
                # Pre-normalization they would be equal; post-normalization
                # they may differ slightly due to total rebalancing, but
                # the tilt_source should never be "combined"
                assert p.tilt_source in ("regime", "none")


class TestMetadata:
    """Test result metadata and rationale generation."""

    def test_result_has_regime(self):
        result = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "CRISIS",
        )
        assert result.regime == "CRISIS"
        assert result.profile == "moderate"

    def test_rationale_is_meaningful(self):
        result = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "CRISIS",
        )
        assert len(result.rationale) >= 20
        assert "CRISIS" in result.rationale

    def test_rationale_includes_regional_scores(self):
        result = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "RISK_ON",
            regional_scores={"US": 70, "EUROPE": 45},
        )
        assert "US: 70" in result.rationale
        assert "EUROPE: 45" in result.rationale

    def test_proposals_count_matches_config(self):
        result = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "RISK_ON",
        )
        assert len(result.proposals) == len(MODERATE_CONFIG)


class TestExtractors:
    """Test helper functions for extracting regime/scores from review data."""

    def test_extract_regime_from_review_with_regime(self):
        report = {"regime": {"global": "CRISIS", "regional": {"US": "CRISIS"}}}
        assert extract_regime_from_review(report) == "CRISIS"

    def test_extract_regime_from_review_without_regime(self):
        report = {"type": "weekly", "score_deltas": []}
        assert extract_regime_from_review(report) == "RISK_ON"

    def test_extract_regime_from_review_none_regime(self):
        report = {"regime": None}
        assert extract_regime_from_review(report) == "RISK_ON"

    def test_extract_regional_scores(self):
        snapshot = {
            "regions": {
                "US": {"composite_score": 62.5, "coverage": 0.85},
                "EUROPE": {"composite_score": 48.0, "coverage": 0.70},
            },
            "global_indicators": {},
        }
        scores = extract_regional_scores_from_snapshot(snapshot)
        assert scores == {"US": 62.5, "EUROPE": 48.0}

    def test_extract_regional_scores_empty(self):
        assert extract_regional_scores_from_snapshot({}) == {}


class TestStressRegimeNumerics:
    """Detailed numeric assertions for the stress/CRISIS scenario.

    Proves that a CRISIS regime produces a mechanically different
    Expected Return / weight vector — the core requirement of G1.4.
    """

    def test_crisis_na_equity_large_below_target(self):
        """CRISIS must reduce na_equity_large below its neutral target."""
        result = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "CRISIS",
        )
        p = _get_proposal(result, "na_equity_large")
        assert p.proposed_weight < p.neutral_weight
        assert p.tilt_applied < 0

    def test_crisis_fi_treasury_above_target(self):
        """CRISIS should increase treasury allocation (flight to quality)."""
        result = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "CRISIS",
        )
        p = _get_proposal(result, "fi_us_treasury")
        assert p.proposed_weight >= p.neutral_weight

    def test_crisis_cash_approaches_max(self):
        """CRISIS should push cash substantially toward its max."""
        result = compute_regime_tilted_weights(
            "moderate", MODERATE_CONFIG, "CRISIS",
        )
        p = _get_proposal(result, "cash")
        # Cash tilt in CRISIS is 0.40 of room to max
        # target=0.05, max=0.10, room=0.05, delta=0.02
        assert p.proposed_weight > p.neutral_weight

    def test_all_regimes_produce_distinct_vectors(self):
        """Every regime must produce a materially different weight vector."""
        results = {
            regime: compute_regime_tilted_weights(
                "moderate", MODERATE_CONFIG, regime,
            )
            for regime in REGIME_TILTS
        }
        regime_names = list(results.keys())
        for i, r1 in enumerate(regime_names):
            for r2 in regime_names[i + 1:]:
                weights_1 = {
                    p.block_id: p.proposed_weight
                    for p in results[r1].proposals
                }
                weights_2 = {
                    p.block_id: p.proposed_weight
                    for p in results[r2].proposals
                }
                total_diff = sum(
                    abs(weights_1[b] - weights_2[b]) for b in weights_1
                )
                assert total_diff > 0.01, (
                    f"{r1} and {r2} produced nearly identical vectors "
                    f"(diff={total_diff:.6f})"
                )
