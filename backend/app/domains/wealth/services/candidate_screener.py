"""Construction Advisor I/O layer — fetch candidates, NAV, holdings, risk.

Bridges async DB queries with the pure-function advisor engine in
``vertical_engines.wealth.model_portfolio.construction_advisor``.

All ORM results are extracted into frozen dataclasses or plain dicts/arrays
**before** crossing the ``asyncio.to_thread()`` boundary.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import numpy as np
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.wealth.models.allocation import StrategicAllocation
from app.domains.wealth.models.block import AllocationBlock
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.instrument_org import InstrumentOrg
from app.domains.wealth.models.nav import NavTimeseries
from app.domains.wealth.models.risk import FundRiskMetrics
from app.shared.models import SecNportHolding
from vertical_engines.wealth.model_portfolio.block_mapping import strategy_labels_for_block
from vertical_engines.wealth.model_portfolio.models import BlockInfo, FundCandidate

logger = structlog.get_logger()

# 6 months minimum for correlation reliability
MIN_CANDIDATE_NAV_DAYS = 126


async def load_block_metadata(db: AsyncSession) -> dict[str, BlockInfo]:
    """Load all active allocation blocks as frozen BlockInfo dataclasses."""
    stmt = select(AllocationBlock).where(AllocationBlock.is_active == True)  # noqa: E712
    result = await db.execute(stmt)
    blocks = result.scalars().all()
    return {
        b.block_id: BlockInfo(
            block_id=b.block_id,
            display_name=b.display_name,
            asset_class=b.asset_class,
            benchmark_ticker=b.benchmark_ticker,
        )
        for b in blocks
    }


async def load_strategic_targets(
    db: AsyncSession,
    profile: str,
) -> dict[str, float]:
    """Load active strategic allocation targets for a profile."""
    today = date.today()
    stmt = (
        select(StrategicAllocation)
        .where(
            StrategicAllocation.profile == profile,
            StrategicAllocation.effective_from <= today,
        )
        .where(
            (StrategicAllocation.effective_to.is_(None))
            | (StrategicAllocation.effective_to > today),
        )
    )
    result = await db.execute(stmt)
    allocations = result.scalars().all()

    # Deduplicate to latest per block
    seen: dict[str, StrategicAllocation] = {}
    for a in allocations:
        current = seen.get(a.block_id)
        if current is None or a.effective_from > current.effective_from:
            seen[a.block_id] = a
    return {a.block_id: float(a.target_weight) for a in seen.values()}


async def discover_candidates(
    db: AsyncSession,
    gap_block_ids: list[str],
    max_per_block: int = 20,
) -> list[FundCandidate]:
    """Discover candidate funds from the global catalog for gap blocks.

    Queries ``instruments_universe`` using strategy_label→block mapping,
    LEFT JOINs ``instruments_org`` to determine ``in_universe`` status,
    and JOINs ``fund_risk_metrics`` for pre-computed vol/sharpe/score.
    """
    if not gap_block_ids:
        return []

    # Build block_id → set of strategy_labels
    block_labels: dict[str, list[str]] = {}
    all_labels: set[str] = set()
    for block_id in gap_block_ids:
        labels = strategy_labels_for_block(block_id)
        if labels:
            block_labels[block_id] = labels
            all_labels.update(labels)

    if not all_labels:
        return []

    # Latest risk metrics subquery (latest calc_date per instrument)
    latest_risk = (
        select(
            FundRiskMetrics.instrument_id,
            func.max(FundRiskMetrics.calc_date).label("max_date"),
        )
        .group_by(FundRiskMetrics.instrument_id)
        .subquery()
    )

    stmt = (
        select(
            Instrument.instrument_id,
            Instrument.name,
            Instrument.ticker,
            Instrument.isin,
            Instrument.attributes,
            FundRiskMetrics.volatility_1y,
            FundRiskMetrics.sharpe_1y,
            FundRiskMetrics.manager_score,
            InstrumentOrg.id.label("org_id"),  # non-null = in universe
        )
        .join(
            latest_risk,
            Instrument.instrument_id == latest_risk.c.instrument_id,
            isouter=True,
        )
        .join(
            FundRiskMetrics,
            (FundRiskMetrics.instrument_id == latest_risk.c.instrument_id)
            & (FundRiskMetrics.calc_date == latest_risk.c.max_date),
            isouter=True,
        )
        .join(
            InstrumentOrg,
            InstrumentOrg.instrument_id == Instrument.instrument_id,
            isouter=True,
        )
        .where(
            Instrument.is_active == True,  # noqa: E712
            Instrument.is_institutional == True,  # noqa: E712
        )
    )

    # Filter by strategy_label via JSONB
    # strategy_label is stored in attributes->>'strategy_label'
    strategy_filter = Instrument.attributes["strategy_label"].astext.in_(list(all_labels))
    stmt = stmt.where(strategy_filter)

    result = await db.execute(stmt)
    rows = result.all()

    # Map rows to FundCandidate, assigning block_id based on strategy_label
    candidates: list[FundCandidate] = []
    block_counts: dict[str, int] = defaultdict(int)

    # Sort by manager_score desc to take top N per block
    sorted_rows = sorted(
        rows,
        key=lambda r: float(r.manager_score) if r.manager_score else 0.0,
        reverse=True,
    )

    for row in sorted_rows:
        attrs = row.attributes or {}
        sl = attrs.get("strategy_label", "")
        # Determine which gap blocks this candidate matches
        from vertical_engines.wealth.model_portfolio.block_mapping import blocks_for_strategy_label

        matched_blocks = blocks_for_strategy_label(sl)
        for block_id in matched_blocks:
            if block_id not in gap_block_ids:
                continue
            if block_counts[block_id] >= max_per_block:
                continue
            block_counts[block_id] += 1

            # Determine external_id (CIK or ISIN)
            ext_id = str(attrs.get("sec_cik", "")) or str(row.isin or "")

            candidates.append(FundCandidate(
                instrument_id=str(row.instrument_id),
                name=row.name,
                ticker=row.ticker,
                block_id=block_id,
                strategy_label=sl or None,
                volatility_1y=float(row.volatility_1y) if row.volatility_1y else None,
                sharpe_1y=float(row.sharpe_1y) if row.sharpe_1y else None,
                manager_score=float(row.manager_score) if row.manager_score else None,
                in_universe=row.org_id is not None,
                external_id=ext_id,
            ))

    logger.info(
        "candidates_discovered",
        gap_blocks=gap_block_ids,
        n_candidates=len(candidates),
        block_counts=dict(block_counts),
    )
    return candidates


async def _fetch_returns_by_type(
    db: AsyncSession,
    candidate_ids: list[uuid.UUID],
    return_type: str,
    date_floor: date,
) -> dict[str, list[float]]:
    """Fetch daily returns for a single return_type. Internal helper."""
    stmt = (
        select(
            NavTimeseries.instrument_id,
            NavTimeseries.nav_date,
            NavTimeseries.return_1d,
        )
        .where(
            NavTimeseries.instrument_id.in_(candidate_ids),
            NavTimeseries.nav_date >= date_floor,
            NavTimeseries.return_1d.is_not(None),
            NavTimeseries.return_type == return_type,
        )
        .order_by(NavTimeseries.instrument_id, NavTimeseries.nav_date)
    )
    result = await db.execute(stmt)

    fund_returns: dict[str, list[float]] = defaultdict(list)
    for inst_id, _nav_date, ret_1d in result.all():
        fund_returns[str(inst_id)].append(float(ret_1d))
    return dict(fund_returns)


async def fetch_candidate_returns(
    db: AsyncSession,
    candidate_ids: list[uuid.UUID],
    lookback_days: int = 504,
) -> dict[str, np.ndarray]:
    """Fetch daily returns for candidates using date floor (never LIMIT).

    Returns {instrument_id_str: (T,) ndarray} for candidates with
    >= MIN_CANDIDATE_NAV_DAYS observations.

    Queries both return types in parallel and prefers log over arithmetic.
    """
    if not candidate_ids:
        return {}

    date_floor = date.today() - timedelta(days=int(lookback_days * 1.5))

    # Fire both return-type queries concurrently
    log_task = _fetch_returns_by_type(db, candidate_ids, "log", date_floor)
    arith_task = _fetch_returns_by_type(db, candidate_ids, "arithmetic", date_floor)
    log_returns, arith_returns = await asyncio.gather(log_task, arith_task)

    # Prefer log, fall back to arithmetic per-fund
    def _qualify(raw: dict[str, list[float]]) -> dict[str, list[float]]:
        return {fid: rets for fid, rets in raw.items() if len(rets) >= MIN_CANDIDATE_NAV_DAYS}

    qualified_log = _qualify(log_returns)
    if qualified_log:
        # Use log for all funds that qualify; fill gaps from arithmetic
        qualified_arith = _qualify(arith_returns)
        merged = {**qualified_arith, **qualified_log}  # log takes precedence
        return {fid: np.array(rets) for fid, rets in merged.items()}

    # No log data at all — fall back to arithmetic only
    qualified_arith = _qualify(arith_returns)
    if qualified_arith:
        return {fid: np.array(rets) for fid, rets in qualified_arith.items()}

    return {}


async def _fetch_portfolio_nav_by_type(
    db: AsyncSession,
    fund_ids: list[uuid.UUID],
    return_type: str,
    date_floor: date,
) -> dict[str, dict[date, float]]:
    """Fetch per-fund date→return map for a single return_type. Internal helper."""
    stmt = (
        select(
            NavTimeseries.instrument_id,
            NavTimeseries.nav_date,
            NavTimeseries.return_1d,
        )
        .where(
            NavTimeseries.instrument_id.in_(fund_ids),
            NavTimeseries.nav_date >= date_floor,
            NavTimeseries.return_1d.is_not(None),
            NavTimeseries.return_type == return_type,
        )
        .order_by(NavTimeseries.nav_date)
    )
    result = await db.execute(stmt)

    by_date: dict[str, dict[date, float]] = defaultdict(dict)
    for inst_id, nav_date, ret_1d in result.all():
        by_date[str(inst_id)][nav_date] = float(ret_1d)
    return dict(by_date)


async def fetch_portfolio_returns(
    db: AsyncSession,
    fund_selection: dict[str, Any],
    lookback_days: int = 504,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fetch daily returns for the current portfolio funds.

    Returns:
        (portfolio_daily_returns (T,N), portfolio_returns (T,), current_weights (N,))
        where portfolio_returns = daily_returns @ weights.

    Queries both return types in parallel and prefers log over arithmetic.
    """
    funds = fund_selection.get("funds", [])
    if not funds:
        return np.array([]), np.array([]), np.array([])

    fund_ids = [uuid.UUID(f["instrument_id"]) for f in funds]
    weights = np.array([f["weight"] for f in funds])

    date_floor = date.today() - timedelta(days=int(lookback_days * 1.5))

    # Fire both return-type queries concurrently
    log_map, arith_map = await asyncio.gather(
        _fetch_portfolio_nav_by_type(db, fund_ids, "log", date_floor),
        _fetch_portfolio_nav_by_type(db, fund_ids, "arithmetic", date_floor),
    )

    # Prefer log; fill gaps from arithmetic per-fund
    fund_returns_by_date: dict[str, dict[date, float]] = {}
    for fid_str in {str(fid) for fid in fund_ids}:
        if fid_str in log_map and len(log_map[fid_str]) >= MIN_CANDIDATE_NAV_DAYS:
            fund_returns_by_date[fid_str] = log_map[fid_str]
        elif fid_str in arith_map and len(arith_map[fid_str]) >= MIN_CANDIDATE_NAV_DAYS:
            fund_returns_by_date[fid_str] = arith_map[fid_str]

    available = [str(fid) for fid in fund_ids if str(fid) in fund_returns_by_date]

    if len(available) < 2:
        return np.array([]), np.array([]), weights

    # Date intersection
    all_dates = [set(fund_returns_by_date[fid].keys()) for fid in available]
    common_dates = sorted(set.intersection(*all_dates))
    if len(common_dates) < MIN_CANDIDATE_NAV_DAYS:
        return np.array([]), np.array([]), weights

    # Re-index weights to available funds only
    fid_order = [str(fid) for fid in fund_ids]
    available_indices = [fid_order.index(fid) for fid in available]
    aligned_weights = weights[available_indices]
    # Renormalize
    w_sum = aligned_weights.sum()
    if w_sum > 0:
        aligned_weights = aligned_weights / w_sum

    # Build (T, N) returns matrix
    daily_returns = np.array([
        [fund_returns_by_date[fid][d] for fid in available]
        for d in common_dates
    ])

    # Weighted portfolio return series (T,)
    portfolio_returns = daily_returns @ aligned_weights

    return daily_returns, portfolio_returns, aligned_weights


async def fetch_candidate_holdings(
    db: AsyncSession,
    candidate_ids: list[uuid.UUID],
) -> dict[str, set[str]]:
    """Fetch latest N-PORT CUSIP sets for candidate funds.

    Returns {instrument_id_str: set_of_cusips}.
    Candidates without N-PORT data are absent from the result.
    """
    if not candidate_ids:
        return {}

    # Resolve sec_cik from instrument attributes
    inst_stmt = select(
        Instrument.instrument_id,
        Instrument.attributes,
    ).where(Instrument.instrument_id.in_(candidate_ids))
    inst_result = await db.execute(inst_stmt)

    inst_to_cik: dict[str, str] = {}
    for row in inst_result.all():
        attrs = row.attributes or {}
        cik = attrs.get("sec_cik")
        if cik:
            inst_to_cik[str(row.instrument_id)] = str(cik)

    if not inst_to_cik:
        return {}

    cik_to_inst = {cik: iid for iid, cik in inst_to_cik.items()}
    cik_list = list(cik_to_inst.keys())

    # Latest N-PORT report per CIK
    latest_subq = (
        select(
            SecNportHolding.cik,
            func.max(SecNportHolding.report_date).label("max_date"),
        )
        .where(SecNportHolding.cik.in_(cik_list))
        .group_by(SecNportHolding.cik)
        .subquery()
    )

    holdings_stmt = (
        select(SecNportHolding.cik, SecNportHolding.cusip)
        .join(
            latest_subq,
            (SecNportHolding.cik == latest_subq.c.cik)
            & (SecNportHolding.report_date == latest_subq.c.max_date),
        )
        .where(
            SecNportHolding.cik.in_(cik_list),
            SecNportHolding.cusip.is_not(None),
        )
    )

    result = await db.execute(holdings_stmt)

    holdings: dict[str, set[str]] = defaultdict(set)
    for row in result.all():
        inst_id = cik_to_inst.get(row.cik)
        if inst_id:
            holdings[inst_id].add(row.cusip)

    return dict(holdings)


async def fetch_portfolio_holdings_cusips(
    db: AsyncSession,
    fund_selection: dict[str, Any],
) -> set[str]:
    """Get the set of CUSIPs held by the current portfolio funds."""
    funds = fund_selection.get("funds", [])
    if not funds:
        return set()

    fund_ids = [uuid.UUID(f["instrument_id"]) for f in funds]

    # Resolve CIKs
    inst_stmt = select(
        Instrument.instrument_id,
        Instrument.attributes,
    ).where(Instrument.instrument_id.in_(fund_ids))
    inst_result = await db.execute(inst_stmt)

    cik_list: list[str] = []
    for row in inst_result.all():
        attrs = row.attributes or {}
        cik = attrs.get("sec_cik")
        if cik:
            cik_list.append(str(cik))

    if not cik_list:
        return set()

    latest_subq = (
        select(
            SecNportHolding.cik,
            func.max(SecNportHolding.report_date).label("max_date"),
        )
        .where(SecNportHolding.cik.in_(cik_list))
        .group_by(SecNportHolding.cik)
        .subquery()
    )

    stmt = (
        select(SecNportHolding.cusip)
        .join(
            latest_subq,
            (SecNportHolding.cik == latest_subq.c.cik)
            & (SecNportHolding.report_date == latest_subq.c.max_date),
        )
        .where(
            SecNportHolding.cik.in_(cik_list),
            SecNportHolding.cusip.is_not(None),
        )
    )
    result = await db.execute(stmt)
    return {row[0] for row in result.all()}
