"""Enrich sec_fund_classes with OEF XBRL fees via Playwright browser downloads.

Uses browser contexts to avoid SEC 429 rate limiting.
Parallel: multiple browser pages downloading simultaneously.

Pipeline:
  1. Get pending CIKs from DB (no xbrl_accession yet)
  2. Playwright downloads submissions JSON → find N-CSR → download XBRL
  3. Parse XBRL locally with ProcessPoolExecutor (24 cores)
  4. Batch upsert to DB

Usage:
    python -m scripts.seed_fund_class_fees_playwright
    python -m scripts.seed_fund_class_fees_playwright --max-ciks 50
    python -m scripts.seed_fund_class_fees_playwright --concurrency 8
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import structlog

logger = structlog.get_logger()

DEFAULT_CONCURRENCY = 3  # parallel browser pages (conservative for SEC rate limit)
UPSERT_BATCH = 500

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

_CLASS_ID_RE = re.compile(r"(C\d{9,12})(?:Mem(?:ber)?)")


# ── XBRL Parser (CPU-bound, runs in subprocess) ─────────────────────

def _parse_xbrl_bytes(args: tuple[bytes, str, str]) -> list[tuple]:
    """Parse XBRL XML bytes, return list of upsert tuples. Runs in ProcessPool."""
    xml_bytes, accession, cik = args
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    results: dict[str, dict] = {}
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

        if local == "DocumentPeriodEndDate" and "dei" in ns:
            period_end = val
            continue

        col = None
        if "oef" in ns:
            col = _OEF_CONCEPTS.get(local)
        elif "us-gaap" in ns or "fasb" in ns:
            col = _USGAAP_CONCEPTS.get(local)
        if not col:
            continue

        ctx = elem.get("contextRef", "")
        m = _CLASS_ID_RE.search(ctx)
        if not m:
            continue
        class_id = m.group(1)

        if class_id not in results:
            results[class_id] = {}
        if col not in results[class_id]:
            results[class_id][col] = val

    rows = []
    for class_id, facts in results.items():
        holdings = facts.get("holdings_count")
        if holdings:
            try:
                holdings = str(int(float(holdings)))
            except (ValueError, TypeError):
                holdings = None

        rows.append((
            class_id,
            facts.get("expense_ratio_pct"),
            facts.get("advisory_fees_paid"),
            facts.get("expenses_paid"),
            facts.get("avg_annual_return_pct"),
            facts.get("net_assets"),
            holdings,
            facts.get("portfolio_turnover_pct"),
            facts.get("fund_name"),
            facts.get("perf_inception_date"),
            accession,
            period_end,
        ))
    return rows


# ── Browser download pipeline ────────────────────────────────────────

async def _nav_with_retry(page, url: str, max_retries: int = 3) -> object | None:
    """Navigate with 429 backoff retry."""
    for attempt in range(max_retries):
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        if resp and resp.status == 200:
            return resp
        if resp and resp.status == 429:
            wait = 30 * (attempt + 1)  # 30s, 60s, 90s
            logger.warning("rate_limited", url=url[:80], wait=wait, attempt=attempt + 1)
            await asyncio.sleep(wait)
            continue
        return None  # other error, don't retry
    return None


async def _download_cik(
    context, cik_padded: str, sem: asyncio.Semaphore,
) -> tuple[bytes | None, str | None]:
    """Download submissions + XBRL via real browser page navigation."""
    async with sem:
        page = await context.new_page()
        try:
            # Throttle: 200ms between requests within this page
            await asyncio.sleep(0.2)

            # Step 1: Navigate to submissions JSON
            sub_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
            resp = await _nav_with_retry(page, sub_url)
            if not resp:
                return None, None

            # Extract JSON from page body text
            try:
                text = await page.evaluate("() => document.body.innerText")
                sub = json.loads(text)
            except Exception:
                try:
                    text = await page.evaluate(
                        "() => document.querySelector('pre')?.textContent || document.body.textContent"
                    )
                    sub = json.loads(text)
                except Exception:
                    return None, None

            # Step 2: Find latest N-CSR
            recent = sub.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            accs = recent.get("accessionNumber", [])
            primary = recent.get("primaryDocument", [])

            xbrl_url = None
            accession = None
            for i, form_type in enumerate(forms):
                if form_type in ("N-CSR", "N-CSRS", "N-CSR/A", "N-CSRS/A"):
                    accession = accs[i]
                    acc_nodash = accession.replace("-", "")
                    cik_raw = cik_padded.lstrip("0")
                    doc = primary[i] if i < len(primary) else None
                    if doc and doc.endswith(".htm"):
                        xml_doc = doc.replace(".htm", "_htm.xml")
                        xbrl_url = f"https://www.sec.gov/Archives/edgar/data/{cik_raw}/{acc_nodash}/{xml_doc}"
                    break

            if not xbrl_url:
                return None, None

            await asyncio.sleep(0.2)

            # Step 3: Navigate to XBRL file
            resp2 = await _nav_with_retry(page, xbrl_url)
            if not resp2:
                return None, None

            body = await resp2.body()
            return body, accession

        except Exception:
            return None, None
        finally:
            await page.close()


async def _run(dsn: str, max_ciks: int | None, concurrency: int) -> None:
    import asyncpg
    from playwright.async_api import async_playwright

    # Get pending CIKs
    conn = await asyncpg.connect(dsn, ssl="require")
    rows = await conn.fetch("""
        SELECT DISTINCT cik FROM sec_fund_classes
        WHERE xbrl_accession IS NULL
        ORDER BY cik
    """)
    pending_ciks = [r["cik"].zfill(10) for r in rows]
    await conn.close()

    if max_ciks:
        pending_ciks = pending_ciks[:max_ciks]

    logger.info("starting", pending_ciks=len(pending_ciks), concurrency=concurrency)
    t0 = time.time()

    # Launch browser
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            extra_http_headers={"Accept-Encoding": "gzip, deflate, br"},
        )

        sem = asyncio.Semaphore(concurrency)
        all_xbrl: list[tuple[bytes, str, str]] = []  # (xml_bytes, accession, cik)
        downloaded = 0
        missed = 0

        # Download in chunks
        chunk_size = concurrency * 4
        for i in range(0, len(pending_ciks), chunk_size):
            chunk = pending_ciks[i:i + chunk_size]
            tasks = [_download_cik(context, cik, sem) for cik in chunk]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for j, r in enumerate(results):
                if isinstance(r, Exception) or r is None or r == (None, None):
                    missed += 1
                else:
                    body, acc = r
                    if body and acc:
                        all_xbrl.append((body, acc, chunk[j]))
                        downloaded += 1
                    else:
                        missed += 1

            elapsed = time.time() - t0
            logger.info("download_progress",
                        downloaded=downloaded, missed=missed,
                        total=len(pending_ciks),
                        processed=i + len(chunk),
                        elapsed=f"{elapsed:.0f}s",
                        rate=f"{(i + len(chunk)) / elapsed:.0f} CIKs/s" if elapsed > 0 else "")

        await browser.close()

    logger.info("download_complete",
                downloaded=downloaded, missed=missed,
                elapsed=f"{time.time()-t0:.0f}s")

    if not all_xbrl:
        logger.warning("no_xbrl_to_parse")
        return

    # Parse XBRL in parallel (CPU-bound, use all cores)
    t1 = time.time()
    num_workers = min(os.cpu_count() or 4, 20)
    all_rows: list[tuple] = []

    with ProcessPoolExecutor(max_workers=num_workers) as pool:
        parse_results = list(pool.map(_parse_xbrl_bytes, all_xbrl, chunksize=10))

    for rows in parse_results:
        all_rows.extend(rows)

    logger.info("parse_complete",
                xbrl_files=len(all_xbrl),
                class_rows=len(all_rows),
                elapsed=f"{time.time()-t1:.1f}s")

    # Batch upsert
    t2 = time.time()
    conn = await asyncpg.connect(dsn, ssl="require")

    upsert_sql = """
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

    for i in range(0, len(all_rows), UPSERT_BATCH):
        batch = all_rows[i:i + UPSERT_BATCH]
        await conn.executemany(upsert_sql, batch)

    # Validation
    stats = await conn.fetch("""
        SELECT count(*) total,
               count(expense_ratio_pct) has_expense,
               count(avg_annual_return_pct) has_return,
               count(net_assets) has_assets,
               count(xbrl_accession) has_xbrl
        FROM sec_fund_classes
    """)
    r = stats[0]
    logger.info("upsert_complete",
                total=r["total"], has_expense=r["has_expense"],
                has_return=r["has_return"], has_assets=r["has_assets"],
                has_xbrl=r["has_xbrl"],
                elapsed=f"{time.time()-t2:.1f}s",
                total_elapsed=f"{time.time()-t0:.0f}s")

    # Top expense ratios sanity check
    sample = await conn.fetch("""
        SELECT class_id, ticker, fund_name, expense_ratio_pct,
               round((net_assets / 1e9)::numeric, 1) assets_bn
        FROM sec_fund_classes
        WHERE expense_ratio_pct IS NOT NULL
        ORDER BY net_assets DESC NULLS LAST LIMIT 10
    """)
    for s in sample:
        logger.info("sample",
                     class_id=s["class_id"], ticker=s["ticker"],
                     fund=s["fund_name"][:40] if s["fund_name"] else None,
                     expense=float(s["expense_ratio_pct"]) if s["expense_ratio_pct"] else None,
                     assets_bn=float(s["assets_bn"]) if s["assets_bn"] else None)

    await conn.close()


def _resolve_dsn(dsn: str | None) -> str:
    if dsn:
        return dsn
    raw = os.environ.get("DATABASE_URL", "")
    if raw.startswith("postgresql+asyncpg://"):
        return raw.replace("postgresql+asyncpg://", "postgresql://", 1)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich sec_fund_classes via Playwright + XBRL")
    parser.add_argument("--dsn", type=str, help="Direct PostgreSQL DSN")
    parser.add_argument("--max-ciks", type=int, help="Limit CIKs (for testing)")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                        help=f"Parallel browser pages (default {DEFAULT_CONCURRENCY})")
    args = parser.parse_args()

    dsn = _resolve_dsn(args.dsn)
    if not dsn:
        raise ValueError("No DSN provided and DATABASE_URL not set")

    asyncio.run(_run(dsn, max_ciks=args.max_ciks, concurrency=args.concurrency))


if __name__ == "__main__":
    main()
