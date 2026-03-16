"""DD Report Engine — orchestrator for 8-chapter fund DD reports.

Generates chapters 1-7 in parallel (TaskGroup + Semaphore), then chapter 8
(Recommendation) sequentially. Implements resume safety, layered timeouts,
and the never-raises contract.

Architecture mirrors credit's memo_book_generator but with:
- Frozen dataclass evidence pack (not dict)
- TaskGroup structured concurrency (not asyncio.gather)
- Direct organization_id on chapters for independent RLS

Usage (from async route via asyncio.to_thread)::

    engine = DDReportEngine(config=config, call_openai_fn=call_fn)
    result = engine.generate(db, instrument_id=fund_id, actor_id=actor_id)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
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
            evidence = self._build_evidence(db, fund_id=instrument_id)

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
    ) -> EvidencePack:
        """Gather all evidence for the fund."""
        from app.domains.wealth.models.fund import Fund

        fund = db.query(Fund).filter(Fund.fund_id == fund_id).first()
        if not fund:
            logger.warning("fund_not_found", fund_id=fund_id)
            return EvidencePack()

        fund_data = {
            "instrument_id": str(fund.fund_id),
            "name": fund.name,
            "isin": fund.isin,
            "ticker": fund.ticker,
            "fund_type": fund.fund_type,
            "geography": fund.geography,
            "asset_class": fund.asset_class,
            "manager_name": fund.manager_name,
            "currency": fund.currency,
            "domicile": fund.domicile,
            "inception_date": fund.inception_date,
            "aum_usd": fund.aum_usd,
        }

        quant_profile = gather_quant_metrics(db, instrument_id=fund_id)
        risk_metrics = gather_risk_metrics(db, instrument_id=fund_id)

        return build_evidence_pack(
            fund_data=fund_data,
            quant_profile=quant_profile,
            risk_metrics=risk_metrics,
        )

    def _generate_all_chapters(
        self,
        *,
        evidence: EvidencePack,
        existing_chapters: dict[str, str],
        force: bool,
    ) -> list[ChapterResult]:
        """Generate all 8 chapters: 1-7 sequentially, then 8.

        Note: Parallel generation via TaskGroup happens at the async
        layer (route handler). This sync method generates sequentially
        since it runs inside asyncio.to_thread(). The async route
        can dispatch multiple chapter calls in parallel via TaskGroup
        if needed.
        """
        assert self._call_openai_fn is not None

        chapters: list[ChapterResult] = []
        chapter_summaries: dict[str, str] = {}

        # Phase A: Chapters 1-7
        for ch_def in CHAPTER_REGISTRY:
            if ch_def["tag"] == SEQUENTIAL_CHAPTER_TAG:
                continue  # Skip recommendation for now

            # Resume safety: skip cached chapters
            if not force and ch_def["tag"] in existing_chapters:
                cached_content = existing_chapters[ch_def["tag"]]
                chapters.append(ChapterResult(
                    tag=ch_def["tag"],
                    order=ch_def["order"],
                    title=ch_def["title"],
                    content_md=cached_content,
                    status="completed",
                    critic_status="accepted",
                ))
                # Add to summaries for recommendation
                chapter_summaries[ch_def["tag"]] = cached_content[:500]
                logger.info("chapter_cached", chapter_tag=ch_def["tag"])
                continue

            evidence_context = evidence.filter_for_chapter(ch_def["tag"])
            result = generate_chapter(
                self._call_openai_fn,
                chapter_tag=ch_def["tag"],
                evidence_context=evidence_context,
            )
            chapters.append(result)

            # Track summary for recommendation chapter
            if result.content_md:
                chapter_summaries[result.tag] = result.content_md[:500]

        # Phase B: Chapter 8 (Recommendation) — sequential
        completed_count = sum(
            1 for ch in chapters if ch.content_md and ch.status == "completed"
        )

        if completed_count >= MIN_CHAPTERS_FOR_RECOMMENDATION:
            # Check cache
            if not force and SEQUENTIAL_CHAPTER_TAG in existing_chapters:
                cached_content = existing_chapters[SEQUENTIAL_CHAPTER_TAG]
                chapters.append(ChapterResult(
                    tag=SEQUENTIAL_CHAPTER_TAG,
                    order=8,
                    title="Recommendation",
                    content_md=cached_content,
                    status="completed",
                    critic_status="accepted",
                ))
            else:
                evidence_context = evidence.filter_for_chapter(SEQUENTIAL_CHAPTER_TAG)
                evidence_context["chapter_summaries"] = chapter_summaries
                rec_result = generate_chapter(
                    self._call_openai_fn,
                    chapter_tag=SEQUENTIAL_CHAPTER_TAG,
                    evidence_context=evidence_context,
                    chapter_summaries=chapter_summaries,
                )
                chapters.append(rec_result)
        else:
            logger.warning(
                "insufficient_chapters_for_recommendation",
                completed=completed_count,
                required=MIN_CHAPTERS_FOR_RECOMMENDATION,
            )
            chapters.append(ChapterResult(
                tag=SEQUENTIAL_CHAPTER_TAG,
                order=8,
                title="Recommendation",
                content_md=None,
                status="skipped",
                error=f"Only {completed_count}/{MIN_CHAPTERS_FOR_RECOMMENDATION} prerequisite chapters completed",
            ))

        # Sort by order
        chapters.sort(key=lambda ch: ch.order)
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

        # Batch persist chapters
        now = datetime.now(timezone.utc)
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
