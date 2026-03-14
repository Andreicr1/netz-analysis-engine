"""
deals_enrichment.py
====================
Per-chunk LLM enrichment for the *deals* pipeline source.

Extracts five structured fields from each eligible chunk using gpt-4.1-mini:
  • borrower_sector         — primary sector of the borrower / fund target
  • loan_structure          — type of loan instrument discussed
  • key_persons_mentioned   — list of real names explicitly present
  • financial_metric_type   — primary financial metric discussed
  • risk_flags              — list of risk topics detected

Only chunks whose doc_type is in DEALS_ENRICHMENT_DOC_TYPES are sent to the
LLM.  All other chunks receive null / [] defaults so the index schema is
satisfied and no ShaperSkill warning fires for missing fields.

Follows the exact pattern of enrich_benchmark_chunks() in market_data_bootstrap.py:
  • JSON mode, temperature=0
  • Cache by chunk_id to avoid re-enriching on re-runs
  • Error handling: log & continue, never abort the batch
  • Summary line: "N enriched, N cache hits, N errors"

Usage (from pipeline_azure.py Stage B.5):
    from deals_enrichment import enrich_deals_chunks
    chunks = enrich_deals_chunks(chunks, gpt_client, cache_path=item_dir / "deals_enrichment_cache.json")
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ai_engine.model_config import get_model
from ai_engine.openai_client import create_completion
from ai_engine.prompts import prompt_registry

logger = logging.getLogger(__name__)

# ── Eligible doc_types ────────────────────────────────────────────────────────

DEALS_ENRICHMENT_DOC_TYPES: frozenset[str] = frozenset({
    "fund_presentation",
    "fund_profile",
    "fund_policy",
    "credit_policy",
    "financial_statements",
    "financial_projections",
    "legal_lpa",
    "legal_subscription",
    "strategy_profile",
    "investment_memo",
    "risk_assessment",
    "capital_raising",
})

# Doc types that should be SKIPPED (for documentation clarity):
#   legal_agreement, legal_amendment, legal_poa, legal_security,
#   legal_intercreditor, legal_credit_agreement, regulatory_compliance,
#   regulatory_qdd, operational_service, attachment, org_chart, other

# ── Enrichment fields ─────────────────────────────────────────────────────────

DEALS_ENRICHMENT_FIELDS: list[str] = [
    "borrower_sector",
    "loan_structure",
    "key_persons_mentioned",
    "financial_metric_type",
    "risk_flags",
]

# Defaults when a chunk is not enriched (keeps the index schema satisfied)
DEALS_ENRICHMENT_DEFAULTS: dict[str, Any] = {
    "borrower_sector":       None,
    "loan_structure":        None,
    "key_persons_mentioned": [],
    "financial_metric_type": None,
    "risk_flags":            [],
}

# ── Main function ─────────────────────────────────────────────────────────────

def enrich_deals_chunks(
    chunks: list[dict],
    openai_client: Any = None,   # deprecated — ignored, kept for call-site compat
    *,
    model: str | None = None,
    max_tokens: int = 400,
    cache_path: Path | None = None,
) -> list[dict]:
    """
    Per-chunk LLM enrichment for deals source.

    Extracts: borrower_sector, loan_structure, key_persons_mentioned,
              financial_metric_type, risk_flags

    Only runs on chunks where doc_type is in DEALS_ENRICHMENT_DOC_TYPES.
    Chunks outside the eligible set receive null / [] defaults.

    Parameters
    ----------
    chunks        : list of chunk dicts (from cu_chunks.json)
    openai_client : deprecated — ignored (uses centralized create_completion)
    model         : LLM model id (default via get_model("extraction"))
    max_tokens    : max output tokens per call
    cache_path    : optional Path to a JSON file used as enrichment cache;
                    if provided, already-enriched chunk_ids are not re-sent

    Returns
    -------
    list[dict] — same chunks with enrichment fields populated
    """
    # ── Load enrichment cache ─────────────────────────────────────────────
    cache: dict[str, dict] = {}
    if cache_path and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    # ── Initialize defaults on ALL chunks (schema satisfaction) ──────────
    for chunk in chunks:
        for field, default in DEALS_ENRICHMENT_DEFAULTS.items():
            if field not in chunk:
                chunk[field] = default

    # ── Identify eligible chunks ──────────────────────────────────────────
    target_chunks = [
        c for c in chunks
        if c.get("doc_type") in DEALS_ENRICHMENT_DOC_TYPES
    ]

    model = model or get_model("extraction")

    if not target_chunks:
        logger.info("[deals_enrich] No eligible chunks — skipping enrichment.")
        return chunks

    logger.info(
        "[deals_enrich] Enriching %d / %d chunks with %s",
        len(target_chunks), len(chunks), model,
    )

    enriched_count = 0
    cache_hits     = 0
    errors         = 0

    # ── Separate cache hits from LLM-needed chunks ────────────────────
    llm_chunks: list[dict] = []
    for chunk in target_chunks:
        chunk_id = chunk.get("chunk_id", "")
        if chunk_id in cache:
            chunk.update(cache[chunk_id])
            cache_hits += 1
        else:
            llm_chunks.append(chunk)

    # ── Parallel LLM enrichment ───────────────────────────────────────
    def _enrich_one(chunk: dict) -> tuple[str, dict[str, Any] | None]:
        chunk_id = chunk.get("chunk_id", "")
        content = chunk.get("content", "")[:2000]
        try:
            user_prompt = prompt_registry.render(
                "extraction/deals_enrichment.j2",
                content=content,
            )
            result = create_completion(
                system_prompt="You are a financial analyst specializing in private credit document extraction.",
                user_prompt=user_prompt,
                model=model,
                temperature=0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            extracted: dict[str, Any] = json.loads(result.text or "{}")
            updates: dict[str, Any] = {}
            for field in ("borrower_sector", "loan_structure", "financial_metric_type"):
                val = extracted.get(field)
                updates[field] = val if (val and val != "null") else None
            for field in ("key_persons_mentioned", "risk_flags"):
                val = extracted.get(field)
                if isinstance(val, list):
                    updates[field] = [str(v).strip() for v in val if v and str(v).strip()]
                else:
                    updates[field] = []
            return chunk_id, updates
        except Exception as e:
            logger.warning("chunk_id=%r: %s", chunk_id, e)
            return chunk_id, None

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_chunk = {executor.submit(_enrich_one, c): c for c in llm_chunks}
        for future in as_completed(future_to_chunk):
            chunk = future_to_chunk[future]
            chunk_id, updates = future.result()
            if updates is not None:
                chunk.update(updates)
                cache[chunk_id] = updates
                enriched_count += 1
            else:
                errors += 1

    # ── Save updated cache ────────────────────────────────────────────────
    if cache_path:
        try:
            cache_path.write_text(
                json.dumps(cache, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Cache write failed: %s", e)

    logger.info(
        "Done — %d enriched, %d cache hits, %d errors.",
        enriched_count, cache_hits, errors,
    )
    return chunks


# ── Async per-chunk enrichment ──────────────────────────────────────────────


async def async_enrich_chunk(
    chunk_content: str,
    doc_type: str,
    *,
    model: str | None = None,
    max_tokens: int = 400,
    fund_context: object | None = None,
) -> dict[str, Any]:
    """Async enrichment of a single chunk. Returns enrichment fields dict.

    Only enriches chunks with eligible doc_types. Returns defaults for others.
    Used by the async ingestion pipeline for per-chunk enrichment.

    When fund_context (FundContext) is provided, seeds the prompt with fund
    strategy and known roles for improved borrower_sector and key_persons
    extraction.
    """
    if doc_type not in DEALS_ENRICHMENT_DOC_TYPES:
        return dict(DEALS_ENRICHMENT_DEFAULTS)

    model = model or get_model("extraction")

    try:
        from ai_engine.openai_client import async_create_completion

        # Build enriched content with fund context hints
        enriched_content = chunk_content[:2000]
        if fund_context:
            context_parts: list[str] = []
            if hasattr(fund_context, "fund_strategy") and fund_context.fund_strategy:
                context_parts.append(
                    f"Fund strategy: {', '.join(fund_context.fund_strategy)}"
                )
            if hasattr(fund_context, "roles") and fund_context.roles:
                known_persons = ", ".join(fund_context.roles.keys())
                context_parts.append(f"Known fund persons: {known_persons}")
            if context_parts:
                enriched_content = (
                    f"[{'; '.join(context_parts)}]\n\n{enriched_content}"
                )

        user_prompt = prompt_registry.render(
            "extraction/deals_enrichment.j2",
            content=enriched_content,
        )
        result = await async_create_completion(
            system_prompt="You are a financial analyst specializing in private credit document extraction.",
            user_prompt=user_prompt,
            model=model,
            temperature=0,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        extracted: dict[str, Any] = json.loads(result.text or "{}")

        updates: dict[str, Any] = {}
        for field_name in ("borrower_sector", "loan_structure", "financial_metric_type"):
            val = extracted.get(field_name)
            updates[field_name] = val if (val and val != "null") else None
        for field_name in ("key_persons_mentioned", "risk_flags"):
            val = extracted.get(field_name)
            if isinstance(val, list):
                updates[field_name] = [str(v).strip() for v in val if v and str(v).strip()]
            else:
                updates[field_name] = []
        return updates

    except Exception as exc:
        logger.warning("async_enrich_chunk failed (doc_type=%s): %s", doc_type, exc)
        return dict(DEALS_ENRICHMENT_DEFAULTS)


async def async_enrich_chunks(
    chunks: list[dict],
    doc_type: str,
    *,
    model: str | None = None,
    max_concurrent: int = 5,
    fund_context: object | None = None,
) -> list[dict]:
    """Async enrichment of multiple chunks with concurrency control.

    Returns the same chunks with enrichment fields populated.
    When fund_context is provided, seeds each chunk enrichment with fund
    strategy and known roles for improved extraction.
    """
    import asyncio

    sem = asyncio.Semaphore(max_concurrent)

    async def _bounded_enrich(chunk: dict) -> None:
        async with sem:
            enrichment = await async_enrich_chunk(
                chunk.get("content", ""),
                doc_type,
                model=model,
                fund_context=fund_context,
            )
            chunk.update(enrichment)

    # Initialize defaults on all chunks first
    for chunk in chunks:
        for field_name, default in DEALS_ENRICHMENT_DEFAULTS.items():
            if field_name not in chunk:
                chunk[field_name] = default

    tasks = [_bounded_enrich(c) for c in chunks]
    await asyncio.gather(*tasks)

    enriched_count = sum(
        1 for c in chunks if c.get("borrower_sector") is not None
    )
    logger.info(
        "[async_deals_enrich] %d/%d chunks enriched (doc_type=%s)",
        enriched_count, len(chunks), doc_type,
    )
    return chunks
