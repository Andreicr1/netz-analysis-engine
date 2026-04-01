"""Run the 6 missing wealth embedding sources directly against Timescale Cloud.

Does NOT require the Railway backend running — connects to the DB and calls
OpenAI embedding API directly, reusing the existing worker functions.

Usage:
    cd backend
    python scripts/run_wealth_embedding_backfill.py              # all 6 missing
    python scripts/run_wealth_embedding_backfill.py --only sec_etf_profile sec_bdc_profile
    python scripts/run_wealth_embedding_backfill.py --all        # all 12 sources (full re-run)
    python scripts/run_wealth_embedding_backfill.py --dry-run    # just show counts, no embedding

Requires .env with DATABASE_URL and OPENAI_API_KEY.

Estimated volume (2026-03-29):
    sec_private_funds  ~5,577 managers (GAV >= $1B)
    sec_etf_profile    ~985 ETFs
    sec_bdc_profile    ~196 BDCs
    sec_mmf_profile    ~373 MMFs
    dd_chapter         ~24 chapters (org-scoped)
    macro_review       ~0 (no data yet)
    ─────────────────────────
    Total              ~7,155 rows → ~72 OpenAI API calls (~$1.50 at 3072-dim)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import traceback

# Ensure backend/ is on sys.path (needed when running as script)
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# ── Sources ──────────────────────────────────────────────────────────

BACKFILL_SOURCES = [
    "sec_fund_series_profile",
    "sec_private_funds",
    "sec_etf_profile",
    "sec_bdc_profile",
    "sec_mmf_profile",
    "dd_chapters",
    "macro_reviews",
]

ALL_SOURCES = [
    "brochure",
    "sec_manager_profile",
    "sec_fund_profile",
    "sec_fund_series_profile",
    "sec_13f_summary",
    "sec_private_funds",
    "esma_fund_profile",
    "esma_manager_profile",
    "sec_etf_profile",
    "sec_bdc_profile",
    "sec_mmf_profile",
    "dd_chapters",
    "macro_reviews",
]

# Maps source name → worker coroutine function name
_SOURCE_FN_MAP = {
    "brochure": "_embed_brochure_sections",
    "sec_manager_profile": "_embed_sec_manager_profiles",
    "sec_fund_profile": "_embed_sec_fund_profiles",
    "sec_fund_series_profile": "_embed_sec_fund_series_profiles",
    "sec_13f_summary": "_embed_sec_13f_summaries",
    "sec_private_funds": "_embed_sec_private_funds",
    "esma_fund_profile": "_embed_esma_fund_profiles",
    "esma_manager_profile": "_embed_esma_manager_profiles",
    "sec_etf_profile": "_embed_sec_etf_profiles",
    "sec_bdc_profile": "_embed_sec_bdc_profiles",
    "sec_mmf_profile": "_embed_sec_mmf_profiles",
    "dd_chapters": "_embed_dd_chapters",
    "macro_reviews": "_embed_macro_reviews",
}


async def dry_run() -> None:
    """Show current chunk counts per source — no embedding."""
    from sqlalchemy import text as sql_text

    from app.core.db.engine import async_session_factory

    async with async_session_factory() as db:
        result = await db.execute(sql_text("""
            SELECT source_type, count(*) as chunks, max(created_at) as last_embed
            FROM wealth_vector_chunks
            GROUP BY source_type
            ORDER BY chunks DESC
        """))
        rows = result.fetchall()

    print(f"\n{'Source Type':<25} {'Chunks':>8}  {'Last Embed'}")
    print("-" * 65)
    for source_type, chunks, last_embed in rows:
        print(f"{source_type:<25} {chunks:>8}  {last_embed}")
    total = sum(r[1] for r in rows)
    print("-" * 65)
    print(f"{'TOTAL':<25} {total:>8}")


async def run_sources(sources: list[str]) -> None:
    """Run selected embedding sources using the existing worker functions."""
    from sqlalchemy import text as sql_text

    from app.core.db.engine import async_session_factory
    from app.domains.wealth.workers import wealth_embedding_worker as worker_mod

    async with async_session_factory() as db:
        # Acquire advisory lock (same as worker — prevents concurrent runs)
        lock = await db.execute(sql_text("SELECT pg_try_advisory_lock(900041)"))
        if not lock.scalar():
            print("ERROR: Advisory lock 900041 held — another worker is running.")
            sys.exit(1)

        try:
            total_embedded = 0
            for source_name in sources:
                fn_name = _SOURCE_FN_MAP[source_name]
                fn = getattr(worker_mod, fn_name)

                print(f"\n{'=' * 60}")
                print(f"  Embedding: {source_name}")
                print(f"{'=' * 60}")

                t0 = time.monotonic()
                try:
                    result = await fn(db)
                    elapsed = time.monotonic() - t0
                    embedded = result.get("embedded", 0) if isinstance(result, dict) else 0
                    total_embedded += embedded
                    print(f"  Done: {source_name} ({elapsed:.1f}s) -> {result}")
                except Exception:
                    elapsed = time.monotonic() - t0
                    print(f"  FAILED: {source_name} ({elapsed:.1f}s)")
                    traceback.print_exc()
                    await db.rollback()

            print(f"\n{'=' * 60}")
            print(f"  COMPLETE — {total_embedded} chunks embedded across {len(sources)} sources")
            print(f"{'=' * 60}\n")
        finally:
            try:
                await db.execute(sql_text("SELECT pg_advisory_unlock(900041)"))
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill missing wealth vector embeddings",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        choices=ALL_SOURCES,
        help="Run only these specific sources",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all 12 sources (not just the 6 missing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Just show current chunk counts, no embedding",
    )
    args = parser.parse_args()

    if args.dry_run:
        asyncio.run(dry_run())
        return

    if args.only:
        sources = args.only
    elif args.all:
        sources = ALL_SOURCES
    else:
        sources = BACKFILL_SOURCES

    print(f"Sources to embed: {sources}")
    print(f"Total sources: {len(sources)}")
    asyncio.run(run_sources(sources))


if __name__ == "__main__":
    main()
