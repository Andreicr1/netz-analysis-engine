"""Canonical Pipeline Ingest Runner — single entry point for the full pipeline.

Orchestrates the complete ingest lifecycle:
    1. Scan blob containers → DocumentRegistry           (document_scanner)
    2. Discover pipeline deals from folder structure      (pipeline_intelligence)
    3. Bridge DocumentRegistry → DealDocument             (registry_bridge)
    4. (Skipped — per-document ingestion via unified_pipeline at upload time)
    5. Deep Review — AI intelligence for all deals        (deep_review)

Every invocation creates a ``PipelineIngestJob`` row that records counters,
timing, and structured error payloads.  The row is the canonical audit trail.

Usage:
    CLI:
        cd backend
        python -m ai_engine.ingestion.pipeline_ingest_runner --fund-id <UUID>

    API:
        POST /ai/ingest/pipeline { "fund_id": "<UUID>" }
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence

logger = logging.getLogger(__name__)


@dataclass
class PipelineIngestResult:
    """Aggregate result across all pipeline stages."""

    documents_scanned: int = 0
    deals_discovered: int = 0
    documents_bridged: int = 0
    documents_ingested: int = 0
    documents_failed: int = 0
    chunks_upserted: int = 0
    new_deals_detected: int = 0
    deals_analyzed: int = 0
    deals_deep_reviewed: int = 0
    deep_review_errors: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    job_id: str | None = None


def _coerce_uuid(value: uuid.UUID | str, *, field_name: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a valid UUID")
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid UUID") from exc


_MAX_DEAL_IDS = 500  # Hard upper bound; matches domain batch_size default and Service Bus limits


def _coerce_uuid_list(
    values: Sequence[uuid.UUID | str] | None,
    *,
    field_name: str,
) -> list[uuid.UUID] | None:
    if values is None:
        return None
    if len(values) > _MAX_DEAL_IDS:
        raise ValueError(
            f"{field_name} exceeds maximum allowed length of {_MAX_DEAL_IDS} items"
        )
    coerced: list[uuid.UUID] = []
    for idx, value in enumerate(values):
        coerced.append(_coerce_uuid(value, field_name=f"{field_name}[{idx}]"))
    return coerced


def _create_ingest_job(db, *, fund_id: uuid.UUID, actor_id: str):
    """Create a PipelineIngestJob row with status=RUNNING."""
    from app.domains.credit.modules.ai.ingest_job_model import IngestJobStatus, PipelineIngestJob

    job = PipelineIngestJob(
        fund_id=str(fund_id),
        status=IngestJobStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(job)
    db.flush()
    return job


def _get_db_session():
    """Mirror the legacy ingest runner bootstrap for worker execution."""
    from app.core.db.engine import async_session_factory

    SessionLocal = async_session_factory
    return SessionLocal()


def _finalise_job(db, job, *, result: PipelineIngestResult, failed: bool):
    """Persist final counters and status to the PipelineIngestJob row."""
    from app.domains.credit.modules.ai.ingest_job_model import IngestJobStatus

    job.finished_at = datetime.now(timezone.utc)
    job.documents_discovered = result.documents_scanned
    job.documents_bridged = result.documents_bridged
    job.documents_ingested = result.documents_ingested
    job.documents_failed = result.documents_failed
    job.chunks_created = result.chunks_upserted
    job.status = IngestJobStatus.FAILED if failed else IngestJobStatus.COMPLETED
    if result.errors:
        job.error_summary = {
            "count": len(result.errors),
            "errors": result.errors[:50],  # cap stored errors
        }
    try:
        db.commit()
    except Exception:
        logger.error("Failed to persist PipelineIngestJob final state", exc_info=True)
        db.rollback()


def run_full_pipeline_ingest(
    fund_id: uuid.UUID | str,
    *,
    deal_ids: Sequence[uuid.UUID | str] | None = None,
    batch_size: int = 50,
    run_ai_analysis: bool = True,
    full_mode: bool = False,
    actor_id: str = "pipeline-ingest-runner",
) -> PipelineIngestResult:
    """Execute the full pipeline ingest lifecycle (synchronous).

    Creates its own DB session — safe for CLI, cron, BackgroundTasks.
    Every call produces a ``PipelineIngestJob`` row (audit trail).

    If *deal_ids* is provided, only blobs belonging to those deals are bridged
    and ingested — enabling incremental processing of new deals without
    re-processing the entire fund.
    """
    fund_id = _coerce_uuid(fund_id, field_name="fund_id")
    deal_ids = _coerce_uuid_list(deal_ids, field_name="deal_ids")
    result = PipelineIngestResult(started_at=datetime.now(timezone.utc).isoformat())
    db = _get_db_session()

    # ── Create audit job row ──────────────────────────────────────────
    job = None
    try:
        job = _create_ingest_job(db, fund_id=fund_id, actor_id=actor_id)
        db.commit()
        result.job_id = str(job.id)
        logger.info("PipelineIngestJob %s created for fund %s", job.id, fund_id)
    except Exception:
        logger.error("Failed to create PipelineIngestJob row", exc_info=True)
        db.rollback()

    pipeline_failed = False
    try:
        # ── Stage 1: Scan blob containers ─────────────────────────────
        logger.info("[Stage 1/5] Scanning blob containers for fund %s", fund_id)
        try:
            from ai_engine.ingestion.document_scanner import scan_document_registry

            scanned = scan_document_registry(db, fund_id=fund_id, actor_id=actor_id)
            result.documents_scanned = len(scanned)
            logger.info("Stage 1 complete: %d documents scanned", result.documents_scanned)
        except Exception as exc:
            error = f"Stage 1 (scan) failed: {exc}"
            logger.error(error, exc_info=True)
            result.errors.append(error)

        # ── Capture existing deal IDs for new-deal auto-detect ────────
        pre_existing_deal_ids: set[uuid.UUID] = set()
        try:
            from sqlalchemy import select as sa_select

            from app.domains.credit.modules.deals.models import PipelineDeal
            pre_existing_deal_ids = set(
                db.execute(
                    sa_select(PipelineDeal.id).where(PipelineDeal.fund_id == fund_id)
                ).scalars().all()
            )
        except Exception:
            logger.debug("Could not query pre-existing deals for auto-detect", exc_info=True)

        # ── Stage 2: Discover pipeline deals ──────────────────────────
        logger.info("[Stage 2/5] Discovering pipeline deals for fund %s", fund_id)
        deals: list = []
        try:
            from vertical_engines.credit.pipeline import discover_pipeline_deals

            deals = discover_pipeline_deals(db, fund_id=fund_id, actor_id=actor_id)
            result.deals_discovered = len(deals)
            logger.info("Stage 2 complete: %d deals discovered", result.deals_discovered)
        except Exception as exc:
            error = f"Stage 2 (discover) failed: {exc}"
            logger.error(error, exc_info=True)
            result.errors.append(error)

        # ── Auto-detect new deals → scope Stages 3-4 ─────────────────
        effective_deal_ids: list[uuid.UUID] | None = deal_ids  # explicit user filter takes priority
        if deal_ids is None and deals:
            new_deal_ids = [d.id for d in deals if d.id not in pre_existing_deal_ids]
            result.new_deals_detected = len(new_deal_ids)
            if new_deal_ids:
                effective_deal_ids = new_deal_ids
                new_names = [d.deal_name for d in deals if d.id in set(new_deal_ids)]
                logger.info(
                    "Auto-detected %d NEW deal(s): %s — scoping Stages 3-4 to new deals only",
                    len(new_deal_ids), new_names,
                )
            else:
                logger.info(
                    "No new deals detected — Stages 3-4 run unfiltered "
                    "(last_indexed_at protects against re-processing)"
                )
        elif deal_ids:
            logger.info("User-specified deal filter: %d deal(s)", len(deal_ids))

        # ── Stage 3: Bridge registry → DealDocument ───────────────────
        logger.info("[Stage 3/5] Bridging DocumentRegistry → DealDocument for fund %s", fund_id)
        try:
            from ai_engine.ingestion.registry_bridge import bridge_registry_to_deal_documents

            bridge = bridge_registry_to_deal_documents(db, fund_id=fund_id, deal_ids=effective_deal_ids, actor_id=actor_id)
            result.documents_bridged = bridge.documents_created
            if bridge.errors:
                result.errors.extend(bridge.errors)
            logger.info("Stage 3 complete: %d documents bridged", result.documents_bridged)
        except Exception as exc:
            error = f"Stage 3 (bridge) failed: {exc}"
            logger.error(error, exc_info=True)
            result.errors.append(error)

        # ── Stage 4: Document ingestion ─────────────────────────────────
        # NOTE: Individual document ingestion now runs through the unified
        # pipeline (ai_engine/pipeline/unified_pipeline.process()) which is
        # triggered per-document at upload time.  Batch re-ingestion of
        # unindexed documents is handled by Stage 5 (Deep Review) which
        # processes all deals with pending documents.
        logger.info("[Stage 4/5] Skipped — document ingestion handled by unified pipeline per-upload")

        # ── Stage 5: Deep Review — AI intelligence for all deals ─────
        if run_ai_analysis:
            logger.info("[Stage 5/5] Running Deep Review for all deals in fund %s", fund_id)
            try:
                from vertical_engines.credit.deep_review import run_all_deals_deep_review_v4

                logger.info("PIPELINE_USING_DEEP_REVIEW_V4")
                review_result = run_all_deals_deep_review_v4(
                    db, fund_id=fund_id, actor_id=actor_id, full_mode=full_mode,
                )
                result.deals_deep_reviewed = review_result.get("reviewed", 0)
                result.deep_review_errors = review_result.get("errors", 0)
                logger.info(
                    "Stage 5 complete: %d deals reviewed, %d errors",
                    result.deals_deep_reviewed, result.deep_review_errors,
                )
                # Append individual deal errors for audit trail
                for dr in review_result.get("results", []):
                    if "error" in dr:
                        result.errors.append(
                            f"Deep review failed for deal {dr.get('dealId', '?')}: {dr['error']}"
                        )
            except Exception as exc:
                error = f"Stage 5 (deep-review) failed: {exc}"
                logger.error(error, exc_info=True)
                result.errors.append(error)
        else:
            logger.info("[Stage 5/5] Skipping Deep Review (run_ai_analysis=False)")

    except Exception as exc:
        # Top-level catch: unexpected fatal error
        error = f"Pipeline fatal error: {exc}"
        logger.error(error, exc_info=True)
        result.errors.append(error)
        pipeline_failed = True

    finally:
        result.finished_at = datetime.now(timezone.utc).isoformat()

        # Determine failure: explicit fatal OR any stage errors
        if result.errors:
            pipeline_failed = True

        # ── Persist final job state ───────────────────────────────────
        if job is not None:
            try:
                # Re-fetch inside same session to ensure merge works
                db.refresh(job)
                _finalise_job(db, job, result=result, failed=pipeline_failed)
                logger.info(
                    "PipelineIngestJob %s finalised: status=%s",
                    job.id,
                    "FAILED" if pipeline_failed else "COMPLETED",
                )
            except Exception:
                logger.error("Could not finalise PipelineIngestJob %s", job.id, exc_info=True)

        db.close()

    logger.info(
        "Full pipeline ingest complete: scanned=%d, deals=%d (new=%d), bridged=%d, "
        "ingested=%d, failed=%d, chunks=%d, analyzed=%d, deep_reviewed=%d, errors=%d",
        result.documents_scanned, result.deals_discovered, result.new_deals_detected,
        result.documents_bridged,
        result.documents_ingested, result.documents_failed, result.chunks_upserted,
        result.deals_analyzed, result.deals_deep_reviewed, len(result.errors),
    )
    return result


async def async_run_full_pipeline_ingest(
    fund_id: uuid.UUID | str,
    *,
    deal_ids: Sequence[uuid.UUID | str] | None = None,
    batch_size: int = 200,
    run_ai_analysis: bool = True,
    full_mode: bool = False,
    actor_id: str = "pipeline-ingest-runner",
) -> PipelineIngestResult:
    """Async version of ``run_full_pipeline_ingest``.

    Stages 1-3 run synchronously via ``asyncio.to_thread()`` (fast, DB-heavy).
    Stage 4 uses ``async_run_ingest_for_unindexed_documents()`` (parallel).
    Stage 5 uses the existing async deep review path.

    Creates its own DB session — safe for worker and BackgroundTasks.
    """
    fund_id = _coerce_uuid(fund_id, field_name="fund_id")
    deal_ids_coerced = _coerce_uuid_list(deal_ids, field_name="deal_ids")
    result = PipelineIngestResult(started_at=datetime.now(timezone.utc).isoformat())
    db = _get_db_session()

    # ── Create audit job row ──────────────────────────────────────────
    job = None
    try:
        job = _create_ingest_job(db, fund_id=fund_id, actor_id=actor_id)
        db.commit()
        result.job_id = str(job.id)
        logger.info("PipelineIngestJob %s created for fund %s", job.id, fund_id)
    except Exception:
        logger.error("Failed to create PipelineIngestJob row", exc_info=True)
        db.rollback()

    pipeline_failed = False
    effective_deal_ids: list[uuid.UUID] | None = deal_ids_coerced
    try:
        # ── Stage 1: Scan blob containers (sync via to_thread) ────────
        logger.info("[Stage 1/5] Scanning blob containers for fund %s", fund_id)
        try:
            from ai_engine.ingestion.document_scanner import scan_document_registry

            # SAFETY: These closures share `db` session — they MUST be awaited
            # sequentially. Do NOT use asyncio.gather() on these stages.
            def _scan_threadsafe() -> list:
                return scan_document_registry(db, fund_id=fund_id, actor_id=actor_id)

            scanned = await asyncio.to_thread(_scan_threadsafe)
            result.documents_scanned = len(scanned)
            logger.info("Stage 1 complete: %d documents scanned", result.documents_scanned)
        except Exception as exc:
            error = f"Stage 1 (scan) failed: {exc}"
            logger.error(error, exc_info=True)
            result.errors.append(error)

        # ── Capture existing deal IDs for new-deal auto-detect ────────
        pre_existing_deal_ids: set[uuid.UUID] = set()
        try:
            from sqlalchemy import select as sa_select

            from app.domains.credit.modules.deals.models import PipelineDeal
            pre_existing_deal_ids = set(
                db.execute(
                    sa_select(PipelineDeal.id).where(PipelineDeal.fund_id == fund_id)
                ).scalars().all()
            )
        except Exception:
            logger.debug("Could not query pre-existing deals for auto-detect", exc_info=True)

        # ── Stage 2: Discover pipeline deals (sync via to_thread) ─────
        logger.info("[Stage 2/5] Discovering pipeline deals for fund %s", fund_id)
        deals: list = []
        try:
            from vertical_engines.credit.pipeline import discover_pipeline_deals

            def _discover_threadsafe() -> list:
                return discover_pipeline_deals(db, fund_id=fund_id, actor_id=actor_id)

            deals = await asyncio.to_thread(_discover_threadsafe)
            result.deals_discovered = len(deals)
            logger.info("Stage 2 complete: %d deals discovered", result.deals_discovered)
        except Exception as exc:
            error = f"Stage 2 (discover) failed: {exc}"
            logger.error(error, exc_info=True)
            result.errors.append(error)

        # ── Auto-detect new deals → scope Stages 3-5 ─────────────────
        if deal_ids_coerced is None and deals:
            new_deal_ids = [d.id for d in deals if d.id not in pre_existing_deal_ids]
            result.new_deals_detected = len(new_deal_ids)
            if new_deal_ids:
                effective_deal_ids = new_deal_ids
                new_names = [d.deal_name for d in deals if d.id in set(new_deal_ids)]
                logger.info(
                    "Auto-detected %d NEW deal(s): %s — scoping Stages 3-5 to new deals only",
                    len(new_deal_ids), new_names,
                )
            else:
                logger.info("No new deals detected — Stages 3-5 run unfiltered")
        elif deal_ids_coerced:
            logger.info("User-specified deal filter: %d deal(s)", len(deal_ids_coerced))

        # ── Stage 2.5: Entity Bootstrap (async) ───────────────────────
        fund_contexts: dict[uuid.UUID, object] = {}  # deal_id -> FundContext
        if deals:
            logger.info("[Stage 2.5] Entity bootstrap for %d deals in fund %s", len(deals), fund_id)
            try:
                # Build blob paths per deal from DocumentRegistry
                from sqlalchemy import select as sa_select2

                from ai_engine.extraction.entity_bootstrap import async_bootstrap_deal
                from app.domains.credit.modules.documents.models import DocumentRegistry

                deal_blob_map: dict[uuid.UUID, list[tuple[str, str]]] = {}
                target_deal_ids = effective_deal_ids or [d.id for d in deals]

                # Single query: all blob paths for this fund (no LIKE wildcards, no N+1)
                all_rows = db.execute(
                    sa_select2(
                        DocumentRegistry.container_name,
                        DocumentRegistry.blob_path,
                    ).where(
                        DocumentRegistry.fund_id == fund_id,
                    )
                ).all()

                # Partition by deal name match in Python
                for deal in deals:
                    if deal.id not in target_deal_ids:
                        continue
                    blob_pairs = [
                        (r[0], r[1]) for r in all_rows
                        if deal.deal_name in r[1] and r[1].lower().endswith(".pdf")
                    ][:5]
                    if blob_pairs:
                        deal_blob_map[deal.id] = blob_pairs

                # Run bootstrap for each deal concurrently
                async def _bootstrap_one(deal_obj) -> tuple[uuid.UUID, object]:
                    blobs = deal_blob_map.get(deal_obj.id, [])
                    ctx = await async_bootstrap_deal(
                        deal_name=deal_obj.deal_name,
                        blob_paths=blobs,
                    )
                    return deal_obj.id, ctx

                target_set = set(target_deal_ids) if target_deal_ids else {d.id for d in deals}
                bootstrap_sem = asyncio.Semaphore(5)

                async def _bounded_bootstrap_one(d):
                    async with bootstrap_sem:
                        return await _bootstrap_one(d)

                bootstrap_tasks = [
                    _bounded_bootstrap_one(d) for d in deals
                    if d.id in target_set
                ]
                bootstrap_results = await asyncio.gather(*bootstrap_tasks, return_exceptions=True)

                for br in bootstrap_results:
                    if isinstance(br, Exception):
                        logger.warning("Entity bootstrap failed for a deal: %s", br)
                        continue
                    deal_id_result, fund_ctx = br
                    fund_contexts[deal_id_result] = fund_ctx

                logger.info(
                    "Stage 2.5 complete: %d/%d deals bootstrapped",
                    len(fund_contexts), len(bootstrap_tasks),
                )
            except Exception as exc:
                error = f"Stage 2.5 (entity-bootstrap) failed: {exc}"
                logger.error(error, exc_info=True)
                result.errors.append(error)

        # ── Stage 3: Bridge registry → DealDocument (sync via to_thread)
        logger.info("[Stage 3/5] Bridging DocumentRegistry → DealDocument for fund %s", fund_id)
        try:
            from ai_engine.ingestion.registry_bridge import bridge_registry_to_deal_documents

            def _bridge_threadsafe():
                return bridge_registry_to_deal_documents(
                    db, fund_id=fund_id, deal_ids=effective_deal_ids, actor_id=actor_id,
                )

            bridge = await asyncio.to_thread(_bridge_threadsafe)
            result.documents_bridged = bridge.documents_created
            if bridge.errors:
                result.errors.extend(bridge.errors)
            logger.info("Stage 3 complete: %d documents bridged", result.documents_bridged)
        except Exception as exc:
            error = f"Stage 3 (bridge) failed: {exc}"
            logger.error(error, exc_info=True)
            result.errors.append(error)

        # Close the session used for Stages 1-3 before Stage 5
        db.close()

        # ── Stage 4: Document ingestion ──────────────────────────────
        # NOTE: Individual document ingestion now runs through the unified
        # pipeline (ai_engine/pipeline/unified_pipeline.process()) which is
        # triggered per-document at upload time.  Batch re-ingestion of
        # unindexed documents is handled by Stage 5 (Deep Review) which
        # processes all deals with pending documents.
        logger.info("[Stage 4/5] Skipped — document ingestion handled by unified pipeline per-upload")

        # ── Stage 5: Deep Review ──────────────────────────────────────
        if run_ai_analysis:
            logger.info("[Stage 5/5] Running Deep Review for all deals in fund %s", fund_id)
            try:
                from vertical_engines.credit.deep_review import run_all_deals_deep_review_v4

                # Deep review uses its own sessions internally
                def _deep_review_threadsafe():
                    review_db = _get_db_session()
                    try:
                        return run_all_deals_deep_review_v4(
                            review_db, fund_id=fund_id, actor_id=actor_id, full_mode=full_mode,
                        )
                    finally:
                        review_db.close()

                review_result = await asyncio.to_thread(_deep_review_threadsafe)
                result.deals_deep_reviewed = review_result.get("reviewed", 0)
                result.deep_review_errors = review_result.get("errors", 0)
                logger.info(
                    "Stage 5 complete: %d deals reviewed, %d errors",
                    result.deals_deep_reviewed, result.deep_review_errors,
                )
                for dr in review_result.get("results", []):
                    if "error" in dr:
                        result.errors.append(
                            f"Deep review failed for deal {dr.get('dealId', '?')}: {dr['error']}"
                        )
            except Exception as exc:
                error = f"Stage 5 (deep-review) failed: {exc}"
                logger.error(error, exc_info=True)
                result.errors.append(error)
        else:
            logger.info("[Stage 5/5] Skipping Deep Review (run_ai_analysis=False)")

    except Exception as exc:
        error = f"Pipeline fatal error: {exc}"
        logger.error(error, exc_info=True)
        result.errors.append(error)
        pipeline_failed = True

    finally:
        result.finished_at = datetime.now(timezone.utc).isoformat()

        if result.errors:
            pipeline_failed = True

        # Persist final job state (fresh session — stage 1-3 session was closed)
        if job is not None:
            finalize_db = _get_db_session()
            try:
                from app.domains.credit.modules.ai.ingest_job_model import PipelineIngestJob
                from sqlalchemy import select as sa_select

                refreshed_job = finalize_db.execute(
                    sa_select(PipelineIngestJob).where(PipelineIngestJob.id == job.id)
                ).scalar_one()
                _finalise_job(finalize_db, refreshed_job, result=result, failed=pipeline_failed)
                logger.info(
                    "PipelineIngestJob %s finalised: status=%s",
                    job.id, "FAILED" if pipeline_failed else "COMPLETED",
                )
            except Exception:
                logger.error("Could not finalise PipelineIngestJob %s", job.id, exc_info=True)
            finally:
                finalize_db.close()

    logger.info(
        "Async full pipeline ingest complete: scanned=%d, deals=%d (new=%d), bridged=%d, "
        "ingested=%d, failed=%d, chunks=%d, analyzed=%d, deep_reviewed=%d, errors=%d",
        result.documents_scanned, result.deals_discovered, result.new_deals_detected,
        result.documents_bridged,
        result.documents_ingested, result.documents_failed, result.chunks_upserted,
        result.deals_analyzed, result.deals_deep_reviewed, len(result.errors),
    )
    return result


# ── CLI entrypoint ────────────────────────────────────────────────────


def main() -> None:
    """CLI: python -m ai_engine.ingestion.pipeline_ingest_runner --fund-id <UUID>"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Canonical Pipeline Ingest Runner")
    parser.add_argument("--fund-id", type=str, required=True, help="Fund UUID to process")
    parser.add_argument("--deal-ids", type=str, default="", help="Comma-separated deal UUIDs (empty = all deals)")
    parser.add_argument("--batch-size", type=int, default=50, help="Max documents per ingest batch")
    parser.add_argument("--skip-ai", action="store_true", help="Skip AI analysis after ingestion")

    args = parser.parse_args()

    try:
        fund_id = uuid.UUID(args.fund_id)
    except ValueError:
        print(f"Invalid UUID: {args.fund_id}", file=sys.stderr)
        sys.exit(1)

    deal_ids: list[uuid.UUID] | None = None
    if args.deal_ids:
        try:
            deal_ids = [uuid.UUID(d.strip()) for d in args.deal_ids.split(",") if d.strip()]
        except ValueError as e:
            print(f"Invalid deal UUID: {e}", file=sys.stderr)
            sys.exit(1)

    result = run_full_pipeline_ingest(
        fund_id,
        deal_ids=deal_ids,
        batch_size=args.batch_size,
        run_ai_analysis=not args.skip_ai,
    )

    print(f"\n{'='*60}")
    print("  PIPELINE INGEST SUMMARY")
    print(f"  {'─'*56}")
    print(f"  Documents scanned:    {result.documents_scanned}")
    print(f"  Deals discovered:     {result.deals_discovered}")
    print(f"  New deals detected:   {result.new_deals_detected}")
    print(f"  Documents bridged:    {result.documents_bridged}")
    print(f"  Documents ingested:   {result.documents_ingested}")
    print(f"  Documents failed:     {result.documents_failed}")
    print(f"  Chunks upserted:      {result.chunks_upserted}")
    print(f"  Deals analyzed:       {result.deals_analyzed}")
    print(f"  Deals deep-reviewed:  {result.deals_deep_reviewed}")
    print(f"  Deep review errors:   {result.deep_review_errors}")
    print(f"  Started:              {result.started_at}")
    print(f"  Finished:             {result.finished_at}")
    if result.errors:
        print(f"\n  Errors ({len(result.errors)}):")
        for err in result.errors:
            print(f"    - {err}")
    print(f"{'='*60}\n")

    # Exit 1 only on deep review errors — document parse failures are non-fatal.
    sys.exit(1 if result.deep_review_errors > 0 else 0)


if __name__ == "__main__":
    main()
