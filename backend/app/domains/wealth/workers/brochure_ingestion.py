"""ADV brochure ingestion worker — two-phase download + extract.

Phase A (download): Fetch PDFs from IAPD at 1 req/s → StorageClient.
Phase B (extract):  Read PDFs from StorageClient → PyMuPDF text → DB upsert.

Splitting avoids re-downloading on extract failures and lets the extract
phase run at full CPU speed with zero network rate-limiting.

Advisory lock IDs: 900_019 (download), 900_020 (extract).
Scope: global.  Frequency: weekly (download), on-demand (extract).
"""

import asyncio

import structlog
from sqlalchemy import text as sa_text

from app.core.db.engine import async_session_factory as async_session
from app.services.storage_client import get_storage_client

logger = structlog.get_logger()

BROCHURE_DOWNLOAD_LOCK_ID = 900_019
BROCHURE_EXTRACT_LOCK_ID = 900_020

_STORAGE_PREFIX = "gold/_global/sec_brochures"
_ADV_PDF_URL = "https://reports.adviserinfo.sec.gov/reports/ADV/{crd}/R_0{crd}.pdf"


def _storage_path(crd: str) -> str:
    """Storage key for a brochure PDF."""
    return f"{_STORAGE_PREFIX}/{crd}.pdf"


async def run_brochure_download() -> dict:
    """Phase A: Download ADV Part 2A PDFs from IAPD → StorageClient.

    Rate-limited at 1 req/s (IAPD).  Skips CRDs already in storage.
    Returns summary dict with status and counts.
    """
    storage = get_storage_client()

    async with async_session() as db:
        lock = await db.execute(
            sa_text(f"SELECT pg_try_advisory_lock({BROCHURE_DOWNLOAD_LOCK_ID})"),
        )
        if not lock.scalar():
            logger.warning("brochure_download.lock_held")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            result = await db.execute(
                sa_text(
                    "SELECT crd_number FROM sec_managers "
                    "WHERE private_fund_count > 0 "
                    "   OR hedge_fund_count > 0 "
                    "   OR pe_fund_count > 0 "
                    "   OR vc_fund_count > 0 "
                    "   OR real_estate_fund_count > 0 "
                    "ORDER BY crd_number",
                ),
            )
            all_crds = [row[0] for row in result.fetchall()]

            if not all_crds:
                return {"status": "completed", "downloaded": 0, "skipped": 0}

            # Filter out already-stored PDFs
            pending: list[str] = []
            for crd in all_crds:
                if not await storage.exists(_storage_path(crd)):
                    pending.append(crd)

            skipped = len(all_crds) - len(pending)

            if not pending:
                logger.info("brochure_download.all_present", total=len(all_crds))
                return {"status": "completed", "downloaded": 0, "skipped": skipped}

            logger.info(
                "brochure_download.starting",
                pending=len(pending),
                skipped=skipped,
            )

            stats = {"downloaded": 0, "not_found": 0, "errors": 0}

            from data_providers.sec.shared import (
                SEC_USER_AGENT,
                check_iapd_rate,
                run_in_sec_thread,
            )

            def _download_one(crd: str) -> tuple[str, bytes | None]:
                """Sync download — runs in thread pool."""
                import time as _time

                import httpx

                pdf_url = _ADV_PDF_URL.format(crd=crd)
                for attempt in range(4):
                    check_iapd_rate()
                    try:
                        resp = httpx.get(
                            pdf_url,
                            headers={"User-Agent": SEC_USER_AGENT},
                            timeout=60.0,
                            follow_redirects=True,
                        )
                        if resp.status_code == 404:
                            return "not_found", None
                        if resp.status_code == 403:
                            _time.sleep(2 ** attempt * 2)
                            continue
                        resp.raise_for_status()
                        if len(resp.content) < 1024:
                            return "not_found", None
                        return "ok", resp.content
                    except Exception:
                        return "error", None
                return "max_retries", None

            for i, crd in enumerate(pending):
                status_code, pdf_bytes = await run_in_sec_thread(
                    _download_one, crd,
                )

                if status_code == "ok" and pdf_bytes:
                    await storage.write(
                        _storage_path(crd),
                        pdf_bytes,
                        content_type="application/pdf",
                    )
                    stats["downloaded"] += 1
                elif status_code == "not_found":
                    # Write empty marker so we skip next time
                    await storage.write(
                        _storage_path(crd), b"", content_type="application/pdf",
                    )
                    stats["not_found"] += 1
                else:
                    stats["errors"] += 1

                if (i + 1) % 100 == 0:
                    logger.info(
                        "brochure_download.progress",
                        progress=i + 1,
                        total=len(pending),
                        **stats,
                    )

            logger.info("brochure_download.complete", **stats)
            return {
                "status": "completed",
                "downloaded": stats["downloaded"],
                "not_found": stats["not_found"],
                "errors": stats["errors"],
                "skipped": skipped,
            }

        except Exception:
            raise
        finally:
            try:
                await db.execute(
                    sa_text(
                        f"SELECT pg_advisory_unlock({BROCHURE_DOWNLOAD_LOCK_ID})",
                    ),
                )
            except Exception:
                pass


async def run_brochure_extract() -> dict:
    """Phase B: Read PDFs from StorageClient → PyMuPDF → classify → DB.

    No network calls to IAPD.  Runs at full CPU speed.
    Only processes CRDs that have a PDF in storage but no rows in
    sec_manager_brochure_text yet.
    """
    storage = get_storage_client()

    async with async_session() as db:
        lock = await db.execute(
            sa_text(f"SELECT pg_try_advisory_lock({BROCHURE_EXTRACT_LOCK_ID})"),
        )
        if not lock.scalar():
            logger.warning("brochure_extract.lock_held")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            # CRDs with no brochure text in DB
            result = await db.execute(
                sa_text(
                    "SELECT m.crd_number FROM sec_managers m "
                    "LEFT JOIN sec_manager_brochure_text b "
                    "  ON m.crd_number = b.crd_number "
                    "WHERE b.crd_number IS NULL "
                    "  AND (m.private_fund_count > 0 "
                    "    OR m.hedge_fund_count > 0 "
                    "    OR m.pe_fund_count > 0 "
                    "    OR m.vc_fund_count > 0 "
                    "    OR m.real_estate_fund_count > 0) "
                    "ORDER BY m.crd_number",
                ),
            )
            pending_crds = [row[0] for row in result.fetchall()]

            if not pending_crds:
                logger.info("brochure_extract.nothing_pending")
                return {"status": "completed", "extracted": 0, "skipped": 0}

            # Filter to those with non-empty PDFs in storage
            crds_with_pdf: list[str] = []
            for crd in pending_crds:
                path = _storage_path(crd)
                if await storage.exists(path):
                    crds_with_pdf.append(crd)

            if not crds_with_pdf:
                logger.info(
                    "brochure_extract.no_pdfs",
                    pending_crds=len(pending_crds),
                )
                return {
                    "status": "completed",
                    "extracted": 0,
                    "no_pdf": len(pending_crds),
                }

            logger.info(
                "brochure_extract.starting", total=len(crds_with_pdf),
            )

            from data_providers.sec.adv_service import (
                AdvService,
                _classify_brochure_sections,
                _parse_team_from_brochure,
            )

            db_factory = async_session
            svc = AdvService(db_session_factory=db_factory)

            stats = {"extracted": 0, "empty": 0, "errors": 0}

            for i, crd in enumerate(crds_with_pdf):
                try:
                    pdf_bytes = await storage.read(_storage_path(crd))

                    if len(pdf_bytes) < 1024:
                        stats["empty"] += 1
                        continue

                    # PyMuPDF extraction in thread to avoid blocking event loop
                    full_text = await asyncio.to_thread(
                        _extract_text_from_pdf, pdf_bytes,
                    )

                    if not full_text or len(full_text) < 100:
                        stats["empty"] += 1
                        continue

                    sections = _classify_brochure_sections(crd, full_text)
                    team = _parse_team_from_brochure(crd, full_text)

                    if sections:
                        await svc._upsert_brochure_sections(crd, sections)
                    if team:
                        await svc._upsert_team(crd, team)

                    stats["extracted"] += 1

                except Exception as exc:
                    stats["errors"] += 1
                    logger.warning(
                        "brochure_extract.failed",
                        crd=crd,
                        error=str(exc)[:200],
                    )

                if (i + 1) % 200 == 0:
                    logger.info(
                        "brochure_extract.progress",
                        progress=i + 1,
                        total=len(crds_with_pdf),
                        **stats,
                    )

            logger.info("brochure_extract.complete", **stats)
            return {"status": "completed", **stats}

        except Exception:
            raise
        finally:
            try:
                await db.execute(
                    sa_text(
                        f"SELECT pg_advisory_unlock({BROCHURE_EXTRACT_LOCK_ID})",
                    ),
                )
            except Exception:
                pass


def _extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Sync PyMuPDF text extraction — meant to run in a thread."""
    import fitz  # pymupdf

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        pages = [page.get_text("text") for page in doc]
    return "\n\n".join(p for p in pages if p.strip())


if __name__ == "__main__":
    import sys

    phase = sys.argv[1] if len(sys.argv) > 1 else "both"
    if phase == "download":
        asyncio.run(run_brochure_download())
    elif phase == "extract":
        asyncio.run(run_brochure_extract())
    else:
        asyncio.run(run_brochure_download())
        asyncio.run(run_brochure_extract())
