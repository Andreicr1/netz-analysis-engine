"""Portfolio Construction Advisor — diagnose CVaR gaps and recommend funds.

Pure functions, zero I/O.  All data arrives as frozen dataclasses or numpy
arrays; results are returned as frozen dataclasses.  Designed to run inside
``asyncio.to_thread()`` from the route handler.

Flow
----
1. ``analyze_block_gaps``   — compare optimizer block weights vs strategic targets
2. ``rank_candidates``      — composite scoring (vol, correlation, overlap, sharpe)
3. ``compute_holdings_overlap`` — CUSIP set intersection per candidate
4. ``project_cvar_historical``  — historical-simulation CVaR with heuristic weight rescaling
5. ``find_minimum_viable_set``  — brute-force (<=15) or greedy+swap (>15)
6. ``build_advice``         — top-level orchestrator that chains 1-5
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from typing import Sequence

import numpy as np
import structlog

from vertical_engines.wealth.model_portfolio.models import (
    AlternativeProfile,
    BlockGap,
    BlockInfo,
    CandidateFund,
    ConstructionAdvice,
    CoverageAnalysis,
    FundCandidate,
    MinimumViableSet,
)

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Diversification value by asset class — higher means more valuable for
# reducing concentrated equity risk.
_DIVERSIFICATION_VALUE: dict[str, float] = {
    "fixed_income": 4.0,
    "alternatives": 3.0,
    "cash": 2.0,
    "equity": 1.0,
}

# Default candidate scoring weights (vol, correlation, overlap, sharpe).
DEFAULT_ADVISOR_SCORING_WEIGHTS: dict[str, float] = {
    "low_volatility": 0.40,
    "low_correlation": 0.35,
    "low_overlap": 0.15,
    "high_sharpe": 0.10,
}

# Hard ceiling: do not consider more than this many candidates in brute-force.
_MAX_BRUTE_FORCE_CANDIDATES = 15
_MAX_SET_SIZE = 5
_MIN_NAV_DAYS = 126  # 6 months minimum for correlation reliability


# ---------------------------------------------------------------------------
# 1. Block Gap Analysis
# ---------------------------------------------------------------------------


def analyze_block_gaps(
    block_weights: dict[str, float],
    strategic_targets: dict[str, float],
    block_metadata: dict[str, BlockInfo],
    *,
    max_gaps: int = 5,
) -> CoverageAnalysis:
    """Compare current block allocation against strategic targets.

    Parameters
    ----------
    block_weights:
        ``{block_id: aggregate_weight}`` from the optimizer result.
    strategic_targets:
        ``{block_id: target_weight}`` from StrategicAllocation.
    block_metadata:
        ``{block_id: BlockInfo}`` with display_name and asset_class.
    max_gaps:
        Maximum number of gap blocks to return (sorted by priority).

    Returns
    -------
    CoverageAnalysis with block gaps sorted by priority descending.
    """
    total_blocks = len(strategic_targets)
    covered = sum(1 for bid in strategic_targets if block_weights.get(bid, 0.0) > 1e-6)

    gaps: list[BlockGap] = []
    for block_id, target in strategic_targets.items():
        current = block_weights.get(block_id, 0.0)
        gap = target - current
        if gap < 0.005:  # less than 0.5pp gap — not worth recommending
            continue

        info = block_metadata.get(block_id)
        asset_class = info.asset_class if info else "equity"
        display_name = info.display_name if info else block_id

        div_value = _DIVERSIFICATION_VALUE.get(asset_class, 1.0)
        # Reason: describe WHY this gap matters
        if current < 1e-6:
            reason = f"No allocation to {display_name} (target {target:.0%})"
        else:
            reason = f"Underweight by {gap:.1%} (current {current:.1%} vs target {target:.1%})"

        gaps.append(
            BlockGap(
                block_id=block_id,
                display_name=display_name,
                asset_class=asset_class,
                target_weight=target,
                current_weight=current,
                gap_weight=gap,
                priority=0,  # set below
                reason=reason,
            ),
        )

    # Sort by gap_weight * diversification_value descending
    gaps.sort(key=lambda g: g.gap_weight * _DIVERSIFICATION_VALUE.get(g.asset_class, 1.0), reverse=True)

    # Assign priority (1 = highest)
    gaps = [replace(g, priority=i + 1) for i, g in enumerate(gaps)]
    gaps = gaps[:max_gaps]

    covered_pct = covered / total_blocks if total_blocks > 0 else 0.0

    return CoverageAnalysis(
        total_blocks=total_blocks,
        covered_blocks=covered,
        covered_pct=round(covered_pct, 3),
        block_gaps=gaps,
    )


# ---------------------------------------------------------------------------
# 2. Candidate Ranking
# ---------------------------------------------------------------------------


def _min_max_normalize(values: Sequence[float]) -> list[float]:
    """Min-max normalize a list of values to [0, 1]."""
    if not values:
        return []
    mn, mx = min(values), max(values)
    rng = mx - mn
    if rng < 1e-12:
        return [0.5] * len(values)
    return [(v - mn) / rng for v in values]


def rank_candidates(
    candidates: list[FundCandidate],
    portfolio_returns: np.ndarray,
    candidate_returns: dict[str, np.ndarray],
    candidate_holdings: dict[str, set[str]],
    portfolio_holdings: set[str],
    *,
    max_per_block: int = 3,
    scoring_weights: dict[str, float] | None = None,
) -> list[CandidateFund]:
    """Score and rank candidates per block.

    Parameters
    ----------
    candidates:
        All eligible fund candidates (pre-filtered by block, NAV availability).
    portfolio_returns:
        ``(T,)`` daily portfolio return series (weighted sum of current funds).
    candidate_returns:
        ``{instrument_id: (T',) array}`` — daily returns per candidate.
        Must share aligned dates with portfolio_returns where overlap exists.
    candidate_holdings:
        ``{instrument_id: set_of_cusips}`` from N-PORT.
    portfolio_holdings:
        Set of CUSIPs in the current portfolio.
    max_per_block:
        Top N candidates to keep per block after ranking.
    scoring_weights:
        Override for ``DEFAULT_ADVISOR_SCORING_WEIGHTS``.

    Returns
    -------
    Ranked list of CandidateFund (across all blocks, sorted by block then score).
    """
    weights = scoring_weights or DEFAULT_ADVISOR_SCORING_WEIGHTS
    w_vol = weights.get("low_volatility", 0.40)
    w_corr = weights.get("low_correlation", 0.35)
    w_overlap = weights.get("low_overlap", 0.15)
    w_sharpe = weights.get("high_sharpe", 0.10)

    # Group candidates by block
    by_block: dict[str, list[FundCandidate]] = {}
    for c in candidates:
        by_block.setdefault(c.block_id, []).append(c)

    result: list[CandidateFund] = []

    for block_id, block_candidates in by_block.items():
        # Compute correlation + overlap for each candidate
        correlations: list[float] = []
        overlaps: list[float] = []
        vols: list[float] = []
        sharpes: list[float] = []
        has_holdings_flags: list[bool] = []

        for fc in block_candidates:
            # Correlation with portfolio
            cand_ret = candidate_returns.get(fc.instrument_id)
            if cand_ret is not None and len(cand_ret) >= _MIN_NAV_DAYS and len(portfolio_returns) >= _MIN_NAV_DAYS:
                # Use overlapping period
                n = min(len(portfolio_returns), len(cand_ret))
                corr = float(np.corrcoef(portfolio_returns[-n:], cand_ret[-n:])[0, 1])
                if np.isnan(corr):
                    corr = 0.0
            else:
                corr = 0.0
            correlations.append(corr)

            # Holdings overlap (Jaccard)
            cand_cusips = candidate_holdings.get(fc.instrument_id, set())
            has_data = len(cand_cusips) > 0
            has_holdings_flags.append(has_data)
            if has_data and portfolio_holdings:
                intersection = len(cand_cusips & portfolio_holdings)
                union = len(cand_cusips | portfolio_holdings)
                overlaps.append(intersection / union if union > 0 else 0.0)
            else:
                overlaps.append(0.0)

            vols.append(fc.volatility_1y if fc.volatility_1y is not None else 0.20)
            sharpes.append(fc.sharpe_1y if fc.sharpe_1y is not None else 0.0)

        # Normalize within block
        norm_vol = _min_max_normalize(vols)
        norm_corr = _min_max_normalize(correlations)
        norm_sharpe = _min_max_normalize(sharpes)
        # overlap is already 0-1

        scored: list[tuple[float, int]] = []
        for i in range(len(block_candidates)):
            score = (
                w_vol * (1.0 - norm_vol[i])
                + w_corr * (1.0 - norm_corr[i])
                + w_overlap * (1.0 - overlaps[i])
                + w_sharpe * norm_sharpe[i]
            )
            scored.append((score, i))

        scored.sort(key=lambda t: t[0], reverse=True)

        for rank, (score, idx) in enumerate(scored[:max_per_block]):
            fc = block_candidates[idx]
            result.append(
                CandidateFund(
                    block_id=block_id,
                    instrument_id=fc.instrument_id,
                    name=fc.name,
                    ticker=fc.ticker,
                    strategy_label=fc.strategy_label,
                    volatility_1y=fc.volatility_1y,
                    correlation_with_portfolio=round(correlations[idx], 4),
                    overlap_pct=round(overlaps[idx], 4),
                    projected_cvar_95=None,  # filled later by project_cvar
                    cvar_improvement=0.0,     # filled later
                    in_universe=fc.in_universe,
                    external_id=fc.external_id,
                    has_holdings_data=has_holdings_flags[idx],
                ),
            )

    return result


# ---------------------------------------------------------------------------
# 3. Holdings Overlap (CUSIP set intersection)
# ---------------------------------------------------------------------------


def compute_holdings_overlap(
    portfolio_cusips: set[str],
    candidate_cusips: set[str],
) -> float:
    """Jaccard overlap between portfolio and candidate CUSIP sets."""
    if not portfolio_cusips or not candidate_cusips:
        return 0.0
    union = len(portfolio_cusips | candidate_cusips)
    if union == 0:
        return 0.0
    return len(portfolio_cusips & candidate_cusips) / union


# ---------------------------------------------------------------------------
# 4. CVaR Projection — Historical Simulation
# ---------------------------------------------------------------------------


def project_cvar_historical(
    portfolio_daily_returns: np.ndarray,
    candidate_returns: np.ndarray,
    current_weights: np.ndarray,
    candidate_target_weight: float,
    *,
    alpha: float = 0.05,
) -> float | None:
    """Project CVaR after adding a candidate fund via historical simulation.

    Uses the most recent common observation window.  Returns annualized CVaR
    as a negative number (loss convention: -0.08 = 8% loss at 95% confidence).

    Returns None if insufficient overlapping data.
    """
    # portfolio_daily_returns: (T, N) — per-fund daily returns
    # candidate_returns: (T',) — candidate daily returns
    n_port = portfolio_daily_returns.shape[0]
    n_cand = len(candidate_returns)
    n_common = min(n_port, n_cand)

    if n_common < _MIN_NAV_DAYS:
        return None

    # Align to most recent common window
    port_ret = portfolio_daily_returns[-n_common:]  # (T, N)
    cand_ret = candidate_returns[-n_common:]        # (T,)

    # Build heuristic weights: rescale existing by (1 - c), append c
    scaled_weights = current_weights * (1.0 - candidate_target_weight)
    new_weights = np.append(scaled_weights, candidate_target_weight)

    # Combine returns: (T, N+1)
    combined = np.column_stack([port_ret, cand_ret])

    # Portfolio daily returns with new weights
    port_daily = combined @ new_weights  # (T,)

    # Historical CVaR
    sorted_ret = np.sort(port_daily)
    cutoff = max(int(len(sorted_ret) * alpha), 1)
    daily_cvar = float(-np.mean(sorted_ret[:cutoff]))

    # Annualize (sqrt(252) for volatility-based scaling)
    annual_cvar = daily_cvar * np.sqrt(252)

    return float(round(-annual_cvar, 6))  # negative = loss convention


def project_cvar_for_candidates(
    candidates: list[CandidateFund],
    portfolio_daily_returns: np.ndarray,
    candidate_returns_map: dict[str, np.ndarray],
    current_weights: np.ndarray,
    strategic_targets: dict[str, float],
    current_cvar: float,
) -> list[CandidateFund]:
    """Compute projected CVaR for each candidate and fill in the projection fields.

    Parameters
    ----------
    candidates:
        Ranked candidates (from ``rank_candidates``).
    portfolio_daily_returns:
        ``(T, N)`` per-fund daily returns for current portfolio.
    candidate_returns_map:
        ``{instrument_id: (T',) array}`` daily returns per candidate.
    current_weights:
        ``(N,)`` current fund weights.
    strategic_targets:
        ``{block_id: target_weight}`` — used as ``candidate_target_weight``.
    current_cvar:
        Current portfolio CVaR (negative, loss convention).

    Returns
    -------
    Updated candidate list with ``projected_cvar_95`` and ``cvar_improvement``.
    """
    result: list[CandidateFund] = []

    for c in candidates:
        cand_ret = candidate_returns_map.get(c.instrument_id)
        target_weight = strategic_targets.get(c.block_id, 0.05)

        projected: float | None = None
        improvement = 0.0

        if cand_ret is not None:
            projected = project_cvar_historical(
                portfolio_daily_returns,
                cand_ret,
                current_weights,
                target_weight,
            )

        if projected is not None and abs(current_cvar) > 1e-8:
            # improvement: how much of the gap did we close? (positive = better)
            improvement = round((current_cvar - projected) / abs(current_cvar), 4)

        result.append(
            replace(
                c,
                projected_cvar_95=projected,
                cvar_improvement=improvement,
            ),
        )

    # Sort by cvar_improvement descending (best improvement first)
    result.sort(key=lambda c: c.cvar_improvement, reverse=True)

    return result


# ---------------------------------------------------------------------------
# 5. Minimum Viable Set — brute-force (small) or greedy+swap (large)
# ---------------------------------------------------------------------------


def _evaluate_set(
    fund_ids: list[str],
    portfolio_daily_returns: np.ndarray,
    candidate_returns_map: dict[str, np.ndarray],
    current_weights: np.ndarray,
    target_weights: dict[str, float],
    candidate_blocks: dict[str, str],
    alpha: float = 0.05,
) -> float | None:
    """Evaluate projected CVaR when adding a set of candidates simultaneously."""
    n_common = portfolio_daily_returns.shape[0]
    cand_arrays: list[np.ndarray] = []
    cand_target_weights: list[float] = []

    for fid in fund_ids:
        ret = candidate_returns_map.get(fid)
        if ret is None:
            return None
        n_common = min(n_common, len(ret))
        cand_arrays.append(ret)
        block = candidate_blocks.get(fid, "")
        cand_target_weights.append(target_weights.get(block, 0.05))

    if n_common < _MIN_NAV_DAYS:
        return None

    total_new_weight = sum(cand_target_weights)
    if total_new_weight >= 1.0:
        total_new_weight = 0.8  # clamp to avoid negative existing weights

    port_ret = portfolio_daily_returns[-n_common:]
    scaled_existing = current_weights * (1.0 - total_new_weight)

    all_weights = list(scaled_existing)
    all_returns = [port_ret]

    for arr, tw in zip(cand_arrays, cand_target_weights, strict=True):
        all_returns.append(arr[-n_common:].reshape(-1, 1))
        all_weights.append(tw * (1.0 - total_new_weight + total_new_weight) / total_new_weight * tw
                           if total_new_weight > 0 else tw)

    # Rebuild weights properly: scale existing by (1 - sum_new), append each candidate weight
    all_weights_arr = np.append(scaled_existing, cand_target_weights)
    # Normalize to sum = 1
    w_sum = all_weights_arr.sum()
    if w_sum > 0:
        all_weights_arr = all_weights_arr / w_sum

    combined_cols = [port_ret]
    for arr in cand_arrays:
        combined_cols.append(arr[-n_common:].reshape(-1, 1))
    combined = np.column_stack(combined_cols)  # (T, N + K)

    port_daily = combined @ all_weights_arr
    sorted_ret = np.sort(port_daily)
    cutoff = max(int(len(sorted_ret) * alpha), 1)
    daily_cvar = float(-np.mean(sorted_ret[:cutoff]))
    annual_cvar = daily_cvar * np.sqrt(252)
    return float(round(-annual_cvar, 6))


def find_minimum_viable_set(
    candidates: list[CandidateFund],
    portfolio_daily_returns: np.ndarray,
    candidate_returns_map: dict[str, np.ndarray],
    current_weights: np.ndarray,
    strategic_targets: dict[str, float],
    cvar_limit: float,
) -> MinimumViableSet | None:
    """Find the smallest candidate set that brings CVaR within the limit.

    Uses brute-force enumeration for <=15 candidates (C(15,5) = 3003 max),
    falls back to greedy + swap-pass for larger sets.

    Returns None if no combination achieves the limit.
    """
    if not candidates:
        return None

    candidate_blocks = {c.instrument_id: c.block_id for c in candidates}
    eligible = [
        c for c in candidates
        if c.instrument_id in candidate_returns_map
    ]

    if not eligible:
        return None

    fids = [c.instrument_id for c in eligible]

    if len(fids) <= _MAX_BRUTE_FORCE_CANDIDATES:
        return _brute_force_search(
            fids, portfolio_daily_returns, candidate_returns_map,
            current_weights, strategic_targets, candidate_blocks, cvar_limit,
        )
    else:
        return _greedy_search_with_swap(
            eligible, portfolio_daily_returns, candidate_returns_map,
            current_weights, strategic_targets, candidate_blocks, cvar_limit,
        )


def _brute_force_search(
    fids: list[str],
    portfolio_daily_returns: np.ndarray,
    candidate_returns_map: dict[str, np.ndarray],
    current_weights: np.ndarray,
    strategic_targets: dict[str, float],
    candidate_blocks: dict[str, str],
    cvar_limit: float,
) -> MinimumViableSet | None:
    """Enumerate all subsets of size 1..MAX_SET_SIZE, return smallest that passes."""
    best: MinimumViableSet | None = None

    for k in range(1, min(_MAX_SET_SIZE, len(fids)) + 1):
        for combo in itertools.combinations(fids, k):
            combo_list = list(combo)
            projected = _evaluate_set(
                combo_list, portfolio_daily_returns, candidate_returns_map,
                current_weights, strategic_targets, candidate_blocks,
            )
            if projected is None:
                continue
            passes = projected >= cvar_limit  # both are negative; -0.05 >= -0.06 is True
            if passes:
                blocks_filled = sorted({candidate_blocks.get(f, "") for f in combo_list})
                candidate = MinimumViableSet(
                    funds=combo_list,
                    projected_cvar_95=projected,
                    projected_within_limit=True,
                    blocks_filled=blocks_filled,
                    search_method="brute_force",
                )
                if (
                    best is None
                    or len(combo_list) < len(best.funds)
                    or (len(combo_list) == len(best.funds) and projected > best.projected_cvar_95)
                ):
                    best = candidate
        if best is not None:
            return best  # found at this size, no need to check larger

    return best


def _greedy_search_with_swap(
    eligible: list[CandidateFund],
    portfolio_daily_returns: np.ndarray,
    candidate_returns_map: dict[str, np.ndarray],
    current_weights: np.ndarray,
    strategic_targets: dict[str, float],
    candidate_blocks: dict[str, str],
    cvar_limit: float,
) -> MinimumViableSet | None:
    """Greedy best-improvement search with swap-pass refinement."""
    selected: list[str] = []
    remaining = [c.instrument_id for c in eligible]

    for _ in range(_MAX_SET_SIZE):
        if not remaining:
            break

        best_fid: str | None = None
        best_cvar: float | None = None

        for fid in remaining:
            trial = selected + [fid]
            projected = _evaluate_set(
                trial, portfolio_daily_returns, candidate_returns_map,
                current_weights, strategic_targets, candidate_blocks,
            )
            if projected is None:
                continue
            if best_cvar is None or projected > best_cvar:
                best_cvar = projected
                best_fid = fid

        if best_fid is None:
            break

        selected.append(best_fid)
        remaining.remove(best_fid)

        if best_cvar is not None and best_cvar >= cvar_limit:
            break

    if not selected:
        return None

    # Swap pass: try replacing each selected fund with each remaining fund
    improved = True
    while improved:
        improved = False
        for i in range(len(selected)):
            for fid in remaining:
                trial = selected[:i] + [fid] + selected[i + 1:]
                projected = _evaluate_set(
                    trial, portfolio_daily_returns, candidate_returns_map,
                    current_weights, strategic_targets, candidate_blocks,
                )
                if projected is None:
                    continue
                current_projected = _evaluate_set(
                    selected, portfolio_daily_returns, candidate_returns_map,
                    current_weights, strategic_targets, candidate_blocks,
                )
                if current_projected is not None and projected > current_projected:
                    old_fid = selected[i]
                    selected[i] = fid
                    remaining.remove(fid)
                    remaining.append(old_fid)
                    improved = True
                    break
            if improved:
                break

    final_cvar = _evaluate_set(
        selected, portfolio_daily_returns, candidate_returns_map,
        current_weights, strategic_targets, candidate_blocks,
    )

    if final_cvar is None:
        return None

    blocks_filled = sorted({candidate_blocks.get(f, "") for f in selected})
    return MinimumViableSet(
        funds=selected,
        projected_cvar_95=final_cvar,
        projected_within_limit=final_cvar >= cvar_limit,
        blocks_filled=blocks_filled,
        search_method="greedy_with_swap",
    )


# ---------------------------------------------------------------------------
# 6. Top-level orchestrator
# ---------------------------------------------------------------------------


def build_advice(
    *,
    portfolio_id: str,
    profile: str,
    current_cvar_95: float,
    cvar_limit: float,
    block_weights: dict[str, float],
    strategic_targets: dict[str, float],
    block_metadata: dict[str, BlockInfo],
    candidates: list[FundCandidate],
    portfolio_returns: np.ndarray,
    portfolio_daily_returns: np.ndarray,
    candidate_returns: dict[str, np.ndarray],
    current_weights: np.ndarray,
    candidate_holdings: dict[str, set[str]],
    portfolio_holdings: set[str],
    alternative_cvar_limits: dict[str, float] | None = None,
    scoring_weights: dict[str, float] | None = None,
) -> ConstructionAdvice:
    """Build complete construction advice from pre-fetched data.

    This is the main entry point called via ``asyncio.to_thread()`` from the
    route handler.  All arguments are plain Python types or numpy arrays —
    no ORM objects, no I/O.

    Parameters
    ----------
    portfolio_id:
        UUID string of the model portfolio.
    profile:
        Risk profile (conservative, moderate, growth).
    current_cvar_95:
        Current portfolio CVaR (negative, loss convention).
    cvar_limit:
        Profile CVaR limit (negative, loss convention).
    block_weights:
        ``{block_id: aggregate_weight}`` from optimizer result.
    strategic_targets:
        ``{block_id: target_weight}`` from StrategicAllocation.
    block_metadata:
        ``{block_id: BlockInfo}`` with display names and asset classes.
    candidates:
        Pre-fetched candidate funds (FundCandidate dataclasses).
    portfolio_returns:
        ``(T,)`` weighted daily portfolio return series.
    portfolio_daily_returns:
        ``(T, N)`` per-fund daily returns for the current portfolio.
    candidate_returns:
        ``{instrument_id: (T',) array}`` daily returns per candidate.
    current_weights:
        ``(N,)`` current portfolio fund weights.
    candidate_holdings:
        ``{instrument_id: set_of_cusips}`` from N-PORT.
    portfolio_holdings:
        Set of CUSIPs in the current portfolio.
    alternative_cvar_limits:
        ``{profile: cvar_limit}`` for alternative profile suggestions.
    scoring_weights:
        Override for candidate scoring formula weights.

    Returns
    -------
    ConstructionAdvice — complete advisor response.
    """
    # 1. Block gap analysis
    coverage = analyze_block_gaps(block_weights, strategic_targets, block_metadata)

    # 2. Rank candidates
    ranked = rank_candidates(
        candidates,
        portfolio_returns,
        candidate_returns,
        candidate_holdings,
        portfolio_holdings,
        scoring_weights=scoring_weights,
    )

    # 3. Project CVaR for ranked candidates
    ranked = project_cvar_for_candidates(
        ranked,
        portfolio_daily_returns,
        candidate_returns,
        current_weights,
        strategic_targets,
        current_cvar_95,
    )

    # 4. Find minimum viable set
    mvs = find_minimum_viable_set(
        ranked,
        portfolio_daily_returns,
        candidate_returns,
        current_weights,
        strategic_targets,
        cvar_limit,
    )

    # 5. Alternative profiles
    alt_profiles: list[AlternativeProfile] = []
    if alternative_cvar_limits:
        for alt_profile, alt_limit in alternative_cvar_limits.items():
            if alt_profile == profile:
                continue
            alt_profiles.append(
                AlternativeProfile(
                    profile=alt_profile,
                    cvar_limit=alt_limit,
                    current_cvar_would_pass=current_cvar_95 >= alt_limit,
                ),
            )
        # Only keep profiles where the current portfolio would pass
        alt_profiles = [a for a in alt_profiles if a.current_cvar_would_pass]

    return ConstructionAdvice(
        portfolio_id=portfolio_id,
        profile=profile,
        current_cvar_95=current_cvar_95,
        cvar_limit=cvar_limit,
        cvar_gap=round(current_cvar_95 - cvar_limit, 6),
        coverage=coverage,
        candidates=ranked,
        minimum_viable_set=mvs,
        alternative_profiles=alt_profiles,
        projected_cvar_is_heuristic=True,
    )
