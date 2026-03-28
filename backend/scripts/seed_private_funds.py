"""Seed sec_manager_funds from IAPD Form ADV Part 1 PDFs.

Downloads Form ADV PDFs for managers with private funds, parses
Section 7.B.(1) to extract individual fund details, and upserts
into sec_manager_funds via direct DB connection.

Usage (local seed):
    python -m scripts.seed_private_funds --download --parse --upsert
    python -m scripts.seed_private_funds --parse --upsert   # skip download if PDFs exist
    python -m scripts.seed_private_funds --upsert            # re-upsert from existing JSON

Requires: DATABASE_URL env var (direct, not pooler).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import structlog

logger = structlog.get_logger()

# ── Config ──────────────────────────────────────────────────────

IAPD_RATE_LIMIT = 1.0  # seconds between requests
ADV_PDF_URL = "https://reports.adviserinfo.sec.gov/reports/ADV/{crd}/PDF/{crd}.pdf"
IAPD_HOME = "https://adviserinfo.sec.gov/"
CONCURRENT_DOWNLOADS = 4  # parallel browser tabs

DATA_DIR = Path(__file__).resolve().parent.parent.parent / ".data" / "adv_part1"
PDF_DIR = DATA_DIR / "pdfs"
PARSED_FILE = DATA_DIR / "parsed_funds.jsonl"

# ── Phase 1: Download ──────────────────────────────────────────


def _get_target_crds() -> list[str]:
    """Get CRDs of managers with private funds from DB."""
    import asyncio

    async def _fetch() -> list[str]:
        from sqlalchemy import text as sa_text

        from app.core.db.engine import async_session_factory

        async with async_session_factory() as db:
            result = await db.execute(sa_text("""
                SELECT crd_number FROM sec_managers
                WHERE registration_status = 'Registered'
                  AND firm_name IS NOT NULL
                  AND (private_fund_count > 0
                       OR hedge_fund_count > 0
                       OR pe_fund_count > 0
                       OR vc_fund_count > 0
                       OR real_estate_fund_count > 0)
                ORDER BY crd_number
            """))
            return [r[0] for r in result.fetchall()]

    return asyncio.run(_fetch())


def download_pdfs(crds: list[str]) -> dict:
    """Download Form ADV Part 1 PDFs from IAPD via Playwright.

    Uses a real browser context to bypass WAF/Cloudflare protection.
    Downloads PDFs in batches using the browser's API context (shares cookies).
    """
    from playwright.sync_api import sync_playwright

    PDF_DIR.mkdir(parents=True, exist_ok=True)

    # Filter already-downloaded
    pending = []
    skipped = 0
    for crd in crds:
        pdf_path = PDF_DIR / f"{crd}.pdf"
        if pdf_path.exists() and pdf_path.stat().st_size > 1024:
            skipped += 1
        else:
            pending.append(crd)

    stats = {"ok": 0, "skipped": skipped, "not_found": 0, "error": 0}
    total = len(crds)

    if not pending:
        logger.info("all_pdfs_already_downloaded", skipped=skipped)
        return stats

    logger.info("download_pending", pending=len(pending), skipped=skipped, total=total)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        # Establish IAPD session (cookies)
        page = context.new_page()
        page.goto(IAPD_HOME, wait_until="domcontentloaded", timeout=30000)
        logger.info("iapd_session_established", cookies=len(context.cookies()))
        page.close()

        for i, crd in enumerate(pending):
            pdf_path = PDF_DIR / f"{crd}.pdf"
            url = ADV_PDF_URL.format(crd=crd)
            status = "error"

            for attempt in range(3):
                try:
                    resp = context.request.get(url, timeout=60000)
                    if resp.status == 404:
                        status = "not_found"
                        break
                    if resp.status == 403:
                        wait = 2 ** attempt * 2
                        logger.warning("iapd_403_backoff", crd=crd, wait=wait)
                        time.sleep(wait)
                        continue
                    if resp.status == 200 and len(resp.body()) > 1024:
                        pdf_path.write_bytes(resp.body())
                        status = "ok"
                        break
                    status = "not_found"
                    break
                except Exception as e:
                    logger.warning("download_error", crd=crd, error=str(e))
                    if attempt < 2:
                        time.sleep(2)
                        continue
                    status = "error"
                    break

            stats[status] += 1

            # Rate limit
            time.sleep(IAPD_RATE_LIMIT)

            if (i + 1) % 50 == 0:
                logger.info(
                    "download_progress",
                    progress=f"{i + 1}/{len(pending)}",
                    crd=crd,
                    **stats,
                )

        browser.close()

    return stats


# ── Phase 2: Parse ─────────────────────────────────────────────

# Regex patterns for Section 7.B.(1) fields
_FUND_NAME_RE = re.compile(
    r"Name of the private fund:\s*\n\s*(.+?)(?:\n|$)", re.IGNORECASE,
)
_FUND_ID_RE = re.compile(
    r"(?:Private fund identification number|include the .805-. prefix).*?\n\s*(805-\d+)",
    re.IGNORECASE,
)
_GAV_RE = re.compile(
    r"Current gross asset value.*?:\s*\n?\s*\$?\s*([\d,]+)", re.IGNORECASE,
)
_INVESTOR_RE = re.compile(
    r"Approximate number of.*?beneficial owners:\s*\n?\s*(\d+)", re.IGNORECASE,
)
_FUND_TYPE_RE = re.compile(
    r"What type of fund.*?\n(.*?)(?:\n\s*NOTE|\n\s*11\.)", re.IGNORECASE | re.DOTALL,
)
_FOF_RE = re.compile(
    r'Is this private fund a .fund of funds.\?\s*\n',
    re.IGNORECASE,
)

# Fund type keywords to detect from the checkbox section
_FUND_TYPE_KEYWORDS = [
    ("hedge fund", "Hedge Fund"),
    ("private equity fund", "Private Equity Fund"),
    ("venture capital fund", "Venture Capital Fund"),
    ("real estate fund", "Real Estate Fund"),
    ("liquidity fund", "Liquidity Fund"),
    ("securitized asset fund", "Securitized Asset Fund"),
    ("other private fund", "Other Private Fund"),
]


def _extract_fund_type(text_block: str) -> str | None:
    """Extract fund type from the Q10 checkbox section."""
    lower = text_block.lower()
    for keyword, label in _FUND_TYPE_KEYWORDS:
        if keyword in lower:
            return label
    return None


def _parse_section_7b(text: str) -> list[dict]:
    """Parse all private funds from Section 7.B.(1) text."""
    funds: list[dict] = []

    # Split on "A. PRIVATE FUND" markers — each is a new fund
    sections = re.split(r"A\.\s*PRIVATE FUND\b", text)

    for section in sections[1:]:  # skip text before first fund
        fund: dict = {}

        # Fund name (Q1a)
        m = _FUND_NAME_RE.search(section)
        if m:
            fund["fund_name"] = m.group(1).strip()
        else:
            continue  # skip if no name

        # Fund ID (Q1b)
        m = _FUND_ID_RE.search(section)
        if m:
            fund["fund_id"] = m.group(1).strip()

        # Gross asset value (Q11)
        m = _GAV_RE.search(section)
        if m:
            try:
                fund["gross_asset_value"] = int(m.group(1).replace(",", ""))
            except ValueError:
                pass

        # Investor count (Q13)
        m = _INVESTOR_RE.search(section)
        if m:
            try:
                fund["investor_count"] = int(m.group(1))
            except ValueError:
                pass

        # Fund type (Q10)
        m = _FUND_TYPE_RE.search(section)
        if m:
            fund["fund_type"] = _extract_fund_type(m.group(1))

        # Fund of funds (Q8)
        m = _FOF_RE.search(section)
        if m:
            # Look for Yes/No after the question — heuristic
            after = section[m.end():m.end() + 200].strip()
            # In the PDF text, checked boxes often appear as text
            # "Yes No" with only one highlighted, but in text extraction
            # we often just see both. Use NOTE context.
            fund["is_fund_of_funds"] = "yes" in after[:50].lower() and "no" not in after[:10].lower()

        if fund.get("fund_name"):
            funds.append(fund)

    return funds


def parse_pdfs() -> int:
    """Parse all downloaded PDFs and write JSONL."""
    import fitz  # pymupdf

    PARSED_FILE.parent.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(PDF_DIR.glob("*.pdf"))
    total = len(pdf_files)
    fund_count = 0
    manager_count = 0

    with open(PARSED_FILE, "w", encoding="utf-8") as out:
        for i, pdf_path in enumerate(pdf_files):
            crd = pdf_path.stem

            try:
                doc = fitz.open(str(pdf_path))
                full_text = "\n".join(
                    page.get_text("text") for page in doc
                )
                doc.close()
            except Exception as e:
                logger.warning("pdf_parse_error", crd=crd, error=str(e))
                continue

            # Check if this adviser has private funds
            if "SECTION 7.B.(1)" not in full_text:
                continue

            # Extract only the Section 7.B.(1) portion
            start = full_text.index("SECTION 7.B.(1)")
            # Section ends at Section 7.B.(2) or Item 8 or SCHEDULE A
            end = len(full_text)
            for marker in ["SECTION 7.B.(2)", "Item 8 ", "SCHEDULE A", "Schedule A"]:
                idx = full_text.find(marker, start + 100)
                if idx != -1 and idx < end:
                    end = idx

            section_text = full_text[start:end]
            funds = _parse_section_7b(section_text)

            if funds:
                manager_count += 1
                for f in funds:
                    f["crd_number"] = crd
                    out.write(json.dumps(f, ensure_ascii=False) + "\n")
                    fund_count += 1

            if (i + 1) % 500 == 0:
                logger.info(
                    "parse_progress",
                    progress=f"{i + 1}/{total}",
                    managers=manager_count,
                    funds=fund_count,
                )

    logger.info(
        "parse_complete",
        total_pdfs=total,
        managers_with_funds=manager_count,
        total_funds=fund_count,
    )
    return fund_count


# ── Phase 3: Upsert ───────────────────────────────────────────


def upsert_funds() -> int:
    """Upsert parsed funds into sec_manager_funds via asyncpg."""
    import asyncio

    if not PARSED_FILE.exists():
        logger.error("parsed_file_not_found", path=str(PARSED_FILE))
        return 0

    funds: list[dict] = []
    with open(PARSED_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                funds.append(json.loads(line))

    if not funds:
        logger.warning("no_funds_to_upsert")
        return 0

    async def _do_upsert() -> int:
        from sqlalchemy import text as sa_text

        from app.core.db.engine import async_session_factory

        upsert_sql = sa_text("""
            INSERT INTO sec_manager_funds
                (id, crd_number, fund_name, fund_id, gross_asset_value,
                 fund_type, is_fund_of_funds, investor_count, data_fetched_at)
            VALUES
                (gen_random_uuid(), :crd_number, :fund_name, :fund_id,
                 :gross_asset_value, :fund_type, :is_fund_of_funds,
                 :investor_count, NOW())
            ON CONFLICT ON CONSTRAINT uq_sec_manager_funds_crd_name
            DO UPDATE SET
                fund_id = COALESCE(EXCLUDED.fund_id, sec_manager_funds.fund_id),
                gross_asset_value = COALESCE(EXCLUDED.gross_asset_value, sec_manager_funds.gross_asset_value),
                fund_type = COALESCE(EXCLUDED.fund_type, sec_manager_funds.fund_type),
                is_fund_of_funds = COALESCE(EXCLUDED.is_fund_of_funds, sec_manager_funds.is_fund_of_funds),
                investor_count = COALESCE(EXCLUDED.investor_count, sec_manager_funds.investor_count),
                data_fetched_at = NOW()
        """)

        chunk_size = 500
        upserted = 0

        for i in range(0, len(funds), chunk_size):
            chunk = funds[i : i + chunk_size]
            async with async_session_factory() as db, db.begin():
                for fund in chunk:
                    await db.execute(upsert_sql, {
                        "crd_number": fund["crd_number"],
                        "fund_name": fund["fund_name"],
                        "fund_id": fund.get("fund_id"),
                        "gross_asset_value": fund.get("gross_asset_value"),
                        "fund_type": fund.get("fund_type"),
                        "is_fund_of_funds": fund.get("is_fund_of_funds"),
                        "investor_count": fund.get("investor_count"),
                    })
                upserted += len(chunk)
            logger.info("upsert_chunk", progress=f"{upserted}/{len(funds)}")

        return upserted

    return asyncio.run(_do_upsert())


# ── CLI ────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed sec_manager_funds from IAPD PDFs")
    parser.add_argument("--download", action="store_true", help="Phase 1: download PDFs")
    parser.add_argument("--parse", action="store_true", help="Phase 2: parse Section 7.B")
    parser.add_argument("--upsert", action="store_true", help="Phase 3: upsert to DB")
    parser.add_argument("--pdf-dir", type=str, help="Override PDF directory")
    args = parser.parse_args()

    if args.pdf_dir:
        global PDF_DIR
        PDF_DIR = Path(args.pdf_dir)

    if not any([args.download, args.parse, args.upsert]):
        parser.print_help()
        sys.exit(1)

    if args.download:
        logger.info("phase_1_download_start")
        crds = _get_target_crds()
        logger.info("target_managers", count=len(crds))
        stats = download_pdfs(crds)
        logger.info("phase_1_complete", **stats)

    if args.parse:
        logger.info("phase_2_parse_start")
        count = parse_pdfs()
        logger.info("phase_2_complete", funds_parsed=count)

    if args.upsert:
        logger.info("phase_3_upsert_start")
        count = upsert_funds()
        logger.info("phase_3_complete", funds_upserted=count)


if __name__ == "__main__":
    main()
