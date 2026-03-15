"""Market data service — daily-cached macro snapshot orchestrator.

Error contract: never-raises (orchestration engine called during deep review).
Returns cached or freshly-fetched macro snapshot with stress severity.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.shared.models import MacroSnapshot
from vertical_engines.credit.market_data.regional import fetch_regional_case_shiller
from vertical_engines.credit.market_data.snapshot import (
    _build_macro_snapshot,
    _snapshot_hash,
)

logger = structlog.get_logger()


def get_macro_snapshot(
    db: Session,
    *,
    force_refresh: bool = False,
    deal_geography: str | None = None,
) -> dict[str, Any]:
    """Return today's macro snapshot, fetching from FRED if not cached.

    NEW in v2: deal_geography triggers regional Case-Shiller fetch.
    Regional data is NOT cached (deal-specific) — always fetched live
    and merged into the cached base snapshot at runtime.

    Cache logic:
      1. Check macro_snapshots table for today's date.
      2. If found AND populated AND valid schema -> return cached.
         If deal_geography -> merge regional data before returning.
      3. If found but all-null or legacy schema (no schema_version key) -> delete + refetch.
      4. If not found -> build expanded snapshot, persist base, return.
      5. force_refresh -> always delete today's cache + refetch.

    Backward compatible: callers without deal_geography get the same
    behavior, with additional time-series fields in the v2 snapshot.
    """
    today = dt.date.today()

    # Check / invalidate cache
    cached = db.execute(
        select(MacroSnapshot).where(MacroSnapshot.as_of_date == today),
    ).scalar_one_or_none()

    _VALUE_KEYS = (
        "risk_free_10y", "risk_free_2y", "baa_spread",
        "unemployment_rate", "financial_conditions_index",
    )

    if cached is not None:
        data = cached.data_json or {}
        is_empty = all(data.get(k) is None for k in _VALUE_KEYS)

        if force_refresh or is_empty:
            reason = "force_refresh" if force_refresh else "all_null_poisoned_cache"
            logger.warning(
                "market_data_cache_invalidated",
                as_of=today.isoformat(),
                reason=reason,
            )
            with db.begin_nested():
                db.delete(cached)
            cached = None
        else:
            logger.info("market_data_cache_hit", as_of=today.isoformat())
            base_snapshot = data
            # Merge deal-specific regional data (never stored in cache)
            if deal_geography:
                regional = fetch_regional_case_shiller(deal_geography, observations=24)
                if regional:
                    base_snapshot = dict(base_snapshot)
                    base_snapshot["regional"] = {"case_shiller_metro": regional}
                    nat_yoy = (
                        (base_snapshot.get("real_estate_national") or {})
                        .get("CSUSHPINSA", {})
                        .get("delta_12m_pct")
                    )
                    metro_yoy = regional.get("delta_12m_pct")
                    if nat_yoy is not None and metro_yoy is not None:
                        base_snapshot["regional"]["national_vs_metro_delta"] = round(
                            metro_yoy - nat_yoy, 2,
                        )
            return base_snapshot

    # Fetch from FRED using the backward-compatible builder entrypoint.
    # Build base snapshot WITHOUT regional (base is deal-agnostic/cacheable)
    snapshot: dict[str, Any] = {}
    try:
        snapshot = _build_macro_snapshot(deal_geography=None)
    except Exception as exc:
        fallback = db.execute(
            select(MacroSnapshot)
            .where(MacroSnapshot.as_of_date < today)
            .order_by(MacroSnapshot.as_of_date.desc()),
        ).scalar_one_or_none()
        if fallback and fallback.data_json:
            logger.warning(
                "market_data_fallback_cache_hit",
                as_of=today.isoformat(),
                fallback_as_of=fallback.as_of_date.isoformat(),
                error=str(exc),
            )
            snapshot = dict(fallback.data_json)
        else:
            raise ValueError("FRED failed and no cached macro snapshot available") from exc

    # Persist base snapshot
    new_snapshot = MacroSnapshot(as_of_date=today, data_json=snapshot)
    try:
        with db.begin_nested():
            db.add(new_snapshot)
    except Exception:
        db.rollback()
        cached = db.execute(
            select(MacroSnapshot).where(MacroSnapshot.as_of_date == today),
        ).scalar_one_or_none()
        if cached and cached.data_json:
            logger.info("market_data_race_recovered", as_of=today.isoformat())
            snapshot = dict(cached.data_json)
        else:
            logger.warning("market_data_persist_failed", as_of=today.isoformat())

    logger.info(
        "market_data_persisted",
        as_of=today.isoformat(),
        hash=_snapshot_hash(snapshot),
    )

    # Merge regional AFTER persisting (deal-specific, not stored)
    if deal_geography:
        regional = fetch_regional_case_shiller(deal_geography, observations=24)
        if regional:
            snapshot = dict(snapshot)
            snapshot["regional"] = {"case_shiller_metro": regional}
            nat_yoy = (
                (snapshot.get("real_estate_national") or {})
                .get("CSUSHPINSA", {})
                .get("delta_12m_pct")
            )
            metro_yoy = regional.get("delta_12m_pct")
            if nat_yoy is not None and metro_yoy is not None:
                snapshot["regional"]["national_vs_metro_delta"] = round(
                    metro_yoy - nat_yoy, 2,
                )

    return snapshot
