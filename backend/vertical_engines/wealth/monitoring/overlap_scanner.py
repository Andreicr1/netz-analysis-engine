"""Holdings Overlap Scanner — pure math for intra-portfolio concentration.

Receives pre-fetched exploded holdings (HoldingRow list) and computes:
- Consolidated exposure per CUSIP across all component funds
- Consolidated exposure per GICS sector
- Breach detection when any single CUSIP exceeds a configurable limit

Zero I/O. All data access is handled by the I/O layer in
app/domains/wealth/services/holdings_exploder.py.

Gaps closed: G6.1 (hidden single-name concentration), G6.2 (sector overlap).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domains.wealth.services.holdings_exploder import HoldingRow

_DEFAULT_CUSIP_LIMIT_PCT = 0.05  # 5% of portfolio NAV


@dataclass(frozen=True, slots=True)
class CusipExposure:
    """Consolidated exposure for a single CUSIP across all funds."""

    cusip: str
    issuer_name: str | None
    total_weighted_pct: float  # sum of fund_weight × (pct_of_fund_nav / 100)
    contributing_funds: tuple[str, ...]  # instrument_id strings
    breach: bool


@dataclass(frozen=True, slots=True)
class SectorExposure:
    """Consolidated exposure for a GICS sector across all funds."""

    sector: str
    total_weighted_pct: float
    n_cusips: int


@dataclass(frozen=True, slots=True)
class OverlapResult:
    """Full overlap analysis result."""

    cusip_exposures: tuple[CusipExposure, ...]  # sorted descending by exposure
    sector_exposures: tuple[SectorExposure, ...]  # sorted descending by exposure
    breaches: tuple[CusipExposure, ...]  # only CUSIPs above limit
    limit_pct: float
    total_holdings: int


def compute_overlap(
    holdings: list[HoldingRow],
    limit_pct: float = _DEFAULT_CUSIP_LIMIT_PCT,
) -> OverlapResult:
    """Compute consolidated overlap from exploded holdings.

    Args:
        holdings: Pre-fetched exploded holdings from I/O layer.
        limit_pct: Breach threshold as decimal (0.05 = 5%).

    Returns:
        OverlapResult with per-CUSIP and per-sector exposures + breaches.

    """
    if not holdings:
        return OverlapResult(
            cusip_exposures=(),
            sector_exposures=(),
            breaches=(),
            limit_pct=limit_pct,
            total_holdings=0,
        )

    # ── Aggregate by CUSIP ──
    cusip_agg: dict[str, dict] = {}
    for h in holdings:
        entry = cusip_agg.setdefault(h.cusip, {
            "issuer_name": h.issuer_name,
            "total": 0.0,
            "funds": set(),
        })
        entry["total"] += h.weighted_pct
        entry["funds"].add(str(h.fund_instrument_id))
        # Prefer non-None issuer name
        if entry["issuer_name"] is None and h.issuer_name is not None:
            entry["issuer_name"] = h.issuer_name

    cusip_exposures: list[CusipExposure] = []
    breaches: list[CusipExposure] = []

    for cusip, data in cusip_agg.items():
        is_breach = data["total"] > limit_pct
        exp = CusipExposure(
            cusip=cusip,
            issuer_name=data["issuer_name"],
            total_weighted_pct=data["total"],
            contributing_funds=tuple(sorted(data["funds"])),
            breach=is_breach,
        )
        cusip_exposures.append(exp)
        if is_breach:
            breaches.append(exp)

    # Sort descending by exposure
    cusip_exposures.sort(key=lambda x: x.total_weighted_pct, reverse=True)
    breaches.sort(key=lambda x: x.total_weighted_pct, reverse=True)

    # ── Aggregate by sector ──
    sector_agg: dict[str, dict] = {}
    for h in holdings:
        sector = h.sector or "Unknown"
        entry = sector_agg.setdefault(sector, {"total": 0.0, "cusips": set()})
        entry["total"] += h.weighted_pct
        entry["cusips"].add(h.cusip)

    sector_exposures = sorted(
        [
            SectorExposure(
                sector=sector,
                total_weighted_pct=data["total"],
                n_cusips=len(data["cusips"]),
            )
            for sector, data in sector_agg.items()
        ],
        key=lambda x: x.total_weighted_pct,
        reverse=True,
    )

    return OverlapResult(
        cusip_exposures=tuple(cusip_exposures),
        sector_exposures=tuple(sector_exposures),
        breaches=tuple(breaches),
        limit_pct=limit_pct,
        total_holdings=len(holdings),
    )
