"""PR-A26.3.3 Section D — populate ``sec_etfs.strategy_label`` for the
~439 rows that SEC bulk ingestion left NULL.

For each such row we look up the matching ``instruments_universe`` entry
by ``series_id`` first, ``ticker`` second, and read
``attributes->>'tiingo_description'``. The description is fed to the
existing cascade classifier
(:func:`app.domains.wealth.services.strategy_classifier.classify_fund`)
which produces a label through name regex when description is missing.

Writes:

* ``sec_etfs.strategy_label = <classifier_output>``
* ``sec_etfs.strategy_label_source`` =
  - ``'tiingo_cascade'`` when classifier produced a label;
  - ``'unclassified'`` when cascade fell back (caller may try brochure).

After this script runs, ``refresh_authoritative_labels.py --apply`` will
promote the new ``sec_etfs`` labels into
``instruments_universe.attributes`` — that is what fixes the 382-row
alt_real_estate / alt_gold contamination gap.

Default mode is dry-run. Re-running is a no-op (only touches NULL rows).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections import Counter
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from app.core.db.engine import async_session_factory
from app.domains.wealth.services.strategy_classifier import classify_fund

logger = logging.getLogger("backfill_sec_etfs_strategy_label")


@dataclass(frozen=True)
class EtfRow:
    series_id: str
    ticker: str | None
    fund_name: str
    tiingo_description: str | None


async def _load_etfs_missing_label(db: Any) -> list[EtfRow]:
    """Join sec_etfs (NULL strategy_label) ↔ instruments_universe by
    series_id OR ticker to recover the tiingo_description when present."""
    result = await db.execute(
        text(
            """
            SELECT etf.series_id,
                   etf.ticker,
                   etf.fund_name,
                   iu.attributes->>'tiingo_description' AS tiingo_description
            FROM sec_etfs AS etf
            LEFT JOIN instruments_universe AS iu
              ON (iu.attributes->>'series_id' = etf.series_id)
              OR (etf.ticker IS NOT NULL AND iu.ticker = etf.ticker)
            WHERE etf.strategy_label IS NULL
            """
        )
    )
    rows: dict[str, EtfRow] = {}
    for row in result:
        # One etf may join multiple iu rows; first-write-wins keeps the
        # cascade input deterministic. All iu rows with matching ticker
        # share the same description in practice.
        if row.series_id in rows:
            existing = rows[row.series_id]
            if existing.tiingo_description or not row.tiingo_description:
                continue
        rows[row.series_id] = EtfRow(
            series_id=row.series_id,
            ticker=row.ticker,
            fund_name=row.fund_name,
            tiingo_description=row.tiingo_description,
        )
    return list(rows.values())


_UPDATE_SQL = text(
    """
    UPDATE sec_etfs
    SET strategy_label = :label,
        strategy_label_source = :source,
        updated_at = NOW()
    WHERE series_id = :series_id
    """
)


def _classify(row: EtfRow) -> tuple[str | None, str]:
    """Return ``(label, source)`` where source is one of
    ``'tiingo_cascade'`` / ``'unclassified'``.
    """
    result = classify_fund(
        fund_name=row.fund_name or "",
        fund_type=None,
        tiingo_description=row.tiingo_description,
        holdings_analysis=None,
    )
    if result.strategy_label is None:
        return None, "unclassified"
    return result.strategy_label, "tiingo_cascade"


async def run(*, apply: bool) -> dict[str, Any]:
    counters: Counter[str] = Counter()
    labels: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []

    async with async_session_factory() as db:
        async with db.begin():
            etfs = await _load_etfs_missing_label(db)
            logger.info("loaded etfs_missing_label=%d", len(etfs))

            for row in etfs:
                label, source = _classify(row)
                counters[source] += 1
                if label is not None:
                    labels[label] += 1
                if len(samples) < 10:
                    samples.append(
                        {
                            "series_id": row.series_id,
                            "ticker": row.ticker,
                            "fund_name": row.fund_name,
                            "label": label,
                            "source": source,
                            "had_description": row.tiingo_description is not None,
                        }
                    )
                if apply:
                    await db.execute(
                        _UPDATE_SQL,
                        {
                            "label": label,
                            "source": source,
                            "series_id": row.series_id,
                        },
                    )

            if not apply:
                await db.rollback()

    report = {
        "dry_run": not apply,
        "candidates_scanned": sum(counters.values()),
        "populated": counters["tiingo_cascade"],
        "unclassified": counters["unclassified"],
        "top_20_labels": [
            {"label": label, "count": count}
            for label, count in labels.most_common(20)
        ],
        "samples": samples,
    }
    return report


def _print_summary(report: dict[str, Any]) -> None:
    print("=" * 70)
    print(f"backfill_sec_etfs_strategy_label  dry_run={report['dry_run']}")
    print(f"  candidates_scanned={report['candidates_scanned']}")
    print(f"  populated={report['populated']}  "
          f"unclassified={report['unclassified']}")
    print()
    print("Top 20 new labels:")
    for entry in report["top_20_labels"]:
        print(f"  [{entry['count']:>5}] {entry['label']}")
    print()
    print("Samples:")
    for s in report["samples"]:
        print(f"  {s['series_id']} {s['ticker'] or '-':<8} "
              f"label={s['label']!r:30s} source={s['source']}  "
              f"had_desc={s['had_description']}")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes.")
    parser.add_argument("--dry-run", action="store_true", help="Explicit dry-run.")
    parser.add_argument("--json", action="store_true",
                        help="Emit the full JSON report.")
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
