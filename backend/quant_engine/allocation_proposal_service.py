"""Allocation Proposal Engine — Black-Litterman-inspired regime tilts.

Transforms a MacroReview's regime classification and regional scores
into a prescriptive allocation weight vector per risk profile.

The approach is inspired by Black-Litterman (1992):
1. Start with the neutral (strategic) weights from the profile config.
2. Derive "views" from the macro regime and regional scores:
   - Global regime determines a risk-appetite multiplier on equity/credit.
   - Regional score deltas tilt geography-specific blocks.
3. Apply tilts within the profile's min/max bounds.
4. Renormalize to sum = 1.0.

Pure sync functions — no I/O. Config is injected by callers via
ConfigService.get("liquid_funds", "profiles").

All tilts are bounded by the profile's min/max constraints, so the
engine can never push allocations outside the investment policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
#  Regime tilt tables — deterministic mapping from regime to asset-class bias
# ---------------------------------------------------------------------------

# Global regime → multiplier on neutral weight delta.
# A positive equity_tilt means "add this fraction of the remaining room to max".
# A negative equity_tilt means "reduce toward min by this fraction of room".
# fi_tilt mirrors in reverse (flight-to-quality).
REGIME_TILTS: dict[str, dict[str, float]] = {
    "RISK_ON": {
        "equity_tilt": 0.30,   # push equities 30% toward max
        "fi_tilt": -0.15,      # trim fixed income 15% toward min
        "alt_tilt": 0.10,      # slight alternatives push
        "cash_tilt": -0.20,    # deploy cash
    },
    "RISK_OFF": {
        "equity_tilt": -0.25,
        "fi_tilt": 0.25,
        "alt_tilt": 0.05,
        "cash_tilt": 0.15,
    },
    "INFLATION": {
        "equity_tilt": -0.10,
        "fi_tilt": -0.20,     # nominal bonds suffer
        "alt_tilt": 0.30,     # real assets, commodities, gold
        "cash_tilt": 0.10,
    },
    "CRISIS": {
        "equity_tilt": -0.50,  # maximum de-risk
        "fi_tilt": 0.20,      # treasuries as safe haven
        "alt_tilt": -0.10,    # reduce illiquid
        "cash_tilt": 0.40,    # maximize cash buffer
    },
}

# Block classification for tilt application
_EQUITY_PREFIXES = ("na_equity", "dm_europe_equity", "dm_asia_equity", "em_equity")
_FI_PREFIXES = ("fi_",)
_ALT_PREFIXES = ("alt_",)
_CASH_IDS = ("cash",)

# Regional score → geography equity tilt
# When a region's composite_score is far from 50 (neutral), we apply
# an additional tilt to blocks in that geography.
_REGION_TO_BLOCKS: dict[str, list[str]] = {
    "US": ["na_equity_large", "na_equity_growth", "na_equity_value", "na_equity_small"],
    "EUROPE": ["dm_europe_equity"],
    "ASIA": ["dm_asia_equity"],
    "EM": ["em_equity"],
}


def _classify_block(block_id: str) -> str:
    """Classify a block_id into equity/fi/alt/cash."""
    if any(block_id.startswith(p) for p in _EQUITY_PREFIXES):
        return "equity"
    if any(block_id.startswith(p) for p in _FI_PREFIXES):
        return "fi"
    if any(block_id.startswith(p) for p in _ALT_PREFIXES):
        return "alt"
    if block_id in _CASH_IDS:
        return "cash"
    return "other"


@dataclass(frozen=True, slots=True)
class BlockProposal:
    """Proposed allocation for a single block."""

    block_id: str
    neutral_weight: float
    proposed_weight: float
    min_weight: float
    max_weight: float
    tilt_applied: float  # proposed - neutral
    tilt_source: str     # "regime", "regional", "combined"


@dataclass(frozen=True, slots=True)
class AllocationProposalResult:
    """Full allocation proposal output."""

    profile: str
    regime: str
    proposals: list[BlockProposal]
    total_weight: float
    rationale: str
    regional_scores: dict[str, float]  # region → composite_score used


def _absorb_residual(
    proposals: list[BlockProposal],
    residual: float,
) -> list[BlockProposal]:
    """Distribute weight residual to reach sum=1.0.

    First tries cash block. Then spreads among blocks with room in
    the residual direction. This preserves tilt direction for all blocks.
    """
    result = list(proposals)

    # Phase 1: Absorb into cash
    cash_idx = next((i for i, p in enumerate(result) if p.block_id == "cash"), None)
    if cash_idx is not None:
        p = result[cash_idx]
        if residual > 0:
            room = p.max_weight - p.proposed_weight
        else:
            room = p.proposed_weight - p.min_weight
        absorbed = max(-room, min(room, residual)) if residual < 0 else min(room, residual)
        new_w = round(p.proposed_weight + absorbed, 6)
        result[cash_idx] = BlockProposal(
            block_id=p.block_id,
            neutral_weight=p.neutral_weight,
            proposed_weight=new_w,
            min_weight=p.min_weight,
            max_weight=p.max_weight,
            tilt_applied=round(new_w - p.neutral_weight, 6),
            tilt_source=p.tilt_source,
        )
        residual -= absorbed

    # Phase 2: Spread remaining residual proportionally among blocks with room
    if abs(residual) > 1e-6:
        rooms: list[tuple[int, float]] = []
        for i, p in enumerate(result):
            if residual > 0:
                room = p.max_weight - p.proposed_weight
            else:
                room = p.proposed_weight - p.min_weight
            if room > 1e-6:
                rooms.append((i, room))

        total_room = sum(r for _, r in rooms)
        if total_room > 1e-6:
            for idx, room in rooms:
                share = (room / total_room) * residual
                p = result[idx]
                new_w = round(p.proposed_weight + share, 6)
                new_w = max(p.min_weight, min(p.max_weight, new_w))
                result[idx] = BlockProposal(
                    block_id=p.block_id,
                    neutral_weight=p.neutral_weight,
                    proposed_weight=new_w,
                    min_weight=p.min_weight,
                    max_weight=p.max_weight,
                    tilt_applied=round(new_w - p.neutral_weight, 6),
                    tilt_source=p.tilt_source,
                )

    return result


def compute_regime_tilted_weights(
    profile_name: str,
    strategic_config: dict[str, dict[str, float]],
    global_regime: str,
    regional_scores: dict[str, float] | None = None,
    score_neutral: float = 50.0,
    regional_sensitivity: float = 0.003,
) -> AllocationProposalResult:
    """Compute a proposed weight vector from regime + regional macro scores.

    Args:
        profile_name: Profile identifier (conservative/moderate/growth).
        strategic_config: Per-block config from profiles.yaml, e.g.
            {"na_equity_large": {"target": 0.20, "min": 0.15, "max": 0.28}, ...}
        global_regime: One of RISK_ON | RISK_OFF | INFLATION | CRISIS.
        regional_scores: Dict of region → composite_score (0-100).
            If None, only global regime tilts are applied.
        score_neutral: The "neutral" composite score (default 50).
        regional_sensitivity: Weight per score-point deviation from neutral.
            E.g., 0.003 means each point above 50 adds 0.3% of room toward max.

    Returns:
        AllocationProposalResult with per-block proposals and rationale.

    """
    regime_tilt = REGIME_TILTS.get(global_regime, REGIME_TILTS["RISK_ON"])
    regional_scores = regional_scores or {}

    # Build reverse lookup: block_id → region
    block_to_region: dict[str, str] = {}
    for region, blocks in _REGION_TO_BLOCKS.items():
        for bid in blocks:
            block_to_region[bid] = region

    proposals: list[BlockProposal] = []

    for block_id, config in strategic_config.items():
        target = config["target"]
        min_w = config["min"]
        max_w = config["max"]
        asset_class = _classify_block(block_id)

        # Step 1: Global regime tilt
        tilt_key = f"{asset_class}_tilt"
        regime_factor = regime_tilt.get(tilt_key, 0.0)

        if regime_factor >= 0:
            room = max_w - target
            global_delta = regime_factor * room
        else:
            room = target - min_w
            global_delta = regime_factor * room  # negative

        # Step 2: Regional score tilt (equity blocks only)
        regional_delta = 0.0
        tilt_source = "regime"
        region = block_to_region.get(block_id)
        if region and region in regional_scores and asset_class == "equity":
            score = regional_scores[region]
            score_deviation = score - score_neutral  # positive = favorable
            if score_deviation >= 0:
                room_r = max_w - target
            else:
                room_r = target - min_w
            regional_delta = score_deviation * regional_sensitivity * room_r
            tilt_source = "combined"

        # Step 3: Combine and clamp
        total_delta = global_delta + regional_delta
        proposed = target + total_delta
        proposed = max(min_w, min(max_w, proposed))

        proposals.append(BlockProposal(
            block_id=block_id,
            neutral_weight=target,
            proposed_weight=round(proposed, 6),
            min_weight=min_w,
            max_weight=max_w,
            tilt_applied=round(proposed - target, 6),
            tilt_source=tilt_source if abs(proposed - target) > 1e-6 else "none",
        ))

    # Step 4: Renormalize so weights sum to 1.0
    # Strategy: absorb residual into cash first, then spread proportionally
    # among blocks that have room, preserving tilt direction.
    total = sum(p.proposed_weight for p in proposals)
    if total > 0 and abs(total - 1.0) > 1e-6:
        residual = 1.0 - total  # positive = need more weight, negative = need less

        # Try to absorb residual into cash block first
        proposals = _absorb_residual(proposals, residual)

    final_total = round(sum(p.proposed_weight for p in proposals), 6)

    # Build rationale
    rationale_parts = [
        f"Regime-driven allocation proposal for '{profile_name}' under {global_regime} regime.",
    ]
    tilted = [p for p in proposals if abs(p.tilt_applied) > 1e-4]
    if tilted:
        increases = [p for p in tilted if p.tilt_applied > 0]
        decreases = [p for p in tilted if p.tilt_applied < 0]
        if increases:
            inc_str = ", ".join(
                f"{p.block_id} +{p.tilt_applied:+.2%}" for p in increases[:5]
            )
            rationale_parts.append(f"Increased: {inc_str}.")
        if decreases:
            dec_str = ", ".join(
                f"{p.block_id} {p.tilt_applied:+.2%}" for p in decreases[:5]
            )
            rationale_parts.append(f"Decreased: {dec_str}.")
    if regional_scores:
        score_str = ", ".join(f"{r}: {s:.0f}" for r, s in regional_scores.items())
        rationale_parts.append(f"Regional scores: {score_str}.")

    return AllocationProposalResult(
        profile=profile_name,
        regime=global_regime,
        proposals=proposals,
        total_weight=final_total,
        rationale=" ".join(rationale_parts),
        regional_scores=regional_scores,
    )


def extract_regime_from_review(report_json: dict[str, Any]) -> str:
    """Extract the global regime from a MacroReview's report_json.

    Falls back to RISK_ON if regime data is unavailable.
    """
    regime_data = report_json.get("regime")
    if isinstance(regime_data, dict):
        return regime_data.get("global", "RISK_ON")
    return "RISK_ON"


def extract_regional_scores_from_snapshot(
    snapshot_data: dict[str, Any],
) -> dict[str, float]:
    """Extract regional composite scores from a snapshot's data_json."""
    scores: dict[str, float] = {}
    for region, rdata in snapshot_data.get("regions", {}).items():
        if isinstance(rdata, dict) and "composite_score" in rdata:
            scores[region] = float(rdata["composite_score"])
    return scores
