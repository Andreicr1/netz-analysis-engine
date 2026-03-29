"""DD Report Engine — orchestrator for 8-chapter fund DD reports.

Chapters 1-7 run in parallel via ThreadPoolExecutor(max_workers=5),
then chapter 8 (Recommendation) runs sequentially consuming summaries
from the preceding chapters. This engine runs inside asyncio.to_thread()
on a sync Session.

Chapter generation mode: PARALLEL (1-7) + SEQUENTIAL (8)
- Chapters 1-7 dispatched to ThreadPoolExecutor(5) — share only frozen EvidencePack.
- Chapter 8 (Recommendation) generated after 1-7 complete.
- Resume safety: cached chapters are skipped when force=False.
- Never raises — returns DDReportResult with status='failed' on error.

Architecture:
- Frozen dataclass evidence pack (EvidencePack) — safe to cross thread boundary
- Sync SQLAlchemy Session — must be created inside the worker thread
- Direct organization_id on chapters for independent RLS

Usage (from async route via asyncio.to_thread)::

    engine = DDReportEngine(config=config, call_openai_fn=call_fn)
    result = engine.generate(db, instrument_id=fund_id, actor_id=actor_id)
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.orm import Session

from vertical_engines.wealth.dd_report.chapters import generate_chapter
from vertical_engines.wealth.dd_report.confidence_scoring import (
    compute_confidence_score,
    derive_decision_anchor,
)
from vertical_engines.wealth.dd_report.evidence_pack import (
    EvidencePack,
    build_evidence_pack,
)
from vertical_engines.wealth.dd_report.models import (
    CHAPTER_REGISTRY,
    MIN_CHAPTERS_FOR_RECOMMENDATION,
    SEQUENTIAL_CHAPTER_TAG,
    ChapterResult,
    DDReportResult,
)
from vertical_engines.wealth.dd_report.quant_injection import (
    gather_quant_metrics,
    gather_risk_metrics,
)
from vertical_engines.wealth.dd_report.sec_injection import (
    gather_fund_enrichment,
    gather_sec_13f_data,
    gather_sec_adv_brochure,
    gather_sec_adv_data,
    gather_sec_nport_data,
)
from vertical_engines.wealth.shared_protocols import CallOpenAiFn

logger = structlog.get_logger()

# Default concurrency for parallel chapter generation
_DEFAULT_LLM_CONCURRENCY = 5


class DDReportEngine:
    """Orchestrates wealth DD report generation.

    Never raises — returns DDReportResult with status='failed' on error.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        call_openai_fn: CallOpenAiFn | None = None,
    ) -> None:
        self._config = config or {}
        self._call_openai_fn = call_openai_fn

    def generate(
        self,
        db: Session,
        *,
        instrument_id: str,
        actor_id: str,
        organization_id: str,
        force: bool = False,
    ) -> DDReportResult:
        """Generate a complete 8-chapter DD report (sync).

        This method is designed to run inside asyncio.to_thread().
        The caller must create a sync Session factory inside the thread.

        Parameters
        ----------
        db : Session
            Sync database session (created inside thread).
        instrument_id : str
            Target fund being evaluated.
        actor_id : str
            User triggering the generation.
        organization_id : str
            Tenant organization ID.
        force : bool
            Re-generate even if cached chapters exist.

        Returns
        -------
        DDReportResult
            Complete report result (frozen dataclass, safe to cross
            back to async context).

        """
        logger.info(
            "dd_report_generation_started",
            instrument_id=instrument_id,
            actor_id=actor_id,
            organization_id=organization_id,
        )

        if not self._call_openai_fn:
            return DDReportResult(
                fund_id=instrument_id,
                chapters=[],
                confidence_score=0.0,
                decision_anchor=None,
                status="failed",
                error="No LLM call function provided",
            )

        try:
            # 1. Create or load DD Report record
            report_id, existing_chapters = self._ensure_report_record(
                db,
                fund_id=instrument_id,
                actor_id=actor_id,
                organization_id=organization_id,
            )

            # 2. Gather evidence
            evidence = self._build_evidence(db, fund_id=instrument_id, organization_id=organization_id)

            # 3. Generate chapters (parallel 1-7, sequential 8)
            chapters = self._generate_all_chapters(
                evidence=evidence,
                existing_chapters=existing_chapters,
                force=force,
            )

            # 4. Compute confidence score
            confidence = compute_confidence_score(
                chapters,
                evidence_refs=evidence.to_context(),
                quant_profile=evidence.quant_profile,
            )

            # 5. Derive decision anchor
            anchor = derive_decision_anchor(confidence, chapters)

            # 6. Persist chapters and update report
            self._persist_results(
                db,
                report_id=report_id,
                organization_id=organization_id,
                chapters=chapters,
                confidence_score=confidence,
                decision_anchor=anchor,
            )

            status = "completed" if all(
                ch.status == "completed" for ch in chapters
            ) else "partial"

            logger.info(
                "dd_report_generation_completed",
                instrument_id=instrument_id,
                report_id=str(report_id),
                status=status,
                confidence=confidence,
                anchor=anchor,
            )

            return DDReportResult(
                fund_id=instrument_id,
                chapters=chapters,
                confidence_score=confidence,
                decision_anchor=anchor,
                status=status,
            )

        except Exception as exc:
            logger.exception("dd_report_generation_failed", instrument_id=instrument_id)
            return DDReportResult(
                fund_id=instrument_id,
                chapters=[],
                confidence_score=0.0,
                decision_anchor=None,
                status="failed",
                error=str(exc),
            )

    def _ensure_report_record(
        self,
        db: Session,
        *,
        fund_id: str,
        actor_id: str,
        organization_id: str,
    ) -> tuple[uuid.UUID, dict[str, str]]:
        """Create or load the DD Report DB record.

        Returns (report_id, existing_chapters) where existing_chapters
        maps chapter_tag → content_md for resume safety.
        """
        from app.domains.wealth.models.dd_report import DDChapter, DDReport

        # Check for existing current report
        existing = (
            db.query(DDReport)
            .filter(
                DDReport.instrument_id == fund_id,
                DDReport.organization_id == organization_id,
                DDReport.is_current.is_(True),
            )
            .first()
        )

        if existing:
            # Load cached chapters for resume safety
            cached = (
                db.query(DDChapter)
                .filter(DDChapter.dd_report_id == existing.id)
                .all()
            )
            existing_chapters = {
                ch.chapter_tag: ch.content_md
                for ch in cached
                if ch.content_md
            }
            # Update status
            existing.status = "generating"
            db.flush()
            return existing.id, existing_chapters

        # Determine version
        max_version = (
            db.query(DDReport.version)
            .filter(
                DDReport.instrument_id == fund_id,
                DDReport.organization_id == organization_id,
            )
            .order_by(DDReport.version.desc())
            .first()
        )
        next_version = (max_version[0] + 1) if max_version else 1

        # Mark previous as not current
        db.query(DDReport).filter(
            DDReport.instrument_id == fund_id,
            DDReport.organization_id == organization_id,
            DDReport.is_current.is_(True),
        ).update({"is_current": False})

        report = DDReport(
            instrument_id=fund_id,
            organization_id=organization_id,
            version=next_version,
            status="generating",
            is_current=True,
            config_snapshot=self._config,
            created_by=actor_id,
        )
        db.add(report)
        db.flush()

        return report.id, {}

    def _build_evidence(
        self,
        db: Session,
        *,
        fund_id: str,
        organization_id: str,
    ) -> EvidencePack:
        """Gather all evidence for the fund.

        Uses Instrument model (instruments_universe) with JSONB attributes
        for SEC linkage. Branches on sec_universe to resolve N-PORT
        (fund-level) vs 13F (firm-level overlay) holdings.
        """
        from app.domains.wealth.models.instrument import Instrument
        from app.domains.wealth.models.instrument_org import InstrumentOrg

        instrument = (
            db.query(Instrument)
            .join(InstrumentOrg, InstrumentOrg.instrument_id == Instrument.instrument_id)
            .filter(
                Instrument.instrument_id == fund_id,
                InstrumentOrg.organization_id == organization_id,
            )
            .first()
        )
        if not instrument:
            logger.warning("instrument_not_found", fund_id=fund_id)
            return EvidencePack()

        attrs = instrument.attributes or {}

        fund_data = {
            "instrument_id": str(instrument.instrument_id),
            "name": instrument.name,
            "isin": instrument.isin,
            "ticker": instrument.ticker,
            "fund_type": attrs.get("fund_type") or instrument.asset_class,
            "geography": instrument.geography,
            "asset_class": instrument.asset_class,
            "manager_name": attrs.get("manager_name"),
            "currency": instrument.currency,
            "domicile": attrs.get("domicile"),
            "inception_date": attrs.get("inception_date"),
            "aum_usd": attrs.get("aum_usd"),
        }

        # SEC linkage from JSONB attributes
        fund_cik = attrs.get("sec_cik")
        sec_universe = attrs.get("sec_universe")
        manager_name = attrs.get("manager_name")

        # ── Parallel evidence gathering ───────────────────────────────
        def _run_quant() -> dict:
            return gather_quant_metrics(db, instrument_id=fund_id, organization_id=organization_id)

        def _run_risk() -> dict:
            return gather_risk_metrics(db, instrument_id=fund_id, organization_id=organization_id)

        def _run_nport() -> dict:
            if sec_universe == "registered_us" and fund_cik:
                return gather_sec_nport_data(db, fund_cik=fund_cik)
            return {}

        def _run_13f() -> dict:
            return gather_sec_13f_data(db, manager_name=manager_name)

        def _run_adv() -> dict:
            return gather_sec_adv_data(db, manager_name=manager_name)

        def _run_enrichment() -> dict:
            return gather_fund_enrichment(db, fund_cik=fund_cik, sec_universe=sec_universe)

        tasks = {
            "quant": _run_quant,
            "risk": _run_risk,
            "nport": _run_nport,
            "thirteenf": _run_13f,
            "adv": _run_adv,
            "enrichment": _run_enrichment,
        }

        results: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(fn): name for name, fn in tasks.items()}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    results[name] = future.result()
                except Exception:
                    logger.warning("evidence_gather_partial_failure", task=name, fund_id=fund_id)
                    results[name] = {}

        quant_profile = results["quant"]
        risk_metrics = results["risk"]
        sec_nport = results["nport"]
        sec_13f = results["thirteenf"]
        sec_adv = results["adv"]
        enrichment = results.get("enrichment", {})

        holdings_source: str | None = None
        if sec_nport:
            holdings_source = "nport"

        # ADV brochure depends on sec_adv result — must stay sequential
        adv_brochure = gather_sec_adv_brochure(db, sec_adv.get("crd_number"))

        # ── Vector search (firm context + org-scoped analysis) ────────
        from ai_engine.extraction.embedding_service import generate_embeddings
        from ai_engine.extraction.pgvector_search_service import (
            search_fund_analysis_sync,
            search_fund_firm_context_sync,
        )

        documents: list[dict] = []
        try:
            query_text = "investment philosophy strategy risk management"
            embed_result = generate_embeddings([query_text])
            if embed_result.vectors:
                qvec = embed_result.vectors[0]
                sec_crd = attrs.get("sec_crd") or (sec_adv.get("crd_number") if sec_adv else None)
                firm_chunks = search_fund_firm_context_sync(
                    query_vector=qvec,
                    sec_crd=sec_crd or None,
                    top=15,
                )
                analysis_chunks = search_fund_analysis_sync(
                    organization_id=organization_id,
                    query_vector=qvec,
                    instrument_id=fund_id,
                    top=10,
                )
                documents = firm_chunks + analysis_chunks
        except Exception:
            logger.warning("vector_search_failed_for_dd_report", fund_id=fund_id)
            documents = []

        return build_evidence_pack(
            fund_data=fund_data,
            documents=documents,
            quant_profile=quant_profile,
            risk_metrics=risk_metrics,
            sec_13f_data=sec_13f,
            sec_nport_data=sec_nport,
            sec_adv_data=sec_adv,
            adv_brochure_sections=adv_brochure,
            holdings_source=holdings_source,
            fund_enrichment=enrichment,
        )

    def _generate_all_chapters(
        self,
        *,
        evidence: EvidencePack,
        existing_chapters: dict[str, str],
        force: bool,
    ) -> list[ChapterResult]:
        """Generate all 8 chapters: 1-7 in parallel, then 8 sequentially.

        Chapters 1-7 are independent (share only the frozen EvidencePack)
        and run in a ThreadPoolExecutor(max_workers=5). Chapter 8
        (Recommendation) depends on summaries from 1-7.

        Each future is wrapped in try/except to honour the never-raises
        contract — a failed chapter returns status='failed' with a safe
        default, never killing the entire generation.
        """
        assert self._call_openai_fn is not None

        chapter_results: dict[str, ChapterResult] = {}
        chapter_summaries: dict[str, str] = {}

        # Separate parallel (1-7) and sequential (8) chapters
        parallel_defs = [
            ch for ch in CHAPTER_REGISTRY if ch["tag"] != SEQUENTIAL_CHAPTER_TAG
        ]

        # Identify which parallel chapters actually need generation
        to_generate: list[dict[str, Any]] = []
        for ch_def in parallel_defs:
            if not force and ch_def["tag"] in existing_chapters:
                cached_content = existing_chapters[ch_def["tag"]]
                chapter_results[ch_def["tag"]] = ChapterResult(
                    tag=ch_def["tag"],
                    order=ch_def["order"],
                    title=ch_def["title"],
                    content_md=cached_content,
                    status="completed",
                    critic_status="accepted",
                )
                chapter_summaries[ch_def["tag"]] = cached_content[:500]
                logger.info("chapter_cached", chapter_tag=ch_def["tag"])
            else:
                to_generate.append(ch_def)

        # Phase A: Chapters 1-7 in parallel via ThreadPoolExecutor
        if to_generate:
            with ThreadPoolExecutor(
                max_workers=_DEFAULT_LLM_CONCURRENCY,
            ) as pool:
                futures = {
                    pool.submit(
                        generate_chapter,
                        self._call_openai_fn,
                        chapter_tag=ch_def["tag"],
                        evidence_context=evidence.filter_for_chapter(ch_def["tag"]),
                        evidence_pack=evidence,
                    ): ch_def
                    for ch_def in to_generate
                }
                for future in as_completed(futures):
                    ch_def = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        logger.warning(
                            "chapter_generation_failed",
                            chapter_tag=ch_def["tag"],
                            error=str(exc),
                        )
                        result = ChapterResult(
                            tag=ch_def["tag"],
                            order=ch_def["order"],
                            title=ch_def["title"],
                            content_md=None,
                            status="failed",
                            error=str(exc),
                        )
                    chapter_results[ch_def["tag"]] = result
                    if result.content_md:
                        chapter_summaries[result.tag] = result.content_md[:500]

        # Phase B: Chapter 8 (Recommendation) — sequential
        completed_count = sum(
            1 for r in chapter_results.values()
            if r.content_md and r.status == "completed"
        )

        if completed_count >= MIN_CHAPTERS_FOR_RECOMMENDATION:
            # Check cache
            if not force and SEQUENTIAL_CHAPTER_TAG in existing_chapters:
                cached_content = existing_chapters[SEQUENTIAL_CHAPTER_TAG]
                chapter_results[SEQUENTIAL_CHAPTER_TAG] = ChapterResult(
                    tag=SEQUENTIAL_CHAPTER_TAG,
                    order=8,
                    title="Recommendation",
                    content_md=cached_content,
                    status="completed",
                    critic_status="accepted",
                )
            else:
                evidence_context = evidence.filter_for_chapter(SEQUENTIAL_CHAPTER_TAG)
                evidence_context["chapter_summaries"] = chapter_summaries
                try:
                    rec_result = generate_chapter(
                        self._call_openai_fn,
                        chapter_tag=SEQUENTIAL_CHAPTER_TAG,
                        evidence_context=evidence_context,
                        chapter_summaries=chapter_summaries,
                        evidence_pack=evidence,
                    )
                except Exception as exc:
                    logger.warning(
                        "recommendation_chapter_failed",
                        error=str(exc),
                    )
                    rec_result = ChapterResult(
                        tag=SEQUENTIAL_CHAPTER_TAG,
                        order=8,
                        title="Recommendation",
                        content_md=None,
                        status="failed",
                        error=str(exc),
                    )
                chapter_results[SEQUENTIAL_CHAPTER_TAG] = rec_result
        else:
            logger.warning(
                "insufficient_chapters_for_recommendation",
                completed=completed_count,
                required=MIN_CHAPTERS_FOR_RECOMMENDATION,
            )
            chapter_results[SEQUENTIAL_CHAPTER_TAG] = ChapterResult(
                tag=SEQUENTIAL_CHAPTER_TAG,
                order=8,
                title="Recommendation",
                content_md=None,
                status="skipped",
                error=f"Only {completed_count}/{MIN_CHAPTERS_FOR_RECOMMENDATION} prerequisite chapters completed",
            )

        # Sort by order
        chapters = sorted(chapter_results.values(), key=lambda ch: ch.order)
        return chapters

    def _persist_results(
        self,
        db: Session,
        *,
        report_id: uuid.UUID,
        organization_id: str,
        chapters: list[ChapterResult],
        confidence_score: float,
        decision_anchor: str | None,
    ) -> None:
        """Persist chapter results and update report status.

        Uses batch persistence (fix #48): one UPDATE + one add_all().
        """
        from app.domains.wealth.models.dd_report import DDChapter, DDReport

        # Update report
        report = db.query(DDReport).filter(DDReport.id == report_id).first()
        if report:
            completed = all(ch.status == "completed" for ch in chapters)
            report.status = "pending_approval" if completed else "draft"
            report.confidence_score = confidence_score
            report.decision_anchor = decision_anchor

        # Delete existing chapters before re-inserting (regeneration safety)
        db.query(DDChapter).filter(
            DDChapter.dd_report_id == report_id,
        ).delete(synchronize_session="fetch")
        db.flush()

        # Batch persist chapters
        now = datetime.now(UTC)
        chapter_models = []
        for ch in chapters:
            chapter_models.append(DDChapter(
                dd_report_id=report_id,
                organization_id=organization_id,
                chapter_tag=ch.tag,
                chapter_order=ch.order,
                content_md=ch.content_md,
                evidence_refs=ch.evidence_refs,
                quant_data=ch.quant_data,
                critic_iterations=ch.critic_iterations,
                critic_status=ch.critic_status,
                generated_at=now if ch.content_md else None,
            ))

        db.add_all(chapter_models)
        db.flush()

        logger.info(
            "chapters_persisted",
            report_id=str(report_id),
            count=len(chapter_models),
        )
