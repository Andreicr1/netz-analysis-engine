"""AI-Assisted Document Review Analyzer.

For each checklist item, performs semantic search against the document's
indexed chunks, then uses an LLM to determine whether the item is
satisfied by the document content.

Returns structured findings: FOUND / NOT_FOUND / UNCLEAR with confidence,
excerpt, and source chunk reference.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.credit.documents.models.review import DocumentReview, ReviewChecklistItem

logger = logging.getLogger(__name__)

def _get_system_prompt() -> str:
    try:
        from ai_engine.prompts import prompt_registry
        return prompt_registry.render("services/doc_review_system.j2")
    except Exception:
        logger.warning("Failed to load doc_review_system.j2 — using inline fallback")
        return (
            "You are a senior legal document reviewer at an institutional private credit fund.\n"
            "Analyze excerpts and determine whether a checklist item is satisfied.\n"
            "Respond in JSON: {status, confidence, excerpt, reasoning}."
        )


async def analyze_review_checklist(
    db: AsyncSession,
    *,
    review: DocumentReview,
    fund_id: uuid.UUID,
    organization_id: uuid.UUID | str | None = None,
) -> dict[str, Any]:
    """Run AI analysis on all checklist items for a document review.

    Returns summary stats and updates each ReviewChecklistItem.ai_finding in-place.
    """
    result = await db.execute(
        select(ReviewChecklistItem)
        .where(ReviewChecklistItem.review_id == review.id)
        .order_by(ReviewChecklistItem.sort_order),
    )
    items = list(result.scalars().all())

    if not items:
        return {"analyzed": 0, "found": 0, "notFound": 0, "unclear": 0, "errors": 0}

    model = _get_model()

    stats = {"analyzed": 0, "found": 0, "notFound": 0, "unclear": 0, "errors": 0}
    now_iso = datetime.now(UTC).isoformat()

    for item in items:
        try:
            chunks = await _search_for_item(db, fund_id, organization_id, item)
            finding = _analyze_item_with_llm(model, item, chunks)
            finding["model"] = model
            finding["analyzed_at"] = now_iso
            if chunks:
                finding["source_chunk_id"] = chunks[0].get("chunk_id", "")

            item.ai_finding = finding
            stats["analyzed"] += 1
            status = finding.get("status", "UNCLEAR")
            if status == "FOUND":
                stats["found"] += 1
            elif status == "NOT_FOUND":
                stats["notFound"] += 1
            else:
                stats["unclear"] += 1

        except Exception:
            logger.warning("AI analysis failed for checklist item %s", item.id, exc_info=True)
            item.ai_finding = {
                "status": "ERROR",
                "confidence": 0,
                "excerpt": "",
                "reasoning": "AI analysis failed — manual verification required",
                "model": model,
                "analyzed_at": now_iso,
            }
            stats["errors"] += 1

    await db.flush()
    return stats


def _get_model() -> str:
    """Resolve the model for document review analysis."""
    from ai_engine.model_config import get_model
    return get_model("doc_review")


async def _search_for_item(
    db: AsyncSession,
    fund_id: uuid.UUID,
    organization_id: uuid.UUID | str | None,
    item: ReviewChecklistItem,
) -> list[dict[str, Any]]:
    """Semantic search for chunks relevant to a checklist item."""
    if not organization_id:
        return []

    query = f"{item.category}: {item.label}"
    if item.description:
        query += f" — {item.description}"

    try:
        from ai_engine.extraction.embedding_service import generate_embeddings
        from ai_engine.extraction.pgvector_search_service import search_and_rerank_fund_policy

        emb = generate_embeddings([query])
        query_vector = emb.vectors[0] if emb.vectors else None

        result = await search_and_rerank_fund_policy(
            db,
            fund_id=fund_id,
            organization_id=str(organization_id),
            query_text=query,
            query_vector=query_vector,
            top=5,
            candidates=20,
        )
        results = []
        for chunk in result.chunks[:5]:
            results.append({
                "chunk_id": chunk.get("id", ""),
                "text": chunk.get("content", ""),
                "score": chunk.get("reranker_score") or chunk.get("score", 0),
                "document_title": chunk.get("title", ""),
            })
        return results
    except Exception:
        logger.warning("Search failed for checklist item: %s", item.label, exc_info=True)
        return []


def _analyze_item_with_llm(
    model: str,
    item: ReviewChecklistItem,
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Use LLM to analyze whether chunks satisfy the checklist item."""
    if not chunks:
        return {
            "status": "NOT_FOUND",
            "confidence": 50,
            "excerpt": "",
            "reasoning": "No document content was retrieved for analysis. Manual verification required.",
        }

    try:
        from ai_engine.prompts import prompt_registry
        user_prompt = prompt_registry.render(
            "services/doc_review_user.j2",
            category=item.category or "General",
            label=item.label,
            description=item.description or "N/A",
            chunks=chunks[:5],
        )
    except Exception:
        user_prompt = (
            f"CHECKLIST ITEM:\nCategory: {item.category or 'General'}\n"
            f"Item: {item.label}\nDescription: {item.description or 'N/A'}\n\n"
            f"DOCUMENT EXCERPTS:\n" + "\n\n".join(
                f"[Excerpt {i+1}]:\n{c['text'][:800]}" for i, c in enumerate(chunks[:5])
            )
        )

    try:
        from ai_engine.openai_client import create_completion

        result = create_completion(
            system_prompt=_get_system_prompt(),
            user_prompt=user_prompt,
            model=model,
            temperature=0.1,
            max_tokens=512,
            response_format={"type": "json_object"},
            stage="doc_review",
        )

        parsed = json.loads(result.text)

        status = parsed.get("status", "UNCLEAR")
        if status not in ("FOUND", "NOT_FOUND", "UNCLEAR"):
            status = "UNCLEAR"

        confidence = parsed.get("confidence", 50)
        if not isinstance(confidence, (int, float)):
            confidence = 50
        confidence = max(0, min(100, int(confidence)))

        return {
            "status": status,
            "confidence": confidence,
            "excerpt": str(parsed.get("excerpt", ""))[:300],
            "reasoning": str(parsed.get("reasoning", ""))[:500],
        }

    except Exception:
        logger.warning("LLM analysis failed for item: %s", item.label, exc_info=True)
        return _heuristic_fallback(item, chunks)


def _heuristic_fallback(
    item: ReviewChecklistItem,
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Keyword-based fallback when LLM is unavailable."""
    keywords = item.label.lower().split()
    best_match = ""
    best_score = 0

    for chunk in chunks:
        text_lower = chunk["text"].lower()
        matches = sum(1 for kw in keywords if kw in text_lower and len(kw) > 3)
        score = matches / max(len(keywords), 1)
        if score > best_score:
            best_score = score
            best_match = chunk["text"][:300]

    if best_score >= 0.5:
        return {
            "status": "FOUND",
            "confidence": int(best_score * 70),
            "excerpt": best_match,
            "reasoning": "Heuristic keyword match (LLM unavailable)",
        }
    if best_score >= 0.2:
        return {
            "status": "UNCLEAR",
            "confidence": int(best_score * 50),
            "excerpt": best_match,
            "reasoning": "Partial keyword match (LLM unavailable)",
        }
    return {
        "status": "NOT_FOUND",
        "confidence": 40,
        "excerpt": "",
        "reasoning": "No keyword matches found (LLM unavailable)",
    }
