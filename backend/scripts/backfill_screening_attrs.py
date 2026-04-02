"""Backfill L1 screening attributes into existing instruments_universe rows.

Populates domicile, structure, aum_usd, and track_record_years from SEC tables
for all fund instruments that are missing these attributes.

Usage:
    python -m scripts.backfill_screening_attrs          # dry-run (default)
    python -m scripts.backfill_screening_attrs --apply  # commit changes

Requires DATABASE_URL env var.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings as app_settings

_UNIVERSE_TO_STRUCTURE = {
    "registered_us": "Mutual Fund",
    "etf": "ETF",
    "bdc": "BDC",
    "money_market": "Money Market",
}


def backfill(*, apply: bool = False) -> None:
    db_url = app_settings.database_url_sync
    engine = create_engine(db_url)

    with Session(engine) as db:
        rows = db.execute(text("""
            SELECT i.instrument_id, i.ticker, i.name, i.attributes
            FROM instruments_universe i
            WHERE i.instrument_type = 'fund'
              AND i.ticker IS NOT NULL
        """)).mappings().all()

        print(f"Found {len(rows)} fund instruments to check")

        updated = 0
        for row in rows:
            ticker = row["ticker"]
            attrs = row["attributes"] if isinstance(row["attributes"], dict) else json.loads(row["attributes"])
            patches: dict[str, object] = {}

            # Always set domicile=US for SEC source
            if not attrs.get("domicile"):
                patches["domicile"] = "US"

            # Resolve structure from sec_universe
            if not attrs.get("structure"):
                universe = attrs.get("sec_universe")
                structure = _UNIVERSE_TO_STRUCTURE.get(str(universe)) if universe else None
                if structure:
                    patches["structure"] = structure

            # Resolve AUM from SEC tables
            if attrs.get("aum_usd") is None:
                aum = _resolve_aum(db, ticker, attrs.get("sec_universe"), attrs.get("sec_cik"))
                if aum is not None:
                    patches["aum_usd"] = aum

            # Resolve track_record_years from inception dates
            if attrs.get("track_record_years") is None:
                track = _resolve_track_record(db, ticker, attrs)
                if track is not None:
                    patches["track_record_years"] = track

            if not patches:
                continue

            new_attrs = {**attrs, **patches}
            if apply:
                db.execute(
                    text("""
                        UPDATE instruments_universe
                        SET attributes = CAST(:attrs AS jsonb)
                        WHERE instrument_id = :iid
                    """),
                    {"attrs": json.dumps(new_attrs, default=str), "iid": row["instrument_id"]},
                )

            print(f"  {'UPDATED' if apply else 'WOULD UPDATE'} {ticker} ({row['name']}): {patches}")
            updated += 1

        if apply:
            db.commit()

        print(f"\n{'Applied' if apply else 'Dry-run'}: {updated}/{len(rows)} instruments {'updated' if apply else 'would be updated'}")


def _resolve_aum(db: Session, ticker: str, universe: str | None, cik: str | None) -> float | None:
    # 1. sec_registered_funds (monthly_avg_net_assets or daily_avg_net_assets)
    if cik:
        row = db.execute(text("""
            SELECT monthly_avg_net_assets, daily_avg_net_assets
            FROM sec_registered_funds WHERE cik = :cik
        """), {"cik": cik}).mappings().first()
        if row:
            if row["monthly_avg_net_assets"] is not None:
                return float(row["monthly_avg_net_assets"])
            if row["daily_avg_net_assets"] is not None:
                return float(row["daily_avg_net_assets"])

    # 2. sec_etfs
    if universe == "etf":
        row = db.execute(text("""
            SELECT monthly_avg_net_assets, daily_avg_net_assets
            FROM sec_etfs WHERE ticker = :ticker LIMIT 1
        """), {"ticker": ticker}).mappings().first()
        if row:
            if row["monthly_avg_net_assets"] is not None:
                return float(row["monthly_avg_net_assets"])
            if row["daily_avg_net_assets"] is not None:
                return float(row["daily_avg_net_assets"])

    # 3. sec_bdcs
    if universe == "bdc":
        row = db.execute(text("""
            SELECT monthly_avg_net_assets, daily_avg_net_assets
            FROM sec_bdcs WHERE ticker = :ticker LIMIT 1
        """), {"ticker": ticker}).mappings().first()
        if row:
            if row["monthly_avg_net_assets"] is not None:
                return float(row["monthly_avg_net_assets"])
            if row["daily_avg_net_assets"] is not None:
                return float(row["daily_avg_net_assets"])

    # 4. Fallback: XBRL net_assets from sec_fund_classes
    row = db.execute(text("""
        SELECT net_assets FROM sec_fund_classes
        WHERE ticker = :ticker AND net_assets IS NOT NULL
        LIMIT 1
    """), {"ticker": ticker}).mappings().first()
    if row and row["net_assets"] is not None:
        return float(row["net_assets"])

    return None


def _resolve_track_record(db: Session, ticker: str, attrs: dict) -> float | None:
    today = dt.date.today()

    # 1. fund_inception_date already in enrichment attrs
    inception_str = attrs.get("fund_inception_date")
    if inception_str:
        try:
            inception = dt.date.fromisoformat(str(inception_str))
            return round((today - inception).days / 365.25, 1)
        except (ValueError, TypeError):
            pass

    # 2. sec_registered_funds.inception_date via CIK
    cik = attrs.get("sec_cik")
    if cik:
        row = db.execute(text("""
            SELECT inception_date FROM sec_registered_funds
            WHERE cik = :cik AND inception_date IS NOT NULL
        """), {"cik": cik}).mappings().first()
        if row and row["inception_date"]:
            return round((today - row["inception_date"]).days / 365.25, 1)

    # 3. sec_fund_classes.perf_inception_date via ticker
    row = db.execute(text("""
        SELECT perf_inception_date FROM sec_fund_classes
        WHERE ticker = :ticker AND perf_inception_date IS NOT NULL
        LIMIT 1
    """), {"ticker": ticker}).mappings().first()
    if row and row["perf_inception_date"]:
        return round((today - row["perf_inception_date"]).days / 365.25, 1)

    # 4. sec_etfs.inception_date via ticker
    row = db.execute(text("""
        SELECT inception_date FROM sec_etfs
        WHERE ticker = :ticker AND inception_date IS NOT NULL
        LIMIT 1
    """), {"ticker": ticker}).mappings().first()
    if row and row["inception_date"]:
        return round((today - row["inception_date"]).days / 365.25, 1)

    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill L1 screening attributes")
    parser.add_argument("--apply", action="store_true", help="Commit changes (default: dry-run)")
    args = parser.parse_args()
    backfill(apply=args.apply)
