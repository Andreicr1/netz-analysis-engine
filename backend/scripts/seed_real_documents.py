#!/usr/bin/env python
"""Seed real documents from R2 bronze layer into the DB.

Creates Document + DocumentVersion records for each PDF blob in R2,
with ingestion_status=PENDING so the pipeline can process them.

Usage:
    cd backend && python scripts/seed_real_documents.py

Idempotent: skips documents that already exist (by blob_uri).
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
os.environ["APP_ENV"] = "development"

# ── Constants ─────────────────────────────────────────────────────────

ORG_ID = uuid.UUID("70f19993-b0d9-42ff-b3c7-cf2bb0728cec")
FUND_ID = uuid.UUID("66b1ed07-8274-4d96-806f-1515bb0e148b")
VERTICAL = "credit"
BRONZE_PREFIX = f"bronze/{ORG_ID}/{FUND_ID}/documents/"

# Only process PDFs (pipeline requires PDF bytes for OCR)
SUPPORTED_EXTENSIONS = {".pdf"}


async def main() -> None:
    import logging

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.config.settings import settings
    from app.domains.credit.modules.documents.models import Document, DocumentVersion
    from app.services.storage_client import get_storage_client
    from app.shared.enums import DocumentIngestionStatus

    engine = create_async_engine(settings.database_url, echo=False, pool_size=5)
    async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    storage = get_storage_client()

    # ── 1. List blobs in R2 ──────────────────────────────────────────
    print(f"Listing blobs under {BRONZE_PREFIX} ...")
    all_keys = await storage.list_files(BRONZE_PREFIX)
    print(f"  Total blobs: {len(all_keys)}")

    # Filter PDFs only
    pdf_blobs = [
        k for k in all_keys
        if Path(k).suffix.lower() in SUPPORTED_EXTENSIONS and not k.endswith("/")
    ]
    print(f"  PDFs to seed: {len(pdf_blobs)}")

    if not pdf_blobs:
        print("No PDFs found. Exiting.")
        await engine.dispose()
        return

    # ── 2. Check existing documents ──────────────────────────────────
    async with async_session_factory() as session:
        async with session.begin():
            safe_oid = str(ORG_ID).replace("'", "")
            await session.execute(
                text(f"SET LOCAL app.current_organization_id = '{safe_oid}'")
            )
            result = await session.execute(
                select(DocumentVersion.blob_uri).where(
                    DocumentVersion.organization_id == ORG_ID,
                )
            )
            existing_uris = {row[0] for row in result.fetchall() if row[0]}

    print(f"  Already seeded: {len(existing_uris)}")

    # ── 3. Insert documents ──────────────────────────────────────────
    created = 0
    skipped = 0

    for blob_key in sorted(pdf_blobs):
        if blob_key in existing_uris:
            skipped += 1
            continue

        # Parse doc_id and filename from path
        rel = blob_key[len(BRONZE_PREFIX):]
        parts = rel.split("/", 1)
        doc_id_str = parts[0]
        filename = parts[1] if len(parts) > 1 else doc_id_str

        try:
            doc_id = uuid.UUID(doc_id_str)
        except ValueError:
            print(f"  [SKIP] Invalid UUID in path: {doc_id_str}")
            skipped += 1
            continue

        # Determine root_folder and subfolder from filename
        if "/" in filename:
            folder_parts = filename.rsplit("/", 1)
            root_folder = folder_parts[0].split("/")[0]
            folder_path = folder_parts[0]
            title = folder_parts[1]
        else:
            root_folder = "1 Corporate Documentation"
            folder_path = root_folder
            title = filename

        version_id = uuid.uuid4()

        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(f"SET LOCAL app.current_organization_id = '{safe_oid}'")
                )

                doc = Document(
                    id=doc_id,
                    organization_id=ORG_ID,
                    fund_id=FUND_ID,
                    access_level="internal",
                    source="dataroom",
                    document_type="DATAROOM",
                    title=title,
                    status="uploaded",
                    current_version=1,
                    root_folder=root_folder,
                    folder_path=folder_path,
                    original_filename=filename,
                    content_type="application/pdf",
                    blob_uri=blob_key,
                    created_by="seed-script",
                    updated_by="seed-script",
                )
                session.add(doc)
                await session.flush()

                version = DocumentVersion(
                    id=version_id,
                    organization_id=ORG_ID,
                    fund_id=FUND_ID,
                    access_level="internal",
                    document_id=doc_id,
                    version_number=1,
                    blob_uri=blob_key,
                    blob_path=blob_key,
                    content_type="application/pdf",
                    is_final=False,
                    ingestion_status=DocumentIngestionStatus.PENDING,
                    uploaded_by="seed-script",
                    created_by="seed-script",
                    updated_by="seed-script",
                )
                session.add(version)

        created += 1
        print(f"  [OK] {doc_id} | {title}")

    await engine.dispose()

    print(f"\n{'='*60}")
    print(f"  Seed complete: {created} created, {skipped} skipped")
    print(f"  Total PENDING: {created}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
