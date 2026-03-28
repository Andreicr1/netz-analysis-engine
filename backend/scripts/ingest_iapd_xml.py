"""One-shot IAPD XML enrichment.

Parses IAPD XML feed(s) and enriches sec_managers with Form ADV Part 1A
structured data (AUM, fees, client types, website, compliance disclosures).

Usage:
    cd backend
    python scripts/ingest_iapd_xml.py "C:/path/to/IA_FIRM_SEC_Feed.xml"
    python scripts/ingest_iapd_xml.py "C:/path/to/IA_FIRM_SEC_Feed.xml" "C:/path/to/IA_FIRM_STATE_Feed.xml"
"""

from __future__ import annotations

import asyncio
import sys

import structlog

from app.core.db.engine import async_session_factory as async_session

logger = structlog.get_logger()


async def main(xml_paths: list[str]) -> None:
    from data_providers.sec.adv_service import AdvService

    service = AdvService(db_session_factory=async_session)

    total = 0
    for path in xml_paths:
        logger.info("ingest_iapd_xml_start", path=path)
        updated = await service.ingest_iapd_xml(path)
        logger.info("ingest_iapd_xml_done", path=path, updated=updated)
        total += updated

    logger.info("ingest_iapd_xml_all_done", total_updated=total)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    xml_paths = sys.argv[1:]
    for p in xml_paths:
        import os

        if not os.path.exists(p):
            print(f"ERROR: File not found: {p}")
            sys.exit(1)

    asyncio.run(main(xml_paths))
