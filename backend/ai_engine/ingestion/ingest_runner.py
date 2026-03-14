"""Background task runner for the Domain Ingest Orchestrator.

Provides:
1. CLI entrypoint for cron / Azure Container Apps Jobs
2. FastAPI BackgroundTasks integration
3. Standalone asyncio runner

Does NOT block the main API thread.
"""
import argparse
import logging
import sys
import uuid

logger = logging.getLogger(__name__)


def _get_db_session():
    """Create a standalone database session (outside FastAPI request cycle)."""

    SessionLocal = async_session_factory
    return SessionLocal()


# ── Synchronous runner (CLI / cron) ───────────────────────────────────


def run_ingest_sync(fund_id: uuid.UUID, *, batch_size: int = 50, run_ai: bool = True) -> dict:
    """Run the ingest orchestrator synchronously.

    Suitable for cron jobs, Azure Container Apps Jobs, or manual invocation.
    """
    from ai_engine.ingestion.domain_ingest_orchestrator import run_ingest_for_unindexed_documents

    db = _get_db_session()
    try:
        result = run_ingest_for_unindexed_documents(
            db, fund_id=fund_id, batch_size=batch_size, run_ai_analysis=run_ai,
        )
        return {
            "documents_processed": result.documents_processed,
            "documents_succeeded": result.documents_succeeded,
            "documents_failed": result.documents_failed,
            "chunks_upserted": result.chunks_upserted,
            "deals_analyzed": result.deals_analyzed,
            "errors": result.errors,
        }
    finally:
        db.close()


# ── FastAPI BackgroundTasks integration ───────────────────────────────


def schedule_ingest_background(fund_id: uuid.UUID, *, batch_size: int = 50) -> None:
    """Intended to be called via ``BackgroundTasks.add_task()``.

    Example in a route:
        @router.post("/ingest/trigger")
        def trigger_ingest(fund_id: uuid.UUID, bg: BackgroundTasks):
            bg.add_task(schedule_ingest_background, fund_id)
            return {"status": "scheduled"}
    """
    try:
        result = run_ingest_sync(fund_id, batch_size=batch_size, run_ai=True)
        logger.info("Background ingest completed: %s", result)
    except Exception:
        logger.error("Background ingest failed for fund %s", fund_id, exc_info=True)


# ── FastAPI route for manual triggering ───────────────────────────────


def create_ingest_router():
    """Create a FastAPI router for ingest trigger endpoints."""
    from fastapi import APIRouter, BackgroundTasks, Depends, Query

    from app.core.security.auth import Actor
    from app.core.security.dependencies import get_actor, require_readonly_allowed

    router = APIRouter(prefix="/ai/ingest", tags=["ai-ingest"])

    @router.post("/trigger")
    def trigger_ingest(
        fund_id: uuid.UUID,
        background_tasks: BackgroundTasks,
        batch_size: int = Query(default=50, ge=1, le=200),
        actor: Actor = Depends(get_actor),
        _write_guard: Actor = Depends(require_readonly_allowed()),
    ):
        background_tasks.add_task(schedule_ingest_background, fund_id, batch_size=batch_size)
        return {
            "status": "scheduled",
            "fund_id": str(fund_id),
            "batch_size": batch_size,
            "triggered_by": actor.actor_id,
        }

    @router.post("/run")
    def run_ingest_synchronous(
        fund_id: uuid.UUID,
        batch_size: int = Query(default=50, ge=1, le=200),
        run_ai: bool = Query(default=True),
        actor: Actor = Depends(get_actor),
        _write_guard: Actor = Depends(require_readonly_allowed()),
    ):
        """Run ingest synchronously (blocks until complete). Use for debugging."""
        result = run_ingest_sync(fund_id, batch_size=batch_size, run_ai=run_ai)
        return result

    return router


# ── CLI entrypoint ────────────────────────────────────────────────────


def main():
    """CLI entrypoint: python -m ai_engine.ingestion.ingest_runner --fund-id <UUID>"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Domain Ingest Orchestrator — CLI Runner")
    parser.add_argument("--fund-id", type=str, required=True, help="Fund UUID to process")
    parser.add_argument("--batch-size", type=int, default=50, help="Max documents per run")
    parser.add_argument("--skip-ai", action="store_true", help="Skip AI analysis after ingestion")

    args = parser.parse_args()

    try:
        fund_id = uuid.UUID(args.fund_id)
    except ValueError:
        print(f"Invalid UUID: {args.fund_id}", file=sys.stderr)
        sys.exit(1)

    logger.info("Starting ingest for fund %s (batch=%d, ai=%s)", fund_id, args.batch_size, not args.skip_ai)
    result = run_ingest_sync(fund_id, batch_size=args.batch_size, run_ai=not args.skip_ai)

    print(f"\n{'='*60}")
    print(f"  Documents processed:  {result['documents_processed']}")
    print(f"  Documents succeeded:  {result['documents_succeeded']}")
    print(f"  Documents failed:     {result['documents_failed']}")
    print(f"  Chunks upserted:      {result['chunks_upserted']}")
    print(f"  Deals analyzed:       {result['deals_analyzed']}")
    if result["errors"]:
        print("\n  Errors:")
        for err in result["errors"]:
            print(f"    - {err}")
    print(f"{'='*60}\n")

    sys.exit(1 if result["documents_failed"] > 0 else 0)


if __name__ == "__main__":
    main()
