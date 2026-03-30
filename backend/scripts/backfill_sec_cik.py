"""Backfill sec_cik and sec_universe into instruments_universe attributes.

Matches existing fund-type instruments against sec_registered_funds by ticker,
then updates the JSONB attributes with sec_cik and sec_universe fields.

Usage:
    python -m scripts.backfill_sec_cik          # dry-run (default)
    python -m scripts.backfill_sec_cik --apply  # commit changes

Requires DATABASE_URL env var.
"""

from __future__ import annotations

import argparse

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings


def backfill(*, apply: bool = False) -> None:
    settings = get_settings()
    # Use sync driver for scripts
    db_url = str(settings.DATABASE_URL).replace("+asyncpg", "+psycopg2")
    engine = create_engine(db_url)

    with Session(engine) as db:
        # Find fund instruments with a ticker but no sec_cik in attributes
        rows = db.execute(text("""
            SELECT i.instrument_id, i.ticker, i.name, i.attributes
            FROM instruments_universe i
            WHERE i.instrument_type = 'fund'
              AND i.ticker IS NOT NULL
              AND (i.attributes->>'sec_cik') IS NULL
        """)).mappings().all()

        print(f"Found {len(rows)} fund instruments without sec_cik")

        updated = 0
        for row in rows:
            ticker = row["ticker"]
            # Match against sec_registered_funds by ticker
            reg = db.execute(text("""
                SELECT srf.cik, srf.crd_number
                FROM sec_registered_funds srf
                WHERE srf.ticker = :ticker
                LIMIT 1
            """), {"ticker": ticker}).mappings().first()

            if not reg:
                continue

            cik = reg["cik"]
            attrs = dict(row["attributes"] or {})
            attrs["sec_cik"] = cik
            attrs["sec_universe"] = "registered_us"

            if apply:
                db.execute(text("""
                    UPDATE instruments_universe
                    SET attributes = attributes || :patch,
                        updated_at = NOW()
                    WHERE instrument_id = :iid
                """), {
                    "patch": f'{{"sec_cik": "{cik}", "sec_universe": "registered_us"}}',
                    "iid": str(row["instrument_id"]),
                })

            updated += 1
            print(f"  {'UPDATED' if apply else 'WOULD UPDATE'}: {row['name']} ({ticker}) → CIK {cik}")

        if apply:
            db.commit()

        print(f"\n{'Applied' if apply else 'Dry-run'}: {updated}/{len(rows)} instruments matched")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill sec_cik into instruments_universe")
    parser.add_argument("--apply", action="store_true", help="Actually apply changes (default: dry-run)")
    args = parser.parse_args()
    backfill(apply=args.apply)
