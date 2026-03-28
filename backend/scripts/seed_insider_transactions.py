"""Seed Form 345 insider transactions from EDGAR bulk TSV files.

Usage:
    python seed_insider_transactions.py --form345-dir "C:/Users/Andrei/Desktop/EDGAR FILES/2025q4_form345"
    python seed_insider_transactions.py --form345-dir "..." --dry-run

Reads SUBMISSION.tsv, REPORTINGOWNER.tsv, NONDERIV_TRANS.tsv and upserts
into sec_insider_transactions. Then refreshes sec_insider_sentiment
materialized view.

Global table — no organization_id, no RLS.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import structlog

logger = structlog.get_logger()

_BATCH_SIZE = 1000

RELATIONSHIP_PRIORITY = {
    "Officer": 3,
    "Director": 2,
    "10% Owner": 1,
}


def parse_decimal(val: str) -> Decimal | None:
    if not val or val.strip() == "":
        return None
    try:
        return Decimal(val.strip())
    except InvalidOperation:
        return None


def parse_date_345(val: str) -> date | None:
    """Parse Form 345 dates (DD-MON-YYYY or YYYY-MM-DD)."""
    if not val or val.strip() == "":
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(val.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _load_submissions(form345_dir: Path) -> dict[str, dict]:
    """Load SUBMISSION.tsv → dict[accession → {issuer_cik, issuer_ticker, ...}]."""
    path = form345_dir / "SUBMISSION.tsv"
    result: dict[str, dict] = {}
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            acc = row["ACCESSION_NUMBER"]
            result[acc] = {
                "issuer_cik": row.get("ISSUERCIK", "").strip(),
                "issuer_ticker": row.get("ISSUERTRADINGSYMBOL", "").strip() or None,
                "document_type": row.get("DOCUMENT_TYPE", "").strip()[:1] or None,
                "period_of_report": parse_date_345(row.get("PERIOD_OF_REPORT", "")),
            }
    logger.info("submissions_loaded", count=len(result))
    return result


def _load_owners(form345_dir: Path) -> dict[str, dict]:
    """Load REPORTINGOWNER.tsv → dict[accession → best owner]."""
    path = form345_dir / "REPORTINGOWNER.tsv"
    result: dict[str, dict] = {}
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            acc = row["ACCESSION_NUMBER"]
            relationship = row.get("RPTOWNER_RELATIONSHIP", "").strip()
            priority = RELATIONSHIP_PRIORITY.get(relationship, 0)

            existing = result.get(acc)
            if existing and RELATIONSHIP_PRIORITY.get(existing["owner_relationship"], 0) >= priority:
                continue

            result[acc] = {
                "owner_cik": row.get("RPTOWNERCIK", "").strip(),
                "owner_name": row.get("RPTOWNERNAME", "").strip() or None,
                "owner_relationship": relationship or None,
                "owner_title": row.get("RPTOWNER_TITLE", "").strip() or None,
            }
    logger.info("owners_loaded", count=len(result))
    return result


def _iter_transactions(
    form345_dir: Path,
    submissions: dict[str, dict],
    owners: dict[str, dict],
) -> list[dict]:
    """Iterate NONDERIV_TRANS.tsv and join with submissions + owners."""
    path = form345_dir / "NONDERIV_TRANS.tsv"
    rows: list[dict] = []
    skipped = 0

    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            acc = row["ACCESSION_NUMBER"]
            sub = submissions.get(acc)
            if not sub:
                skipped += 1
                continue

            owner = owners.get(acc, {})
            trans_code = row.get("TRANS_CODE", "").strip()
            if not trans_code:
                skipped += 1
                continue

            trans_date = parse_date_345(row.get("TRANS_DATE", ""))
            if not trans_date:
                skipped += 1
                continue

            trans_sk_raw = row.get("NONDERIV_TRANS_SK", "").strip()
            if not trans_sk_raw:
                skipped += 1
                continue

            try:
                trans_sk = int(trans_sk_raw)
            except ValueError:
                skipped += 1
                continue

            rows.append({
                "accession_number": acc,
                "trans_sk": trans_sk,
                "issuer_cik": sub["issuer_cik"],
                "issuer_ticker": sub["issuer_ticker"],
                "owner_cik": owner.get("owner_cik", ""),
                "owner_name": owner.get("owner_name"),
                "owner_relationship": owner.get("owner_relationship"),
                "owner_title": owner.get("owner_title"),
                "trans_date": trans_date,
                "period_of_report": sub["period_of_report"],
                "document_type": sub["document_type"],
                "trans_code": trans_code,
                "trans_acquired_disp": row.get("TRANS_ACQUIRED_DISP_CD", "").strip()[:1] or None,
                "trans_shares": parse_decimal(row.get("TRANS_SHARES", "")),
                "trans_price_per_share": parse_decimal(row.get("TRANS_PRICEPERSHARE", "")),
                "shares_owned_after": parse_decimal(row.get("SHRS_OWND_FOLWNG_TRANS", "")),
            })

    logger.info("transactions_parsed", count=len(rows), skipped=skipped)
    return rows


async def _upsert_batch(db, batch: list[dict]) -> int:
    """Upsert a batch of rows into sec_insider_transactions."""
    from sqlalchemy import text as sa_text

    # Build VALUES clause — exclude trans_value (GENERATED ALWAYS)
    cols = [
        "accession_number", "trans_sk", "issuer_cik", "issuer_ticker",
        "owner_cik", "owner_name", "owner_relationship", "owner_title",
        "trans_date", "period_of_report", "document_type", "trans_code",
        "trans_acquired_disp", "trans_shares", "trans_price_per_share",
        "shares_owned_after",
    ]

    placeholders = []
    params: dict = {}
    for i, row in enumerate(batch):
        parts = []
        for col in cols:
            key = f"{col}_{i}"
            params[key] = row[col]
            parts.append(f":{key}")
        placeholders.append(f"({', '.join(parts)})")

    sql = f"""
        INSERT INTO sec_insider_transactions ({', '.join(cols)})
        VALUES {', '.join(placeholders)}
        ON CONFLICT (accession_number, trans_sk) DO UPDATE SET
            issuer_ticker = EXCLUDED.issuer_ticker,
            owner_name = EXCLUDED.owner_name,
            owner_relationship = EXCLUDED.owner_relationship,
            owner_title = EXCLUDED.owner_title,
            trans_shares = EXCLUDED.trans_shares,
            trans_price_per_share = EXCLUDED.trans_price_per_share,
            shares_owned_after = EXCLUDED.shares_owned_after
    """

    await db.execute(sa_text(sql), params)
    return len(batch)


async def seed(form345_dir: str, dry_run: bool = False) -> dict:
    """Main seed entry point."""
    dir_path = Path(form345_dir)
    if not dir_path.exists():
        logger.error("form345_dir_not_found", path=str(dir_path))
        return {"error": f"Directory not found: {dir_path}"}

    submissions = _load_submissions(dir_path)
    owners = _load_owners(dir_path)
    transactions = _iter_transactions(dir_path, submissions, owners)

    if not transactions:
        logger.warning("no_transactions_parsed")
        return {"rows_parsed": 0}

    # Count by trans_code
    code_counts: dict[str, int] = {}
    for t in transactions:
        code = t["trans_code"]
        code_counts[code] = code_counts.get(code, 0) + 1
    logger.info("trans_code_distribution", counts=code_counts)

    if dry_run:
        logger.info("dry_run_complete", total=len(transactions), codes=code_counts)
        return {"dry_run": True, "rows_parsed": len(transactions), "codes": code_counts}

    # Upsert in batches
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.core.db.engine import async_session_factory

    total_upserted = 0
    async with async_session_factory() as db:
        for i in range(0, len(transactions), _BATCH_SIZE):
            batch = transactions[i : i + _BATCH_SIZE]
            n = await _upsert_batch(db, batch)
            total_upserted += n
            if (i // _BATCH_SIZE) % 10 == 0:
                logger.info("upsert_progress", upserted=total_upserted, total=len(transactions))

        await db.commit()
        logger.info("upsert_complete", total=total_upserted)

        # Refresh materialized view
        from sqlalchemy import text as sa_text

        await db.execute(sa_text("REFRESH MATERIALIZED VIEW CONCURRENTLY sec_insider_sentiment"))
        await db.commit()
        logger.info("materialized_view_refreshed", view="sec_insider_sentiment")

    return {
        "rows_parsed": len(transactions),
        "rows_upserted": total_upserted,
        "codes": code_counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Form 345 insider transactions")
    parser.add_argument(
        "--form345-dir",
        required=True,
        help="Path to directory containing SUBMISSION.tsv, REPORTINGOWNER.tsv, NONDERIV_TRANS.tsv",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no DB writes")
    args = parser.parse_args()

    result = asyncio.run(seed(args.form345_dir, dry_run=args.dry_run))
    print(result)


if __name__ == "__main__":
    main()
