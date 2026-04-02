"""Peer matcher — peer identification by instrument type.

Pure logic helper. Builds peer group keys from instrument attributes and
implements hierarchical fallback when groups are too small (< MIN_PEER_COUNT).

Does NOT import service.py (enforced by import-linter).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import structlog

from vertical_engines.wealth.peer_group.models import PeerGroup, PeerGroupNotFound

logger = structlog.get_logger()

MIN_PEER_COUNT = 20  # Morningstar/Lipper standard


# ── AUM bucket boundaries (USD) ────────────────────────────────────
def _aum_bucket(aum_usd: float | None) -> str:
    if aum_usd is None:
        return "unknown"
    if aum_usd < 500_000_000:
        return "small"
    if aum_usd < 5_000_000_000:
        return "mid"
    return "large"


# ── Duration bucket boundaries (years) ─────────────────────────────
def _duration_bucket(duration_years: float | None) -> str:
    if duration_years is None:
        return "unknown"
    if duration_years < 3:
        return "short"
    if duration_years < 7:
        return "medium"
    if duration_years < 15:
        return "long"
    return "ultra"


# ── Rating tier mapping ────────────────────────────────────────────
_RATING_TIERS: dict[str, str] = {}
for _r in ("AAA", "AA+", "AA", "AA-"):
    _RATING_TIERS[_r] = "AAA_AA"
for _r in ("A+", "A", "A-"):
    _RATING_TIERS[_r] = "A"
for _r in ("BBB+", "BBB", "BBB-"):
    _RATING_TIERS[_r] = "BBB"
for _r in ("BB+", "BB", "BB-", "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C", "D"):
    _RATING_TIERS[_r] = "BB_and_below"


def _rating_tier(rating: str | None) -> str:
    if not rating:
        return "unknown"
    return _RATING_TIERS.get(rating.strip(), "unknown")


# ── Market cap tier boundaries (USD) ───────────────────────────────
def _cap_tier(market_cap_usd: float | None) -> str:
    if market_cap_usd is None:
        return "unknown"
    if market_cap_usd >= 200_000_000_000:
        return "mega"
    if market_cap_usd >= 10_000_000_000:
        return "large"
    if market_cap_usd >= 2_000_000_000:
        return "mid"
    return "small"


# ── Key builders per instrument type ───────────────────────────────

def _fund_key_levels(block_id: str, attrs: dict[str, Any]) -> list[str]:
    """Build hierarchical peer group keys for a fund.

    Returns keys from most specific (level 0) to least (level 2).
    """
    strategy = str(attrs.get("strategy_label") or attrs.get("strategy", "unknown"))
    aum = _aum_bucket(attrs.get("aum_usd"))
    return [
        f"{block_id}::{strategy}::{aum}",       # level 0: full
        f"{block_id}::{strategy}",                # level 1: drop aum_bucket
        block_id,                                  # level 2: block only
    ]


def _bond_key_levels(block_id: str, attrs: dict[str, Any]) -> list[str]:
    """Build hierarchical peer group keys for a bond."""
    issuer_type = str(attrs.get("issuer_type", "unknown"))
    tier = _rating_tier(attrs.get("credit_rating"))
    dur = _duration_bucket(attrs.get("duration_years"))
    return [
        f"{block_id}::{issuer_type}::{tier}::{dur}",  # level 0: full
        f"{block_id}::{issuer_type}::{tier}",           # level 1: drop duration
        block_id,                                         # level 2: block only
    ]


def _equity_key_levels(block_id: str, attrs: dict[str, Any]) -> list[str]:
    """Build hierarchical peer group keys for an equity."""
    sector = str(attrs.get("gics_sector", "unknown"))
    cap = _cap_tier(attrs.get("market_cap_usd"))
    return [
        f"{block_id}::{sector}::{cap}",   # level 0: full
        f"{block_id}::{sector}",            # level 1: drop cap_tier
        block_id,                            # level 2: block only
    ]


_KEY_BUILDERS: dict[str, Callable[[str, dict[str, Any]], list[str]]] = {
    "fund": _fund_key_levels,
    "bond": _bond_key_levels,
    "equity": _equity_key_levels,
}


def build_key_levels(
    instrument_type: str,
    block_id: str,
    attributes: dict[str, Any],
) -> list[str]:
    """Build hierarchical peer group keys for any instrument type.

    Returns a list of keys from most specific (index 0) to least (index 2).
    """
    builder = _KEY_BUILDERS.get(instrument_type)
    if builder is None:
        return [block_id]
    return builder(block_id, attributes)


def build_peer_group_key(
    instrument_type: str,
    block_id: str,
    attributes: dict[str, Any],
) -> str:
    """Build the most specific (level 0) peer group key."""
    levels = build_key_levels(instrument_type, block_id, attributes)
    return levels[0]


def match_peers(
    target_instrument_id: uuid.UUID,
    target_type: str,
    target_block_id: str | None,
    target_attributes: dict[str, Any],
    universe: list[dict[str, Any]],
    min_peer_count: int = MIN_PEER_COUNT,
) -> PeerGroup | PeerGroupNotFound:
    """Find the peer group for a target instrument from a universe.

    Implements hierarchical fallback: tries full key first, then drops
    the most granular dimension until min_peer_count is met or block-only
    is exhausted.

    Keys are precomputed once for the entire universe (O(N)), then each
    fallback level is a dict lookup (O(1)).

    Args:
        target_instrument_id: UUID of the target instrument.
        target_type: 'fund', 'bond', or 'equity'.
        target_block_id: AllocationBlock ID (None = no block assigned).
        target_attributes: JSONB attributes dict.
        universe: List of dicts with instrument_id, instrument_type, block_id, attributes.
        min_peer_count: Minimum number of peers required (default 20).

    Returns:
        PeerGroup if sufficient peers found, PeerGroupNotFound otherwise.

    """
    if not target_block_id:
        return PeerGroupNotFound(
            instrument_id=target_instrument_id,
            reason="no_block_assigned",
        )

    key_levels = build_key_levels(target_type, target_block_id, target_attributes)

    # Precompute keys for the entire universe once — O(N)
    # Map: level_index → key_value → list[instrument_id]
    level_buckets: dict[int, dict[str, list[uuid.UUID]]] = {}
    for inst in universe:
        if inst["instrument_type"] != target_type:
            continue
        inst_block = inst.get("block_id")
        if not inst_block:
            continue

        inst_keys = build_key_levels(
            inst["instrument_type"],
            inst_block,
            inst.get("attributes", {}),
        )
        for level_idx, key_val in enumerate(inst_keys):
            if level_idx not in level_buckets:
                level_buckets[level_idx] = {}
            bucket = level_buckets[level_idx]
            if key_val not in bucket:
                bucket[key_val] = []
            bucket[key_val].append(inst["instrument_id"])

    # Lookup at each fallback level — O(1) per level
    best_members: list[uuid.UUID] = []
    for fallback_level, target_key in enumerate(key_levels):
        members = level_buckets.get(fallback_level, {}).get(target_key, [])

        if len(members) >= min_peer_count:
            logger.debug(
                "peer_group_found",
                instrument_id=str(target_instrument_id),
                peer_group_key=target_key,
                member_count=len(members),
                fallback_level=fallback_level,
            )
            return PeerGroup(
                peer_group_key=target_key,
                instrument_type=target_type,
                block_id=target_block_id,
                member_count=len(members),
                members=tuple(members),
                fallback_level=fallback_level,
            )
        best_members = members

    logger.debug(
        "peer_group_insufficient",
        instrument_id=str(target_instrument_id),
        best_count=len(best_members),
    )
    return PeerGroupNotFound(
        instrument_id=target_instrument_id,
        reason="insufficient_peers",
    )
