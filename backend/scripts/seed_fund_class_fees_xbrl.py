"""Enrich sec_fund_classes with OEF XBRL fee data from N-CSR filings.

Pipeline:
  1. Fetch all unique CIKs from sec_fund_classes
  2. For each CIK, GET submissions JSON to find latest N-CSR/N-CSRS
  3. GET filing index to find XBRL instance document
  4. Parse XBRL, extract OEF facts per class_id (C000xxxxx)
  5. Batch upsert to sec_fund_classes

SEC rate limit: 10 req/s via asyncio.Semaphore.

Usage:
    python -m scripts.seed_fund_class_fees_xbrl
    python -m scripts.seed_fund_class_fees_xbrl --dsn "postgresql://..."
    python -m scripts.seed_fund_class_fees_xbrl --max-ciks 50  # test with subset
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from io import BytesIO

import structlog

logger = structlog.get_logger()

SEC_RATE_LIMIT = 10  # requests per second
USER_AGENT = "Netz/1.0 (andrei@investintell.com)"
UPSERT_BATCH = 500

# OEF concepts we extract (namespace suffix -> local name -> our column)
_OEF_CONCEPTS = {
    "ExpenseRatioPct": "expense_ratio_pct",
    "AdvisoryFeesPaidAmt": "advisory_fees_paid",
    "ExpensesPaidAmt": "expenses_paid",
    "AvgAnnlRtrPct": "avg_annual_return_pct",
    "HoldingsCount": "holdings_count",
    "FundName": "fund_name",
    "PerfInceptionDate": "perf_inception_date",
}

_USGAAP_CONCEPTS = {
    "AssetsNet": "net_assets",
    "InvestmentCompanyPortfolioTurnover": "portfolio_turnover_pct",
}

# Regex to extract class_id from XBRL contextRef
# Patterns: "..._C000007825Mem", "..._C000007825Member", "..._C000007825Mem_..."
_CLASS_ID_RE = re.compile(r"(C\d{9,12})(?:Mem(?:ber)?)")


@dataclass
class ClassFacts:
    class_id: str
    expense_ratio_pct: str | None = None
    advisory_fees_paid: str | None = None
    expenses_paid: str | None = None
    avg_annual_return_pct: str | None = None
    net_assets: str | None = None
    holdings_count: str | None = None
    portfolio_turnover_pct: str | None = None
    fund_name: str | None = None
    perf_inception_date: str | None = None


# ── HTTP Layer (rate-limited) ────────────────────────────────────────

async def _fetch(session, url: str, sem: asyncio.Semaphore) -> bytes | None:
    async with sem:
        try:
            async with session.get(url, headers={"User-Agent": USER_AGENT}, timeout=30) as resp:
                if resp.status == 200:
                    return await resp.read()
                if resp.status == 404:
                    return None
                logger.warning("http_error", url=url, status=resp.status)
                return None
        except Exception as e:
            logger.warning("http_exception", url=url, error=str(e)[:80])
            return None
        finally:
            await asyncio.sleep(1.0 / SEC_RATE_LIMIT)  # rate limit


# ── Step 1: Find latest N-CSR filing ─────────────────────────────────

async def _find_ncsr_xbrl_url(
    session, cik_padded: str, sem: asyncio.Semaphore,
) -> tuple[str | None, str | None]:
    """Returns (xbrl_url, accession_number) or (None, None)."""
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    data = await _fetch(session, url, sem)
    if not data:
        return None, None

    import json
    try:
        sub = json.loads(data)
    except json.JSONDecodeError:
        return None, None

    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accs = recent.get("accessionNumber", [])
    primary = recent.get("primaryDocument", [])

    # Find latest N-CSR or N-CSRS
    for i, form in enumerate(forms):
        if form in ("N-CSR", "N-CSRS", "N-CSR/A", "N-CSRS/A"):
            acc = accs[i]
            acc_nodash = acc.replace("-", "")
            doc = primary[i] if i < len(primary) else None

            # Primary document is usually the HTML/XBRL
            if doc and doc.endswith(".htm"):
                xml_doc = doc.replace(".htm", "_htm.xml")
                xbrl_url = f"https://www.sec.gov/Archives/edgar/data/{cik_padded.lstrip('0')}/{acc_nodash}/{xml_doc}"
                return xbrl_url, acc

            # Fallback: try common pattern
            xbrl_url = f"https://www.sec.gov/Archives/edgar/data/{cik_padded.lstrip('0')}/{acc_nodash}/"
            return xbrl_url, acc

    return None, None


async def _find_xbrl_in_index(
    session, index_url: str, sem: asyncio.Semaphore,
) -> str | None:
    """If we got a directory URL, find the _htm.xml file in the index."""
    data = await _fetch(session, index_url, sem)
    if not data:
        return None
    html = data.decode("utf-8", errors="replace")
    # Find _htm.xml or _ncsr_htm.xml
    matches = re.findall(r'href="([^"]*_htm\.xml)"', html, re.I)
    if matches:
        return index_url + matches[0]
    # Try any .xml that looks like XBRL instance
    matches = re.findall(r'href="([^"]*ncsr[^"]*\.xml)"', html, re.I)
    if matches:
        return index_url + matches[0]
    return None


# ── Step 2: Parse XBRL ───────────────────────────────────────────────

def _parse_xbrl(xml_bytes: bytes, accession: str) -> dict[str, ClassFacts]:
    """Parse XBRL instance, return {class_id: ClassFacts}."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return {}

    results: dict[str, ClassFacts] = {}
    period_end: str | None = None

    for elem in root.iter():
        tag = elem.tag
        if "{" not in tag:
            continue
        ns, local = tag.split("}", 1)
        ns = ns.lstrip("{")
        val = (elem.text or "").strip()
        if not val:
            continue

        # Extract period end date
        if local == "DocumentPeriodEndDate" and "dei" in ns:
            period_end = val
            continue

        # Map concept to column name
        col = None
        if "oef" in ns:
            col = _OEF_CONCEPTS.get(local)
        elif "us-gaap" in ns or "fasb" in ns:
            col = _USGAAP_CONCEPTS.get(local)

        if not col:
            continue

        # Extract class_id from contextRef
        ctx = elem.get("contextRef", "")
        m = _CLASS_ID_RE.search(ctx)
        if not m:
            continue
        class_id = m.group(1)

        if class_id not in results:
            results[class_id] = ClassFacts(class_id=class_id)

        # Set the value (keep first non-None for each concept per class)
        cf = results[class_id]
        if getattr(cf, col) is None:
            setattr(cf, col, val)

    # Attach period_end to all
    for cf in results.values():
        cf.__dict__["_period_end"] = period_end
        cf.__dict__["_accession"] = accession

    return results


# ── Step 3: Process single CIK ───────────────────────────────────────

async def _process_cik(
    session, cik_padded: str, sem: asyncio.Semaphore,
) -> list[tuple]:
    """Fetch + parse one CIK, return list of upsert tuples."""
    xbrl_url, accession = await _find_ncsr_xbrl_url(session, cik_padded, sem)
    if not xbrl_url or not accession:
        return []

    # If URL is a directory, find the XBRL file
    if xbrl_url.endswith("/"):
        xbrl_url = await _find_xbrl_in_index(session, xbrl_url, sem)
        if not xbrl_url:
            return []

    xml_bytes = await _fetch(session, xbrl_url, sem)
    if not xml_bytes:
        return []

    class_facts = _parse_xbrl(xml_bytes, accession)
    if not class_facts:
        return []

    rows = []
    for cf in class_facts.values():
        # Convert types for asyncpg (XBRL values are all strings)
        holdings = None
        if cf.holdings_count is not None:
            try:
                holdings = int(float(cf.holdings_count))
            except (ValueError, TypeError):
                pass

        rows.append((
            cf.class_id,               # $1 str
            cf.expense_ratio_pct,       # $2 str->numeric
            cf.advisory_fees_paid,      # $3 str->numeric
            cf.expenses_paid,           # $4 str->numeric
            cf.avg_annual_return_pct,   # $5 str->numeric
            cf.net_assets,              # $6 str->numeric
            str(holdings) if holdings is not None else None,  # $7 str->int
            cf.portfolio_turnover_pct,  # $8 str->numeric
            cf.fund_name,               # $9 str
            cf.perf_inception_date,     # $10 str->date
            cf.__dict__.get("_accession"),   # $11 str
            cf.__dict__.get("_period_end"),  # $12 str->date
        ))

    return rows


# ── Step 4: DB Upsert ────────────────────────────────────────────────

_UPSERT_SQL = """
UPDATE sec_fund_classes SET
    expense_ratio_pct = COALESCE($2::text::numeric, expense_ratio_pct),
    advisory_fees_paid = COALESCE($3::text::numeric, advisory_fees_paid),
    expenses_paid = COALESCE($4::text::numeric, expenses_paid),
    avg_annual_return_pct = COALESCE($5::text::numeric, avg_annual_return_pct),
    net_assets = COALESCE($6::text::numeric, net_assets),
    holdings_count = COALESCE($7::text::int, holdings_count),
    portfolio_turnover_pct = COALESCE($8::text::numeric, portfolio_turnover_pct),
    fund_name = COALESCE($9, fund_name),
    perf_inception_date = COALESCE($10::text::date, perf_inception_date),
    xbrl_accession = COALESCE($11, xbrl_accession),
    xbrl_period_end = COALESCE($12::text::date, xbrl_period_end)
WHERE class_id = $1
"""


# ── Main pipeline ────────────────────────────────────────────────────

async def _run(dsn: str, max_ciks: int | None = None) -> None:
    import aiohttp
    import asyncpg

    # Get unique CIKs from DB
    conn = await asyncpg.connect(dsn, ssl="require")
    db_ciks = await conn.fetch("SELECT DISTINCT cik FROM sec_fund_classes")
    cik_list = sorted({r["cik"] for r in db_ciks})
    await conn.close()

    if max_ciks:
        cik_list = cik_list[:max_ciks]

    # Zero-pad CIKs to 10 digits
    padded = [c.zfill(10) for c in cik_list]
    logger.info("starting", ciks=len(padded))

    sem = asyncio.Semaphore(SEC_RATE_LIMIT)
    all_rows: list[tuple] = []
    processed = 0
    errors = 0

    async with aiohttp.ClientSession() as session:
        # Process in chunks to avoid memory pressure
        chunk_size = 100
        for i in range(0, len(padded), chunk_size):
            chunk = padded[i:i + chunk_size]
            tasks = [_process_cik(session, cik, sem) for cik in chunk]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for r in results:
                if isinstance(r, Exception):
                    errors += 1
                elif r:
                    all_rows.extend(r)
                processed += 1

            logger.info("progress",
                        processed=processed, total=len(padded),
                        rows_so_far=len(all_rows), errors=errors)

    logger.info("fetch_complete", total_rows=len(all_rows), errors=errors)

    if not all_rows:
        logger.warning("no_rows_to_upsert")
        return

    # Batch upsert
    t0 = time.time()
    conn = await asyncpg.connect(dsn, ssl="require")

    for i in range(0, len(all_rows), UPSERT_BATCH):
        batch = all_rows[i:i + UPSERT_BATCH]
        await conn.executemany(_UPSERT_SQL, batch)

    # Validation
    stats = await conn.fetch("""
        SELECT count(*) total,
               count(expense_ratio_pct) has_expense,
               count(avg_annual_return_pct) has_return,
               count(net_assets) has_assets,
               count(fund_name) has_name
        FROM sec_fund_classes
    """)
    r = stats[0]
    logger.info("upsert_complete",
                total=r["total"], has_expense=r["has_expense"],
                has_return=r["has_return"], has_assets=r["has_assets"],
                elapsed=f"{time.time()-t0:.1f}s")

    await conn.close()


# ── Entrypoint ───────────────────────────────────────────────────────

def _resolve_dsn(dsn: str | None) -> str:
    if dsn:
        return dsn
    raw = os.environ.get("DATABASE_URL", "")
    if raw.startswith("postgresql+asyncpg://"):
        return raw.replace("postgresql+asyncpg://", "postgresql://", 1)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich sec_fund_classes from N-CSR XBRL")
    parser.add_argument("--dsn", type=str, help="Direct PostgreSQL DSN")
    parser.add_argument("--max-ciks", type=int, help="Limit CIKs to process (for testing)")
    args = parser.parse_args()

    dsn = _resolve_dsn(args.dsn)
    if not dsn:
        raise ValueError("No DSN provided and DATABASE_URL not set")

    asyncio.run(_run(dsn, max_ciks=args.max_ciks))


if __name__ == "__main__":
    main()
