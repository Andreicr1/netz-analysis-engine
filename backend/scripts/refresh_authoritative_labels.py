"""PR-A26.3.2 — refresh ``instruments_universe.attributes->>'strategy_label'``
from authoritative regulatory sources, falling back to the Tiingo
description cascade only when no authoritative source is available.

Priority ladder (per active instrument):

1. ``sec_money_market_funds`` matched on series_id (``iu.attributes->>'series_id'``
   or ``iu.isin`` when it begins with ``S0``). CIK is intentionally NOT used
   as a bridge — it is the issuer-level registrant identifier.
2. ``sec_etfs`` matched on series_id first, then ``ticker`` as fallback.
3. ``sec_bdcs`` matched on series_id.
4. ``esma_funds`` matched on real ``isin`` (skips IU rows storing series_id).
5. Most recent high-confidence ``strategy_reclassification_stage`` row
   with ``classification_source='tiingo_description'``.
6. Else: NULL with ``attributes.needs_human_review = true``.

Default mode is ``--dry-run``. ``--apply`` writes:

* one row to ``strategy_label_authoritative_backup`` per change
* JSONB merge into ``instruments_universe.attributes`` setting
  ``strategy_label``, ``strategy_label_source``,
  ``strategy_label_source_table``, ``strategy_label_refreshed_at``,
  and ``needs_human_review`` (only on the NULL fallback branch).

Re-running after apply is idempotent — the script skips rows already
matching the target.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from app.core.db.engine import async_session_factory
from app.domains.wealth.services.authoritative_label_map import (
    map_bdc_label,
    map_esma_label,
    map_etf_label,
    map_mmf_category,
)

logger = logging.getLogger("refresh_authoritative_labels")

# Tickers that the spec calls out as the regression target; their
# transition is reported separately even when no change occurs so the
# operator can see exactly what each authoritative source delivered.
REGRESSION_TICKERS: tuple[str, ...] = (
    "SCHD",
    "XLF",
    "QQQM",
    "SCHB",
    "FEZ",
    "VMIAX",
    "SPMQX",
)

# Source labels that always trigger a backup row write so the operator
# trail captures even no-op resolutions.
KNOWN_CONTAMINATED_LABELS: frozenset[str] = frozenset(
    {"Real Estate", "Cash Equivalent", "Commodities", "Precious Metals"},
)


@dataclass(frozen=True)
class InstrumentRow:
    instrument_id: str
    ticker: str | None
    isin: str | None  # NOTE: SEC funds store series_id here ("S00..."); ESMA funds store actual ISIN.
    series_id: str | None  # extracted from attributes.series_id (alias of isin for SEC funds).
    fund_name: str | None
    sec_cik: str | None
    current_label: str | None


@dataclass(frozen=True)
class Resolution:
    label: str | None
    source: str  # one of the ladder slot identifiers (see SOURCE_*)
    source_table: str | None
    source_value: str | None  # raw value from the authoritative source
    reason: str


SOURCE_OVERRIDE = "override"
SOURCE_MMF = "sec_mmf"
SOURCE_ETF = "sec_etf"
SOURCE_BDC = "sec_bdc"
SOURCE_ESMA = "esma_funds"
SOURCE_TIINGO = "tiingo_cascade"
SOURCE_NEEDS_REVIEW = "needs_review"

# PR-A26.3.5 Session 1 — FT Vest Buffer family (FJAN..FDEC) share the
# SPY-buffered defined-outcome structure. Collapsed to the canonical
# Balanced label (multi-asset, near-zero residual vol vs SPY). Exact
# tickers resolved via the class-level regex in ``_resolve_override``.
_FT_VEST_BUFFER_RE = re.compile(r"^F(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)$")
_FT_VEST_BUFFER_LABEL = "Balanced"


# ---------------------------------------------------------------------------
# Lookup loaders — load each authoritative table into memory once and index
# it by the bridge column. This keeps the per-instrument loop O(N) instead
# of issuing N×4 round-trips.
# ---------------------------------------------------------------------------


async def _load_override_index(db: Any) -> dict[str, tuple[str, str]]:
    """Return ``{ticker: (strategy_label, rationale)}`` from curated table.

    Priority-0 source (PR-A26.3.5 Session 1). Exact ticker match only —
    class-level families (FT Vest buffer series) are handled via regex
    fallback inside ``_resolve_override``.
    """
    result = await db.execute(
        text(
            "SELECT ticker, strategy_label, rationale "
            "FROM instrument_strategy_overrides"
        )
    )
    return {row.ticker: (row.strategy_label, row.rationale or "") for row in result}


async def _load_mmf_index(db: Any) -> dict[str, tuple[str, str]]:
    """Return ``{series_id: (mmf_category, fund_name)}``.

    Bridge is series_id (not CIK) because CIK is the issuer-level
    registrant identifier — one CIK can host dozens of unrelated funds.
    """
    result = await db.execute(
        text(
            "SELECT series_id, mmf_category, fund_name FROM sec_money_market_funds "
            "WHERE series_id IS NOT NULL"
        )
    )
    return {row.series_id: (row.mmf_category, row.fund_name or "") for row in result}


async def _load_etf_index_by_series(db: Any) -> dict[str, tuple[str, str]]:
    """Return ``{series_id: (strategy_label, fund_name)}``."""
    result = await db.execute(
        text(
            "SELECT series_id, strategy_label, fund_name FROM sec_etfs "
            "WHERE strategy_label IS NOT NULL AND series_id IS NOT NULL"
        )
    )
    return {row.series_id: (row.strategy_label, row.fund_name or "") for row in result}


async def _load_etf_index_by_ticker(db: Any) -> dict[str, tuple[str, str]]:
    """Return ``{ticker: (strategy_label, fund_name)}`` — secondary bridge."""
    result = await db.execute(
        text(
            "SELECT ticker, strategy_label, fund_name FROM sec_etfs "
            "WHERE strategy_label IS NOT NULL AND ticker IS NOT NULL"
        )
    )
    out: dict[str, tuple[str, str]] = {}
    for row in result:
        # First-write-wins keeps the lookup deterministic; ETF tickers
        # are globally unique in the SEC universe.
        if row.ticker not in out:
            out[row.ticker] = (row.strategy_label, row.fund_name or "")
    return out


async def _load_bdc_index(db: Any) -> dict[str, tuple[str, str]]:
    """Return ``{series_id: (strategy_label, fund_name)}``."""
    result = await db.execute(
        text(
            "SELECT series_id, strategy_label, fund_name FROM sec_bdcs "
            "WHERE strategy_label IS NOT NULL AND series_id IS NOT NULL"
        )
    )
    return {row.series_id: (row.strategy_label, row.fund_name or "") for row in result}


async def _load_esma_index(db: Any) -> dict[str, tuple[str, str]]:
    """Return ``{isin: (strategy_label, fund_name)}``."""
    result = await db.execute(
        text(
            "SELECT isin, strategy_label, fund_name FROM esma_funds "
            "WHERE strategy_label IS NOT NULL AND isin IS NOT NULL"
        )
    )
    out: dict[str, tuple[str, str]] = {}
    for row in result:
        if row.isin not in out:
            out[row.isin] = (row.strategy_label, row.fund_name or "")
    return out


async def _load_tiingo_cascade(db: Any) -> dict[str, str]:
    """Return ``{instrument_id: proposed_strategy_label}`` for the most recent
    high-confidence ``tiingo_description`` row per instrument."""
    result = await db.execute(
        text(
            """
            SELECT DISTINCT ON (source_pk)
                   source_pk, proposed_strategy_label
            FROM strategy_reclassification_stage
            WHERE source_table = 'instruments_universe'
              AND classification_source = 'tiingo_description'
              AND confidence = 'high'
              AND proposed_strategy_label IS NOT NULL
            ORDER BY source_pk, classified_at DESC
            """
        )
    )
    return {row.source_pk: row.proposed_strategy_label for row in result}


async def _load_active_instruments(db: Any) -> list[InstrumentRow]:
    result = await db.execute(
        text(
            """
            SELECT instrument_id::text AS instrument_id,
                   ticker,
                   isin,
                   name AS fund_name,
                   attributes->>'sec_cik' AS sec_cik,
                   COALESCE(attributes->>'series_id', isin) AS series_id,
                   attributes->>'strategy_label' AS current_label
            FROM instruments_universe
            WHERE is_active = true
            """
        )
    )
    out: list[InstrumentRow] = []
    for row in result:
        cik_raw = row.sec_cik
        cik_norm = cik_raw.lstrip("0") if cik_raw else None
        # Series_id is the SEC fund-level identifier ("S00..."). We only
        # accept it when it actually looks like a series id; the isin
        # column is also reused for real ESMA ISINs (12-char alphanum).
        series = row.series_id
        if series and not series.startswith("S0"):
            series = None
        out.append(
            InstrumentRow(
                instrument_id=row.instrument_id,
                ticker=row.ticker,
                isin=row.isin,
                series_id=series,
                fund_name=row.fund_name,
                sec_cik=cik_norm,
                current_label=row.current_label,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Priority ladder
# ---------------------------------------------------------------------------


def _resolve(
    inst: InstrumentRow,
    *,
    overrides: dict[str, tuple[str, str]],
    mmf: dict[str, tuple[str, str]],
    etf_by_series: dict[str, tuple[str, str]],
    etf_by_ticker: dict[str, tuple[str, str]],
    bdc: dict[str, tuple[str, str]],
    esma: dict[str, tuple[str, str]],
    tiingo: dict[str, str],
) -> Resolution:
    # 0. Curator override — highest priority, bypasses every other source.
    if inst.ticker:
        hit = overrides.get(inst.ticker)
        if hit is not None:
            label, rationale = hit
            return Resolution(
                label=label,
                source=SOURCE_OVERRIDE,
                source_table="instrument_strategy_overrides",
                source_value=inst.ticker,
                reason=rationale or "curator override",
            )
        if _FT_VEST_BUFFER_RE.match(inst.ticker):
            return Resolution(
                label=_FT_VEST_BUFFER_LABEL,
                source=SOURCE_OVERRIDE,
                source_table="instrument_strategy_overrides",
                source_value=inst.ticker,
                reason="FT Vest U.S. Equity Buffer ETF family (SPY-buffered defined-outcome)",
            )
    # 1. MMF — bridge by series_id (CIK is issuer-level; not unique per fund)
    if inst.series_id and inst.series_id in mmf:
        cat, _ = mmf[inst.series_id]
        mapping = map_mmf_category(cat)
        if mapping.label is not None:
            return Resolution(
                label=mapping.label,
                source=SOURCE_MMF,
                source_table="sec_money_market_funds",
                source_value=cat,
                reason=mapping.reason,
            )
    # 2. ETF — series_id first, ticker as fallback
    etf_hit: tuple[str, str] | None = None
    if inst.series_id and inst.series_id in etf_by_series:
        etf_hit = etf_by_series[inst.series_id]
    elif inst.ticker and inst.ticker in etf_by_ticker:
        etf_hit = etf_by_ticker[inst.ticker]
    if etf_hit is not None:
        raw, _ = etf_hit
        mapping = map_etf_label(raw)
        if mapping.label is not None:
            return Resolution(
                label=mapping.label,
                source=SOURCE_ETF,
                source_table="sec_etfs",
                source_value=raw,
                reason=mapping.reason,
            )
    # 3. BDC — bridge by series_id
    if inst.series_id and inst.series_id in bdc:
        raw, _ = bdc[inst.series_id]
        mapping = map_bdc_label(raw)
        if mapping.label is not None:
            return Resolution(
                label=mapping.label,
                source=SOURCE_BDC,
                source_table="sec_bdcs",
                source_value=raw,
                reason=mapping.reason,
            )
    # 4. ESMA — bridge by actual ISIN (not series_id)
    if inst.isin and not inst.isin.startswith("S0") and inst.isin in esma:
        raw, _ = esma[inst.isin]
        mapping = map_esma_label(raw)
        if mapping.label is not None:
            return Resolution(
                label=mapping.label,
                source=SOURCE_ESMA,
                source_table="esma_funds",
                source_value=raw,
                reason=mapping.reason,
            )
    # 5. Tiingo cascade fallback
    if inst.instrument_id in tiingo:
        return Resolution(
            label=tiingo[inst.instrument_id],
            source=SOURCE_TIINGO,
            source_table="strategy_reclassification_stage",
            source_value=tiingo[inst.instrument_id],
            reason="tiingo_description high-confidence fallback",
        )
    # 6. NULL with needs_review flag
    return Resolution(
        label=None,
        source=SOURCE_NEEDS_REVIEW,
        source_table=None,
        source_value=None,
        reason="no authoritative source and no Tiingo cascade entry",
    )


# ---------------------------------------------------------------------------
# Apply path
# ---------------------------------------------------------------------------


_BACKUP_INSERT = text(
    """
    INSERT INTO strategy_label_authoritative_backup (
        run_id, instrument_id, ticker, fund_name,
        previous_strategy_label, new_strategy_label,
        source_table, source_value
    ) VALUES (
        :run_id, :instrument_id, :ticker, :fund_name,
        :previous, :new_label, :source_table, :source_value
    )
    """
)

_UPDATE_ATTRS = text(
    """
    UPDATE instruments_universe
    SET attributes = COALESCE(attributes, '{}'::jsonb) || jsonb_build_object(
        'strategy_label', CAST(:label AS text),
        'strategy_label_source', CAST(:source AS text),
        'strategy_label_source_table', CAST(:source_table AS text),
        'strategy_label_refreshed_at', CAST(:ts AS text),
        'needs_human_review', CAST(:needs_review AS boolean)
    )
    WHERE instrument_id::text = :instrument_id
    """
)

_RUN_INSERT = text(
    """
    INSERT INTO strategy_label_refresh_runs (
        run_id, dry_run, candidates_count,
        mmf_applied, etf_applied, bdc_applied, esma_applied,
        tiingo_fallback_count, null_flagged_count, report_json,
        completed_at
    ) VALUES (
        :run_id, :dry_run, :candidates,
        :mmf, :etf, :bdc, :esma, :tiingo, :null_flagged, CAST(:report AS jsonb),
        NOW()
    )
    """
)


async def _persist_change(
    db: Any,
    *,
    run_id: UUID,
    inst: InstrumentRow,
    resolution: Resolution,
    apply: bool,
) -> None:
    if apply:
        await db.execute(
            _BACKUP_INSERT,
            {
                "run_id": str(run_id),
                "instrument_id": inst.instrument_id,
                "ticker": inst.ticker,
                "fund_name": inst.fund_name,
                "previous": inst.current_label,
                "new_label": resolution.label,
                "source_table": resolution.source_table or "needs_review",
                "source_value": resolution.source_value or "",
            },
        )
        await db.execute(
            _UPDATE_ATTRS,
            {
                "label": resolution.label,
                "source": resolution.source,
                "source_table": resolution.source_table,
                "ts": datetime.now(timezone.utc).isoformat(),
                "needs_review": resolution.label is None,
                "instrument_id": inst.instrument_id,
            },
        )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


async def run(*, apply: bool) -> dict[str, Any]:
    run_id = uuid4()
    counters: Counter[str] = Counter()
    transitions: Counter[tuple[str | None, str | None, str]] = Counter()
    regression: dict[str, dict[str, str | None]] = {}
    sample_changes: list[dict[str, Any]] = []
    contamination_resolved: list[dict[str, Any]] = []

    async with async_session_factory() as db:
        # Single transaction: candidate scan, per-instrument writes (apply
        # only), and the run-audit row all commit together. Dry-run still
        # persists the audit row so operators have a history.
        async with db.begin():
            overrides = await _load_override_index(db)
            mmf = await _load_mmf_index(db)
            etf_by_series = await _load_etf_index_by_series(db)
            etf_by_ticker = await _load_etf_index_by_ticker(db)
            bdc = await _load_bdc_index(db)
            esma = await _load_esma_index(db)
            tiingo = await _load_tiingo_cascade(db)
            instruments = await _load_active_instruments(db)

            logger.info(
                "loaded indexes: overrides=%d mmf=%d etf_series=%d etf_ticker=%d "
                "bdc=%d esma=%d tiingo=%d active_instruments=%d",
                len(overrides),
                len(mmf),
                len(etf_by_series),
                len(etf_by_ticker),
                len(bdc),
                len(esma),
                len(tiingo),
                len(instruments),
            )

            for inst in instruments:
                resolution = _resolve(
                    inst,
                    overrides=overrides,
                    mmf=mmf,
                    etf_by_series=etf_by_series,
                    etf_by_ticker=etf_by_ticker,
                    bdc=bdc,
                    esma=esma,
                    tiingo=tiingo,
                )
                counters[resolution.source] += 1

                if inst.ticker in REGRESSION_TICKERS:
                    regression[inst.ticker] = {
                        "before": inst.current_label,
                        "after": resolution.label,
                        "source": resolution.source,
                        "source_value": resolution.source_value,
                    }

                changed = (resolution.label or "") != (inst.current_label or "")
                if not changed:
                    continue

                transitions[(inst.current_label, resolution.label, resolution.source)] += 1

                if (
                    inst.current_label in KNOWN_CONTAMINATED_LABELS
                    and resolution.label is not None
                    and resolution.label != inst.current_label
                ):
                    contamination_resolved.append(
                        {
                            "ticker": inst.ticker,
                            "fund_name": inst.fund_name,
                            "before": inst.current_label,
                            "after": resolution.label,
                            "source": resolution.source,
                        }
                    )

                if len(sample_changes) < 50:
                    sample_changes.append(
                        {
                            "ticker": inst.ticker,
                            "before": inst.current_label,
                            "after": resolution.label,
                            "source": resolution.source,
                        }
                    )

                await _persist_change(
                    db,
                    run_id=run_id,
                    inst=inst,
                    resolution=resolution,
                    apply=apply,
                )

            transitions_top_20 = [
                {
                    "before": before,
                    "after": after,
                    "source": source,
                    "count": count,
                }
                for (before, after, source), count in transitions.most_common(20)
            ]

            report = {
                "run_id": str(run_id),
                "dry_run": not apply,
                "candidates": len(instruments),
                "applied_by_source": {
                    SOURCE_OVERRIDE: counters[SOURCE_OVERRIDE],
                    SOURCE_MMF: counters[SOURCE_MMF],
                    SOURCE_ETF: counters[SOURCE_ETF],
                    SOURCE_BDC: counters[SOURCE_BDC],
                    SOURCE_ESMA: counters[SOURCE_ESMA],
                    SOURCE_TIINGO: counters[SOURCE_TIINGO],
                    SOURCE_NEEDS_REVIEW: counters[SOURCE_NEEDS_REVIEW],
                },
                "changes": sum(transitions.values()),
                "transitions_top_20": transitions_top_20,
                "regression_check": regression,
                "contamination_resolved_sample": contamination_resolved[:50],
                "contamination_resolved_count": len(contamination_resolved),
                "sample_changes": sample_changes,
            }

            await db.execute(
                _RUN_INSERT,
                {
                    "run_id": str(run_id),
                    "dry_run": not apply,
                    "candidates": len(instruments),
                    "mmf": counters[SOURCE_MMF],
                    "etf": counters[SOURCE_ETF],
                    "bdc": counters[SOURCE_BDC],
                    "esma": counters[SOURCE_ESMA],
                    "tiingo": counters[SOURCE_TIINGO],
                    "null_flagged": counters[SOURCE_NEEDS_REVIEW],
                    "report": json.dumps(report),
                },
            )

    return report


def _print_summary(report: dict[str, Any]) -> None:
    print("=" * 70)
    print(f"strategy_label refresh — run_id={report['run_id']}")
    print(f"  dry_run={report['dry_run']}  candidates={report['candidates']}")
    print("  applied_by_source:")
    for source, count in report["applied_by_source"].items():
        print(f"    {source:<20} {count}")
    print(f"  changes={report['changes']}")
    print(f"  contamination_resolved={report['contamination_resolved_count']}")
    print()
    print("Top 20 transitions:")
    for t in report["transitions_top_20"]:
        before = t["before"] or "<null>"
        after = t["after"] or "<null>"
        print(f"  [{t['count']:>5}] {before!r:30s} -> {after!r:30s} ({t['source']})")
    print()
    print("Regression check:")
    for ticker, info in sorted(report["regression_check"].items()):
        print(
            f"  {ticker:<6} before={info['before']!r:30s} "
            f"after={info['after']!r:30s} source={info['source']}"
        )
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes. Default is dry-run (no writes).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit dry-run flag (default behaviour; mutually exclusive with --apply).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full JSON report to stdout (in addition to summary).",
    )
    args = parser.parse_args()

    if args.apply and args.dry_run:
        raise SystemExit("--apply and --dry-run are mutually exclusive")

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    report = asyncio.run(run(apply=args.apply))
    _print_summary(report)
    if args.json:
        print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
