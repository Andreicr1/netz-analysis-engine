"""Form 345 insider transaction ingestion worker.

Usage (standalone):
    python -m app.domains.wealth.workers.form345_ingestion

Ingests Form 3/4/5 insider transactions from SEC EDGAR bulk quarterly
TSV files and refreshes the sec_insider_sentiment materialized view.

GLOBAL TABLE: No organization_id, no RLS.
Advisory lock ID = 900_051.
Frequency: Quarterly.
"""

from __future__ import annotations

import asyncio
import csv
import io
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import structlog
from sqlalchemy import text

from app.core.db.engine import async_session_factory as async_session

logger = structlog.get_logger()
FORM345_LOCK_ID = 900_051
_BATCH_SIZE = 1000

# SEC EDGAR bulk data base URL
_EDGAR_BULK_BASE = "https://www.sec.gov/files/structureddata/data/form-345"


def _parse_decimal(val: str) -> Decimal | None:
    if not val or val.strip() == "":
        return None
    try:
        return Decimal(val.strip())
    except InvalidOperation:
        return None


def _parse_date_345(val: str) -> date | None:
    if not val or val.strip() == "":
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(val.strip(), fmt).date()
        except ValueError:
            continue
    return None


async def run_form345_ingestion() -> dict:
    """Ingest Form 345 insider transactions.

    Downloads latest quarter's Form 345 bulk data from SEC EDGAR,
    parses TSV files, and upserts into sec_insider_transactions.
    Then refreshes sec_insider_sentiment materialized view.
    """
    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({FORM345_LOCK_ID})"),
        )
        if not lock_result.scalar():
            logger.warning("form345_ingestion: lock not acquired, skipping")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            result = await _ingest_form345(db)

            await db.execute(
                text("REFRESH MATERIALIZED VIEW CONCURRENTLY sec_insider_sentiment"),
            )
            await db.commit()
            logger.info("sec_insider_sentiment_refreshed")

            return result

        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({FORM345_LOCK_ID})"),
            )


async def _ingest_form345(db) -> dict:
    """Download and ingest the latest quarter's Form 345 data."""
    import httpx

    now = datetime.utcnow()
    year = now.year
    quarter = (now.month - 1) // 3 + 1

    # Try current quarter, fall back to previous
    for y, q in [(year, quarter), (year if quarter > 1 else year - 1, quarter - 1 if quarter > 1 else 4)]:
        url = f"{_EDGAR_BULK_BASE}/{y}q{q}_form345.zip"
        logger.info("form345_downloading", url=url)

        try:
            async with httpx.AsyncClient(
                timeout=120.0,
                headers={"User-Agent": "NetzAnalysisEngine/1.0 (admin@investintell.com)"},
            ) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return await _process_zip(db, resp.content, f"{y}q{q}")
                logger.warning("form345_download_failed", status=resp.status_code, url=url)
        except Exception:
            logger.exception("form345_download_error", url=url)

    return {"status": "error", "reason": "no_data_available"}


async def _process_zip(db, zip_bytes: bytes, quarter_label: str) -> dict:
    """Process downloaded ZIP containing TSV files."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        logger.info("form345_zip_contents", files=names)

        # Load SUBMISSION
        sub_name = next((n for n in names if "SUBMISSION" in n.upper()), None)
        owner_name = next((n for n in names if "REPORTINGOWNER" in n.upper()), None)
        trans_name = next((n for n in names if "NONDERIV_TRANS" in n.upper()), None)

        if not all([sub_name, owner_name, trans_name]):
            return {"status": "error", "reason": "missing_tsv_files", "files": names}

        submissions = _parse_submissions(zf.read(sub_name).decode("utf-8", errors="replace"))
        owners = _parse_owners(zf.read(owner_name).decode("utf-8", errors="replace"))
        transactions = _parse_transactions(
            zf.read(trans_name).decode("utf-8", errors="replace"),
            submissions,
            owners,
        )

    if not transactions:
        return {"status": "no_transactions", "quarter": quarter_label}

    # Upsert
    total = 0
    for i in range(0, len(transactions), _BATCH_SIZE):
        batch = transactions[i : i + _BATCH_SIZE]
        await _upsert_batch(db, batch)
        total += len(batch)
        if (i // _BATCH_SIZE) % 10 == 0:
            await db.flush()

    await db.commit()
    logger.info("form345_upsert_complete", total=total, quarter=quarter_label)

    return {"status": "ok", "quarter": quarter_label, "rows_upserted": total}


def _parse_submissions(content: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    reader = csv.DictReader(io.StringIO(content), delimiter="\t")
    for row in reader:
        acc = row.get("ACCESSION_NUMBER", "").strip()
        if not acc:
            continue
        result[acc] = {
            "issuer_cik": row.get("ISSUERCIK", "").strip(),
            "issuer_ticker": row.get("ISSUERTRADINGSYMBOL", "").strip() or None,
            "document_type": row.get("DOCUMENT_TYPE", "").strip()[:1] or None,
            "period_of_report": _parse_date_345(row.get("PERIOD_OF_REPORT", "")),
        }
    return result


def _parse_owners(content: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    reader = csv.DictReader(io.StringIO(content), delimiter="\t")
    priority_map = {"Officer": 3, "Director": 2, "10% Owner": 1}
    for row in reader:
        acc = row.get("ACCESSION_NUMBER", "").strip()
        if not acc:
            continue
        rel = row.get("RPTOWNER_RELATIONSHIP", "").strip()
        priority = priority_map.get(rel, 0)
        existing = result.get(acc)
        if existing and priority_map.get(existing["owner_relationship"], 0) >= priority:
            continue
        result[acc] = {
            "owner_cik": row.get("RPTOWNERCIK", "").strip(),
            "owner_name": row.get("RPTOWNERNAME", "").strip() or None,
            "owner_relationship": rel or None,
            "owner_title": row.get("RPTOWNER_TITLE", "").strip() or None,
        }
    return result


def _parse_transactions(
    content: str,
    submissions: dict[str, dict],
    owners: dict[str, dict],
) -> list[dict]:
    rows: list[dict] = []
    reader = csv.DictReader(io.StringIO(content), delimiter="\t")
    for row in reader:
        acc = row.get("ACCESSION_NUMBER", "").strip()
        sub = submissions.get(acc)
        if not sub:
            continue
        trans_code = row.get("TRANS_CODE", "").strip()
        if not trans_code:
            continue
        trans_date = _parse_date_345(row.get("TRANS_DATE", ""))
        if not trans_date:
            continue
        trans_sk_raw = row.get("NONDERIV_TRANS_SK", "").strip()
        if not trans_sk_raw:
            continue
        try:
            trans_sk = int(trans_sk_raw)
        except ValueError:
            continue

        owner = owners.get(acc, {})
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
            "trans_shares": _parse_decimal(row.get("TRANS_SHARES", "")),
            "trans_price_per_share": _parse_decimal(row.get("TRANS_PRICEPERSHARE", "")),
            "shares_owned_after": _parse_decimal(row.get("SHRS_OWND_FOLWNG_TRANS", "")),
        })
    return rows


async def _upsert_batch(db, batch: list[dict]) -> None:
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
    await db.execute(text(sql), params)


if __name__ == "__main__":
    asyncio.run(run_form345_ingestion())
