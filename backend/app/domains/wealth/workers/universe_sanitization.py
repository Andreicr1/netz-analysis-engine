"""Worker: universe_sanitization — flag non-institutional vehicles so
downstream consumers (strategy_reclassification, candidate_screener,
catalog_sql, mv_unified_funds) stop polluting peer groups and scoring
percentiles with retirement, CIT, education, SMA, and sub-scale funds.

Advisory lock : 900_063 (deterministic literal)
Frequency     : on-demand. Run AFTER sec_adv_ingestion, sec_bulk_ingestion,
                esma_ingestion; BEFORE strategy_reclassification.
Idempotent    : yes — every invocation first resets flags to TRUE on all
                rows, then re-applies the rule cascade. A second run with
                the same source data produces the same per-reason counts.

Design notes
------------
* **Stored column, not a view.** Gives a permanent audit trail
  (``exclusion_reason``) and keeps downstream queries cheap.
* **First match wins.** ``exclusion_reason IS NULL`` is the gate; once a
  row is flagged with e.g. ``retirement`` it will not be re-flagged as
  ``cit`` in a later rule. The ordering of rules matters for reporting
  but not for the final institutional/non-institutional bit.
* **No external fetches.** Everything reads from already-ingested tables.
* **Per-rule commit.** Each rule commits on its own so a crash mid-run
  preserves partial progress and the idempotent reset on the next run
  cleans it up.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory as async_session

SANITIZATION_LOCK_ID = 900_063
GAV_FLOOR_USD = 3_000_000_000  # $3B manager GAV floor

logger: Any = structlog.get_logger()


# ── Exclusion keyword patterns (PostgreSQL POSIX regex, case-insensitive) ──

PATTERN_RETIREMENT = (
    r"(\m401\(?k\)?|\m403\(?b\)?|\m457\M|"
    r"\mIRA\M|\mSEP\s+IRA|\mSIMPLE\s+IRA|"
    r"ERISA|retirement|pension\s+plan|"
    r"\mESOP\M|employee\s+stock\s+ownership|"
    r"\mtarget\s+(date|retirement)\M)"
)

PATTERN_CIT = (
    r"(collective\s+(investment\s+)?trust|"
    r"\mCIT\M\s+fund|"  # avoid false positives on bank abbreviations
    r"common\s+(investment\s+)?fund|"
    r"bank\s+collective)"
)

PATTERN_EDUCATION = (
    r"(\m529\s*(plan|portfolio)|"
    r"coverdell|"
    r"education\s+savings)"
)

PATTERN_INSURANCE = (
    r"(stable\s+value|"
    r"guaranteed\s+(income|interest|annuity)|"
    r"insurance.{0,10}wrap|"
    r"\mGIC\M|guaranteed\s+investment\s+contract|"
    r"fixed\s+annuity)"
)

PATTERN_SMA_WRAP = (
    r"(\mSMA\M\s+(program|platform)|"
    r"separately\s+managed|"
    r"wrap\s+(account|program|fee)|"
    r"managed\s+account\s+program|"
    r"\mUMA\M)"  # unified managed account
)

_SOURCE_TABLES: tuple[str, ...] = (
    "sec_manager_funds",
    "sec_registered_funds",
    "sec_etfs",
    "sec_bdcs",
    "sec_money_market_funds",
    "esma_funds",
)


# ───────────────────────────────────────────────────────────────────
# Public entry point
# ───────────────────────────────────────────────────────────────────


async def run_universe_sanitization() -> dict[str, Any]:
    """Apply sanitization rules across all fund tables.

    Returns a dict with ``per_table`` mapping to per-reason counters
    plus an ``institutional`` / ``excluded`` / ``total`` summary block.
    """
    started = datetime.now(timezone.utc)
    result: dict[str, Any] = {
        "started_at": started.isoformat(),
        "per_table": {},
    }

    async with async_session() as db:
        lock_row = await db.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": SANITIZATION_LOCK_ID},
        )
        if not lock_row.scalar():
            logger.warning("sanitization_skipped", reason="lock_contention")
            return {"skipped": True, "reason": "lock_contention"}

        try:
            await _reset_flags(db)
            await db.commit()

            result["per_table"]["sec_manager_funds"] = (
                await _sanitize_sec_manager_funds(db)
            )
            await db.commit()

            result["per_table"]["sec_registered_funds"] = (
                await _sanitize_sec_registered_funds(db)
            )
            await db.commit()

            result["per_table"]["sec_etfs"] = await _sanitize_sec_etfs(db)
            await db.commit()

            # sec_bdcs: no rules today (all public BDCs are institutional).
            # Still report the summary for the audit trail.
            result["per_table"]["sec_bdcs"] = await _summary(db, "sec_bdcs")

            result["per_table"]["sec_money_market_funds"] = (
                await _sanitize_sec_mmfs(db)
            )
            await db.commit()

            result["per_table"]["esma_funds"] = await _sanitize_esma_funds(db)
            await db.commit()

            await _propagate_to_instruments_universe(db)
            await db.commit()

            finished = datetime.now(timezone.utc)
            result["completed_at"] = finished.isoformat()
            result["duration_seconds"] = (finished - started).total_seconds()

        finally:
            await db.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": SANITIZATION_LOCK_ID},
            )
            await db.commit()

    return result


# ───────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────


async def _reset_flags(db: AsyncSession) -> None:
    """Reset every row to institutional=true so the run is idempotent."""
    for table in _SOURCE_TABLES:
        await db.execute(
            text(
                f"UPDATE {table} "
                f"SET is_institutional = true, "
                f"    exclusion_reason = NULL, "
                f"    sanitized_at = NOW()",
            ),
        )
    logger.info("sanitization_flags_reset")


async def _summary(db: AsyncSession, table: str) -> dict[str, int]:
    """Return institutional / excluded / total counts for a table."""
    row = (
        await db.execute(
            text(
                f"SELECT "
                f"  COUNT(*) FILTER (WHERE is_institutional) AS institutional, "
                f"  COUNT(*) FILTER (WHERE NOT is_institutional) AS excluded, "
                f"  COUNT(*) AS total "
                f"FROM {table}",
            ),
        )
    ).one()
    return dict(row._mapping)


# ───────────────────────────────────────────────────────────────────
# sec_manager_funds — highest-risk table, 62k rows
# ───────────────────────────────────────────────────────────────────


async def _sanitize_sec_manager_funds(db: AsyncSession) -> dict[str, int]:
    """Rules:
      1. retirement / ERISA (name regex)
      2. CIT (name regex)
      3. education (name regex)
      4. insurance-wrapped (name regex)
      5. SMA / wrap (name regex)
      6. GAV floor $3B at manager level
      7. retail adviser (client_types JSONB)
      8. duplicate multi-adviser filings (keep largest adviser)
    """
    counts: dict[str, int] = {}

    for reason, pattern in (
        ("retirement", PATTERN_RETIREMENT),
        ("cit", PATTERN_CIT),
        ("education", PATTERN_EDUCATION),
        ("insurance_wrapped", PATTERN_INSURANCE),
        ("sma_wrap", PATTERN_SMA_WRAP),
    ):
        r = await db.execute(
            text(
                "UPDATE sec_manager_funds "
                "SET is_institutional = false, "
                "    exclusion_reason = :reason, "
                "    sanitized_at = NOW() "
                "WHERE is_institutional = true "
                "  AND exclusion_reason IS NULL "
                "  AND fund_name ~* :pattern",
            ),
            {"reason": reason, "pattern": pattern},
        )
        counts[reason] = r.rowcount or 0

    # Rule 6 — GAV floor at the manager level
    r = await db.execute(
        text(
            "UPDATE sec_manager_funds f "
            "SET is_institutional = false, "
            "    exclusion_reason = 'gav_below_3b', "
            "    sanitized_at = NOW() "
            "FROM sec_managers m "
            "WHERE f.crd_number = m.crd_number "
            "  AND f.is_institutional = true "
            "  AND f.exclusion_reason IS NULL "
            "  AND COALESCE(m.total_private_fund_assets, 0) < :floor",
        ),
        {"floor": GAV_FLOOR_USD},
    )
    counts["gav_below_3b"] = r.rowcount or 0

    # Rule 7 — retail adviser heuristic: REMOVED.
    #
    # Original design: flag managers with >500 individual clients OR <2
    # pooled vehicles. Empirical validation against the 2026-04-14 DB
    # snapshot showed this catches foundational institutional managers
    # (PIMCO, Neuberger Berman, Lazard, Western Asset, Franklin, UBS AM)
    # because top-tier firms run both wealth platforms (thousands of
    # individual clients) and institutional private fund books. 1,185
    # funds from the top of the league table were false-flagged.
    #
    # ``client_types`` alone cannot separate "institutional manager with
    # wealth platform" from "retail RIA". The $3B GAV floor above
    # already filters the genuinely small RIAs, and ``duplicate_filing``
    # cleans multi-adviser noise. If later data shows residual retail
    # pollution, revisit with a stricter signal such as
    # ``individuals_pct_aum > 90%`` once that granularity is populated.

    # Rule 8 — duplicate multi-adviser filings. For a fund reported by
    # multiple CRDs with the same (fund_name, GAV), keep the adviser with
    # the largest AUM. Ties fall to the lexicographically smaller CRD.
    r = await db.execute(
        text(
            """
            WITH dupes AS (
                SELECT
                    f.id,
                    ROW_NUMBER() OVER (
                        PARTITION BY f.fund_name, f.gross_asset_value
                        ORDER BY m.aum_total DESC NULLS LAST, f.crd_number
                    ) AS rn
                FROM sec_manager_funds f
                JOIN sec_managers m ON f.crd_number = m.crd_number
                WHERE f.is_institutional = true
                  AND f.exclusion_reason IS NULL
                  AND f.fund_name IS NOT NULL
                  AND f.gross_asset_value IS NOT NULL
            )
            UPDATE sec_manager_funds f
            SET is_institutional = false,
                exclusion_reason = 'duplicate_filing',
                sanitized_at = NOW()
            FROM dupes d
            WHERE f.id = d.id
              AND d.rn > 1
            """,
        ),
    )
    counts["duplicate_filing"] = r.rowcount or 0

    counts.update(await _summary(db, "sec_manager_funds"))
    logger.info("sec_manager_funds_sanitized", **counts)
    return counts


# ───────────────────────────────────────────────────────────────────
# sec_registered_funds — mutual funds, closed-end, interval
# ───────────────────────────────────────────────────────────────────


async def _sanitize_sec_registered_funds(db: AsyncSession) -> dict[str, int]:
    """Rules:
      1. retirement keywords in name
      2. is_target_date flag from N-CEN
      3. sub-scale (< $100M aggregate net assets across share classes)
    """
    counts: dict[str, int] = {}

    r = await db.execute(
        text(
            "UPDATE sec_registered_funds "
            "SET is_institutional = false, "
            "    exclusion_reason = 'retirement', "
            "    sanitized_at = NOW() "
            "WHERE is_institutional = true "
            "  AND exclusion_reason IS NULL "
            "  AND fund_name ~* :pattern",
        ),
        {"pattern": PATTERN_RETIREMENT},
    )
    counts["retirement"] = r.rowcount or 0

    r = await db.execute(
        text(
            "UPDATE sec_registered_funds "
            "SET is_institutional = false, "
            "    exclusion_reason = 'target_date', "
            "    sanitized_at = NOW() "
            "WHERE is_institutional = true "
            "  AND exclusion_reason IS NULL "
            "  AND COALESCE(is_target_date, false) = true",
        ),
    )
    counts["target_date"] = r.rowcount or 0

    # Aggregate share-class net_assets (XBRL-enriched column on
    # sec_fund_classes) and exclude sub-$100M funds. The fund table PK
    # is ``cik``; so is the share-class table.
    r = await db.execute(
        text(
            """
            UPDATE sec_registered_funds f
            SET is_institutional = false,
                exclusion_reason = 'sub_scale',
                sanitized_at = NOW()
            FROM (
                SELECT cik, SUM(net_assets) AS total_aum
                FROM sec_fund_classes
                WHERE net_assets IS NOT NULL
                GROUP BY cik
            ) agg
            WHERE f.cik = agg.cik
              AND f.is_institutional = true
              AND f.exclusion_reason IS NULL
              AND agg.total_aum < 100000000
            """,
        ),
    )
    counts["sub_scale"] = r.rowcount or 0

    counts.update(await _summary(db, "sec_registered_funds"))
    logger.info("sec_registered_funds_sanitized", **counts)
    return counts


# ───────────────────────────────────────────────────────────────────
# sec_etfs
# ───────────────────────────────────────────────────────────────────


async def _sanitize_sec_etfs(db: AsyncSession) -> dict[str, int]:
    """Rules:
      1. retirement-focused ETFs (target date)
      2. leveraged / inverse retail exotics below $100M AUM
    """
    counts: dict[str, int] = {}

    r = await db.execute(
        text(
            "UPDATE sec_etfs "
            "SET is_institutional = false, "
            "    exclusion_reason = 'retirement', "
            "    sanitized_at = NOW() "
            "WHERE is_institutional = true "
            "  AND exclusion_reason IS NULL "
            "  AND fund_name ~* :pattern",
        ),
        {"pattern": PATTERN_RETIREMENT},
    )
    counts["retirement"] = r.rowcount or 0

    # ETF model exposes monthly_avg_net_assets (no raw net_assets column).
    r = await db.execute(
        text(
            r"""
            UPDATE sec_etfs
            SET is_institutional = false,
                exclusion_reason = 'leveraged_retail',
                sanitized_at = NOW()
            WHERE is_institutional = true
              AND exclusion_reason IS NULL
              AND fund_name ~* '(\m(2x|3x|-?1x|-?2x|-?3x)\M|leveraged|inverse|ultra)'
              AND COALESCE(monthly_avg_net_assets, 0) < 100000000
            """,
        ),
    )
    counts["leveraged_retail"] = r.rowcount or 0

    counts.update(await _summary(db, "sec_etfs"))
    logger.info("sec_etfs_sanitized", **counts)
    return counts


# ───────────────────────────────────────────────────────────────────
# sec_money_market_funds
# ───────────────────────────────────────────────────────────────────


async def _sanitize_sec_mmfs(db: AsyncSession) -> dict[str, int]:
    """Rules:
      1. retirement / insurance-wrapped MMFs (name regex)
      2. retail-only MMFs (mmf_category)
    """
    counts: dict[str, int] = {}

    r = await db.execute(
        text(
            "UPDATE sec_money_market_funds "
            "SET is_institutional = false, "
            "    exclusion_reason = 'retirement_or_insurance', "
            "    sanitized_at = NOW() "
            "WHERE is_institutional = true "
            "  AND exclusion_reason IS NULL "
            "  AND (fund_name ~* :pattern_retirement "
            "       OR fund_name ~* :pattern_insurance)",
        ),
        {
            "pattern_retirement": PATTERN_RETIREMENT,
            "pattern_insurance": PATTERN_INSURANCE,
        },
    )
    counts["retirement_or_insurance"] = r.rowcount or 0

    # Retail MMFs expose a boolean ``is_retail`` flag populated from
    # N-MFP (``mmf_category`` is the investment style — Government,
    # Prime, Tax Exempt — not the retail/institutional split).
    r = await db.execute(
        text(
            """
            UPDATE sec_money_market_funds
            SET is_institutional = false,
                exclusion_reason = 'retail_mmf',
                sanitized_at = NOW()
            WHERE is_institutional = true
              AND exclusion_reason IS NULL
              AND is_retail IS TRUE
            """,
        ),
    )
    counts["retail_mmf"] = r.rowcount or 0

    counts.update(await _summary(db, "sec_money_market_funds"))
    logger.info("sec_money_market_funds_sanitized", **counts)
    return counts


# ───────────────────────────────────────────────────────────────────
# esma_funds
# ───────────────────────────────────────────────────────────────────


async def _sanitize_esma_funds(db: AsyncSession) -> dict[str, int]:
    """Rules:
      1. retirement / pension focused UCITS (name regex)
      2. EU-specific pension wrappers (PEPP, IORP)

    Note: sub-scale AUM filtering is intentionally skipped — the
    ``esma_funds`` table has no AUM column today.
    """
    counts: dict[str, int] = {}

    r = await db.execute(
        text(
            "UPDATE esma_funds "
            "SET is_institutional = false, "
            "    exclusion_reason = 'retirement', "
            "    sanitized_at = NOW() "
            "WHERE is_institutional = true "
            "  AND exclusion_reason IS NULL "
            "  AND fund_name ~* :pattern",
        ),
        {"pattern": PATTERN_RETIREMENT},
    )
    counts["retirement"] = r.rowcount or 0

    r = await db.execute(
        text(
            r"""
            UPDATE esma_funds
            SET is_institutional = false,
                exclusion_reason = 'eu_pension',
                sanitized_at = NOW()
            WHERE is_institutional = true
              AND exclusion_reason IS NULL
              AND fund_name ~* '(\mPEPP\M|pan.?european\s+pension|\mIORP\M|occupational\s+pension)'
            """,
        ),
    )
    counts["eu_pension"] = r.rowcount or 0

    counts.update(await _summary(db, "esma_funds"))
    logger.info("esma_funds_sanitized", **counts)
    return counts


# ───────────────────────────────────────────────────────────────────
# Propagate to instruments_universe via JSONB attributes
# ───────────────────────────────────────────────────────────────────


async def _propagate_to_instruments_universe(db: AsyncSession) -> None:
    """Fold is_institutional + exclusion_reason into instruments_universe.

    The ``is_institutional`` column on ``instruments_universe`` is GENERATED
    from ``attributes->>'is_institutional'``; writing to the JSONB
    attributes is enough to update the column.
    """
    # sec_manager_funds — joined via sec_crd + fund_name
    await db.execute(
        text(
            """
            UPDATE instruments_universe iu
            SET attributes = COALESCE(iu.attributes, '{}'::jsonb)
                || jsonb_build_object(
                    'is_institutional', f.is_institutional,
                    'exclusion_reason', f.exclusion_reason
                )
            FROM sec_manager_funds f
            WHERE iu.attributes->>'sec_crd' = f.crd_number
              AND iu.attributes->>'fund_name' = f.fund_name
            """,
        ),
    )

    # sec_registered_funds — joined via sec_cik
    await db.execute(
        text(
            """
            UPDATE instruments_universe iu
            SET attributes = COALESCE(iu.attributes, '{}'::jsonb)
                || jsonb_build_object(
                    'is_institutional', f.is_institutional,
                    'exclusion_reason', f.exclusion_reason
                )
            FROM sec_registered_funds f
            WHERE iu.attributes->>'sec_cik' = f.cik::text
               OR iu.instrument_id IN (
                   SELECT instrument_id FROM instrument_identity
                   WHERE cik_unpadded = LTRIM(f.cik::text, '0')
                      OR cik_padded = f.cik::text
               )
            """,
        ),
    )

    # sec_etfs — joined via series_id
    await db.execute(
        text(
            """
            UPDATE instruments_universe iu
            SET attributes = COALESCE(iu.attributes, '{}'::jsonb)
                || jsonb_build_object(
                    'is_institutional', f.is_institutional,
                    'exclusion_reason', f.exclusion_reason
                )
            FROM sec_etfs f
            WHERE iu.attributes->>'series_id' = f.series_id
            """,
        ),
    )

    # sec_bdcs — joined via series_id
    await db.execute(
        text(
            """
            UPDATE instruments_universe iu
            SET attributes = COALESCE(iu.attributes, '{}'::jsonb)
                || jsonb_build_object(
                    'is_institutional', f.is_institutional,
                    'exclusion_reason', f.exclusion_reason
                )
            FROM sec_bdcs f
            WHERE iu.attributes->>'series_id' = f.series_id
            """,
        ),
    )

    # sec_money_market_funds — joined via series_id
    await db.execute(
        text(
            """
            UPDATE instruments_universe iu
            SET attributes = COALESCE(iu.attributes, '{}'::jsonb)
                || jsonb_build_object(
                    'is_institutional', f.is_institutional,
                    'exclusion_reason', f.exclusion_reason
                )
            FROM sec_money_market_funds f
            WHERE iu.attributes->>'series_id' = f.series_id
            """,
        ),
    )

    # esma_funds — joined via fund_lei attribute (post-Q11B)
    # Transition fallback: also match by legacy isin attribute = lei
    await db.execute(
        text(
            """
            UPDATE instruments_universe iu
            SET attributes = COALESCE(iu.attributes, '{}'::jsonb)
                || jsonb_build_object(
                    'is_institutional', f.is_institutional,
                    'exclusion_reason', f.exclusion_reason
                )
            FROM esma_funds f
            WHERE iu.attributes->>'fund_lei' = f.lei
               OR iu.attributes->>'isin' = f.lei
            """,
        ),
    )

    logger.info("instruments_universe_flag_propagated")
