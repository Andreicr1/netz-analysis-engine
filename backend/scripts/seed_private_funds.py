"""Seed sec_manager_funds from IAPD Form ADV Part 1 PDFs.

Downloads Form ADV PDFs for managers with private funds, parses
Section 7.B.(1) to extract individual fund details, and upserts
into sec_manager_funds via direct DB connection.

Fund type detection uses **checkbox image analysis**: SEC Form ADV PDFs
render Q10 checkboxes as small JPEG images (17×21 px). The checked
checkbox uses a different image xref than the unchecked ones. We detect
the minority xref among the 6–7 checkbox images to identify the selected
fund type. Fallback: ``sec_managers`` fund-type counters.

Usage (local seed):
    python -m scripts.seed_private_funds --download --parse --upsert
    python -m scripts.seed_private_funds --parse --upsert   # skip download if PDFs exist
    python -m scripts.seed_private_funds --upsert            # re-upsert from existing JSON

Requires: DATABASE_URL env var (direct, not pooler).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
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
_FOF_RE = re.compile(
    r'Is this private fund a .fund of funds.\?\s*\n',
    re.IGNORECASE,
)

# ── Q10 fund type: checkbox image detection ──────────────────────
#
# SEC Form ADV PDFs render Q10 as 6–7 small JPEG images (17×21 px)
# next to text labels. Checked vs unchecked use different image xrefs.
# We detect the minority xref (= checked) and map by X-position to labels.

_Q10_LABEL_KEYWORDS: list[tuple[str, str]] = [
    ("hedge fund", "Hedge Fund"),
    ("liquidity fund", "Liquidity Fund"),
    ("private equity fund", "Private Equity Fund"),
    ("real estate fund", "Real Estate Fund"),
    ("securitized asset fund", "Securitized Asset Fund"),
    ("venture capital fund", "Venture Capital Fund"),
]


def _detect_fund_types_on_page(page) -> list[tuple[str, float]]:  # noqa: ANN001
    """Detect checked fund types on a PDF page via checkbox image xrefs.

    Returns list of (fund_type_label, checkbox_x) for checked boxes.
    Empty list if detection fails.
    """
    # 1. Find Q10 label positions by matching span text
    blocks = page.get_text("dict")
    labels: list[tuple[str, float, float]] = []  # (label, x, y)
    for block in blocks.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                t = span["text"].strip().lower()
                bbox = span["bbox"]
                for kw, lbl in _Q10_LABEL_KEYWORDS:
                    if t == kw:
                        labels.append((lbl, bbox[0], bbox[1]))
                        break
                # "Other private fund:" — text starts with "other"
                if labels and t.startswith("other") and abs(bbox[1] - labels[0][2]) < 2:
                    labels.append(("Other Private Fund", bbox[0], bbox[1]))

    if len(labels) < 5:
        return []

    q10_y = labels[0][2]

    # 2. Find small images (checkboxes) aligned with Q10 labels
    checkboxes: list[tuple[float, int]] = []  # (x, xref)
    for img in page.get_image_info(xrefs=True):
        if img["width"] <= 20 and img["height"] <= 25:
            img_y = img["bbox"][1]
            if abs(img_y - q10_y + 8) < 15:
                checkboxes.append((img["bbox"][0], img["xref"]))

    if len(checkboxes) < 6:
        return []

    # 3. Majority xref = unchecked, minority = checked
    xref_counts = Counter(xr for _, xr in checkboxes)
    if len(xref_counts) < 2:
        return []  # all same — can't distinguish

    unchecked_xref = xref_counts.most_common(1)[0][0]
    checked = [(x, xr) for x, xr in checkboxes if xr != unchecked_xref]

    results = []
    for cx, _ in checked:
        nearest = min(labels, key=lambda t: abs(t[1] - cx - 15))
        results.append((nearest[0], cx))

    return results


def _build_page_fund_type_map(doc) -> dict[int, str]:  # noqa: ANN001
    """Build page_number → fund_type map for all Q10 sections in the PDF.

    Each fund in Section 7.B.(1) occupies ~1 page. We scan every page
    that contains "What type of fund" and detect the checked checkbox.
    Returns {page_index: fund_type_label}.
    """
    page_types: dict[int, str] = {}

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        if "what type of fund" not in text.lower():
            continue

        detected = _detect_fund_types_on_page(page)
        if detected:
            # Usually one checked box per Q10; take the first
            page_types[page_num] = detected[0][0]

    return page_types


def _parse_section_7b(
    text: str,
    page_fund_types: dict[int, str] | None = None,
) -> list[dict]:
    """Parse all private funds from Section 7.B.(1) text.

    ``page_fund_types`` maps page indices to detected fund types from
    checkbox image analysis.  Fund sections are matched to pages by
    order (fund 0 → first Q10 page, fund 1 → second Q10 page, etc.).
    """
    funds: list[dict] = []

    # Build ordered list of fund types from page map
    ordered_types: list[str] = []
    if page_fund_types:
        ordered_types = [
            page_fund_types[p] for p in sorted(page_fund_types)
        ]

    # Split on "A. PRIVATE FUND" markers — each is a new fund
    sections = re.split(r"A\.\s*PRIVATE FUND\b", text)

    for idx, section in enumerate(sections[1:]):  # skip text before first fund
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

        # Fund type (Q10) — from checkbox image detection
        if idx < len(ordered_types):
            fund["fund_type"] = ordered_types[idx]

        # Fund of funds (Q8)
        m = _FOF_RE.search(section)
        if m:
            after = section[m.end():m.end() + 200].strip()
            fund["is_fund_of_funds"] = "yes" in after[:50].lower() and "no" not in after[:10].lower()

        if fund.get("fund_name"):
            funds.append(fund)

    return funds


def parse_pdfs() -> int:
    """Parse all downloaded PDFs and write JSONL.

    Uses checkbox image analysis for fund type detection (Q10).
    """
    import fitz  # pymupdf

    PARSED_FILE.parent.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(PDF_DIR.glob("*.pdf"))
    total = len(pdf_files)
    fund_count = 0
    manager_count = 0
    img_detect_ok = 0
    img_detect_fail = 0

    with open(PARSED_FILE, "w", encoding="utf-8") as out:
        for i, pdf_path in enumerate(pdf_files):
            crd = pdf_path.stem

            try:
                doc = fitz.open(str(pdf_path))
            except Exception as e:
                logger.warning("pdf_parse_error", crd=crd, error=str(e))
                continue

            try:
                full_text = "\n".join(
                    page.get_text("text") for page in doc
                )

                # Check if this adviser has private funds
                if "SECTION 7.B.(1)" not in full_text:
                    continue

                # Detect fund types via checkbox images (before closing doc)
                page_fund_types = _build_page_fund_type_map(doc)
                if page_fund_types:
                    img_detect_ok += 1
                else:
                    img_detect_fail += 1

                # Extract only the Section 7.B.(1) portion
                start = full_text.index("SECTION 7.B.(1)")
                end = len(full_text)
                for marker in ["SECTION 7.B.(2)", "Item 8 ", "SCHEDULE A", "Schedule A"]:
                    idx = full_text.find(marker, start + 100)
                    if idx != -1 and idx < end:
                        end = idx

                section_text = full_text[start:end]
                funds = _parse_section_7b(section_text, page_fund_types)

                if funds:
                    manager_count += 1
                    for f in funds:
                        f["crd_number"] = crd
                        out.write(json.dumps(f, ensure_ascii=False) + "\n")
                        fund_count += 1
            finally:
                doc.close()

            if (i + 1) % 500 == 0:
                logger.info(
                    "parse_progress",
                    progress=f"{i + 1}/{total}",
                    managers=manager_count,
                    funds=fund_count,
                    img_ok=img_detect_ok,
                    img_fail=img_detect_fail,
                )

    logger.info(
        "parse_complete",
        total_pdfs=total,
        managers_with_funds=manager_count,
        total_funds=fund_count,
        img_detect_ok=img_detect_ok,
        img_detect_fail=img_detect_fail,
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
