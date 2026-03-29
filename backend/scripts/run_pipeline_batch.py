#!/usr/bin/env python
"""Run unified pipeline for all PENDING document versions.

Processes in batches, logs progress per document.

Usage:
    cd backend && python scripts/run_pipeline_batch.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
os.environ["APP_ENV"] = "development"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("lmstudio").setLevel(logging.WARNING)

logger = logging.getLogger("pipeline_batch")

# ── Constants ─────────────────────────────────────────────────────────

ORG_ID = uuid.UUID("70f19993-b0d9-42ff-b3c7-cf2bb0728cec")
FUND_ID = uuid.UUID("66b1ed07-8274-4d96-806f-1515bb0e148b")
BATCH_SIZE = 5


async def main() -> None:
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.config.settings import settings

    # Patch uppercase attrs
    _cls = type(settings)
    if not hasattr(settings, "OPENAI_API_KEY"):
        _cls.OPENAI_API_KEY = property(lambda s: s.openai_api_key)
    if not hasattr(settings, "MISTRAL_API_KEY"):
        _cls.MISTRAL_API_KEY = property(lambda s: os.environ.get("MISTRAL_API_KEY", ""))
    if not hasattr(settings, "MISTRAL_OCR_RATE_LIMIT"):
        _cls.MISTRAL_OCR_RATE_LIMIT = property(lambda s: 5)

    from app.domains.credit.modules.documents.models import Document, DocumentVersion
    from app.shared.enums import DocumentIngestionStatus
    from ai_engine.pipeline.models import IngestRequest
    from ai_engine.pipeline.unified_pipeline import process

    engine = create_async_engine(settings.database_url, echo=False, pool_size=5)
    sf = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    safe_oid = str(ORG_ID).replace("'", "")

    # ── Count pending ─────────────────────────────────────────────
    async with sf() as s:
        async with s.begin():
            await s.execute(text(f"SET LOCAL app.current_organization_id = '{safe_oid}'"))
            r = await s.execute(
                select(DocumentVersion)
                .where(DocumentVersion.organization_id == ORG_ID)
                .where(DocumentVersion.ingestion_status == DocumentIngestionStatus.PENDING)
                .order_by(DocumentVersion.created_at)
            )
            all_pending = r.scalars().all()

    total = len(all_pending)
    logger.info("Total PENDING documents: %d", total)

    if total == 0:
        logger.info("Nothing to process.")
        await engine.dispose()
        return

    # ── Load parent documents ─────────────────────────────────────
    doc_ids = {v.document_id for v in all_pending}
    async with sf() as s:
        async with s.begin():
            await s.execute(text(f"SET LOCAL app.current_organization_id = '{safe_oid}'"))
            r = await s.execute(
                select(Document).where(Document.id.in_(doc_ids))
            )
            docs_by_id = {d.id: d for d in r.scalars().all()}

    # ── Process in batches ────────────────────────────────────────
    completed = 0
    failed = 0
    skipped = 0
    results: list[dict] = []
    t0 = time.time()

    for batch_start in range(0, total, BATCH_SIZE):
        batch = all_pending[batch_start : batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

        logger.info(
            "━━━ Batch %d/%d (%d docs) ━━━",
            batch_num, total_batches, len(batch),
        )

        for i, version in enumerate(batch):
            doc = docs_by_id.get(version.document_id)
            filename = doc.title if doc else "unknown.pdf"
            doc_num = batch_start + i + 1

            logger.info(
                "[%d/%d] %s (doc_id=%s)",
                doc_num, total, filename, str(version.document_id)[:8],
            )

            # Skip non-PDF
            if not (version.blob_uri or "").lower().endswith(".pdf"):
                logger.warning("  SKIP — not a PDF: %s", version.blob_uri)
                skipped += 1

                async with sf() as s:
                    async with s.begin():
                        await s.execute(text(f"SET LOCAL app.current_organization_id = '{safe_oid}'"))
                        await s.execute(
                            text("UPDATE document_versions SET ingestion_status = 'FAILED', ingest_error = :err WHERE id = :vid"),
                            {"vid": version.id, "err": json.dumps({"reason": "not_pdf"})},
                        )
                continue

            # Mark PROCESSING
            async with sf() as s:
                async with s.begin():
                    await s.execute(text(f"SET LOCAL app.current_organization_id = '{safe_oid}'"))
                    await s.execute(
                        text("UPDATE document_versions SET ingestion_status = 'PROCESSING' WHERE id = :vid"),
                        {"vid": version.id},
                    )

            # Build request
            req = IngestRequest(
                source="batch",
                org_id=ORG_ID,
                vertical="credit",
                document_id=version.document_id,
                blob_uri=version.blob_uri or "",
                filename=filename,
                fund_id=FUND_ID,
                version_id=version.id,
            )

            # Run pipeline without db session — pgvector index will be
            # rebuilt from silver Parquet via search_rebuild.py after all
            # documents are processed (dual-write architecture).
            t1 = time.time()
            try:
                result = await process(req, db=None, actor_id="batch-pipeline", skip_index=True)
                elapsed = time.time() - t1

                if result.success:
                    completed += 1
                    m = result.metrics
                    doc_type = m.get("doc_type", "?")
                    chunks = m.get("chunk_count", 0)
                    pages = m.get("page_count", 0)
                    terminal = m.get("terminal_state", "?")
                    logger.info(
                        "  ✓ %s | %d pages | %d chunks | %s | %.0fs",
                        doc_type, pages, chunks, terminal, elapsed,
                    )
                    results.append({
                        "doc_id": str(version.document_id),
                        "filename": filename,
                        "doc_type": doc_type,
                        "pages": pages,
                        "chunks": chunks,
                        "status": "completed",
                        "elapsed_s": round(elapsed, 1),
                    })

                    # Mark INDEXED
                    async with sf() as s:
                        async with s.begin():
                            await s.execute(text(f"SET LOCAL app.current_organization_id = '{safe_oid}'"))
                            await s.execute(
                                text("UPDATE document_versions SET ingestion_status = 'INDEXED', indexed_at = NOW() WHERE id = :vid"),
                                {"vid": version.id},
                            )
                else:
                    failed += 1
                    errors = result.errors[:2] if result.errors else ["unknown"]
                    logger.error(
                        "  ✗ FAILED at stage=%s: %s (%.0fs)",
                        result.stage, errors[0][:100], elapsed,
                    )
                    results.append({
                        "doc_id": str(version.document_id),
                        "filename": filename,
                        "status": "failed",
                        "stage": result.stage,
                        "error": errors[0][:200],
                        "elapsed_s": round(elapsed, 1),
                    })

                    async with sf() as s:
                        async with s.begin():
                            await s.execute(text(f"SET LOCAL app.current_organization_id = '{safe_oid}'"))
                            await s.execute(
                                text("UPDATE document_versions SET ingestion_status = 'FAILED', ingest_error = :err WHERE id = :vid"),
                                {"vid": version.id, "err": json.dumps({"stage": result.stage, "errors": result.errors[:3]})},
                            )

            except Exception as e:
                elapsed = time.time() - t1
                failed += 1
                logger.exception("  ✗ EXCEPTION: %s (%.0fs)", str(e)[:100], elapsed)
                results.append({
                    "doc_id": str(version.document_id),
                    "filename": filename,
                    "status": "exception",
                    "error": str(e)[:200],
                    "elapsed_s": round(elapsed, 1),
                })

                async with sf() as s:
                    async with s.begin():
                        await s.execute(text(f"SET LOCAL app.current_organization_id = '{safe_oid}'"))
                        await s.execute(
                            text("UPDATE document_versions SET ingestion_status = 'FAILED', ingest_error = :err WHERE id = :vid"),
                            {"vid": version.id, "err": json.dumps({"reason": str(e)[:500]})},
                        )

        logger.info(
            "  Batch %d done: %d completed, %d failed, %d skipped so far",
            batch_num, completed, failed, skipped,
        )

    total_elapsed = time.time() - t0

    # ── Summary ───────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  PIPELINE COMPLETE")
    print(f"  {completed} completed, {failed} failed, {skipped} skipped")
    print(f"  Total time: {total_elapsed/60:.1f} min")
    print(f"{'='*70}")

    # Doc type distribution
    type_counts: dict[str, int] = {}
    for r in results:
        if r["status"] == "completed":
            dt = r.get("doc_type", "unknown")
            type_counts[dt] = type_counts.get(dt, 0) + 1
    if type_counts:
        print("\nDoc type distribution:")
        for dt, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f"  {cnt:3d} {dt}")

    # Save results
    out_path = Path(__file__).parent / "pipeline_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {out_path}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
