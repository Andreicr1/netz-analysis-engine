"""fund_data_enrichment.py
========================
Per-chunk LLM enrichment for the *fund-data* pipeline source.

Extracts four structured fields from each eligible chunk using gpt-4.1-mini:
  • clause_type      — legal clause category (redemption, gate, lock_up, …)
  • party_role       — primary party role discussed
  • obligation_type  — nature of the obligation (right, restriction, …)
  • applies_to       — entity the clause applies to (gp, lp, fund, manager, both)

Only chunks whose doc_type is in FUND_DATA_ENRICHMENT_DOC_TYPES are sent to
the LLM.  All other chunks receive null defaults so the index schema is
satisfied and no ShaperSkill warning fires for missing fields.

Follows the exact pattern of enrich_benchmark_chunks() in market_data_bootstrap.py:
  • JSON mode, temperature=0
  • Cache by chunk_id to avoid re-enriching on re-runs
  • Error handling: log & continue, never abort the batch
  • Summary line: "N enriched, N cache hits, N errors"

Usage (from pipeline_azure.py Stage B.5):
    from fund_data_enrichment import enrich_fund_data_chunks
    chunks = enrich_fund_data_chunks(
        chunks, gpt_client,
        cache_path=item_dir / "fund_data_enrichment_cache.json"
    )
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

FUND_DATA_ENRICHMENT_DOC_TYPES: frozenset[str] = frozenset({
    # Actual doc_types found in fund-data-index (migrated from legacy indexes)
    "general",
    "fund_constitution",
    "service_agreement",
    # Legacy taxonomy names (in case new docs are ingested with these types)
    "legal_lpa",
    "legal_agreement",
    "legal_amendment",
    "legal_side_letter",
    "legal_subscription",
    "fund_policy",
    "regulatory_cima",
    "regulatory_compliance",
})

# ── Enrichment fields ─────────────────────────────────────────────────────────

FUND_DATA_ENRICHMENT_FIELDS: list[str] = [
    "clause_type",
    "party_role",
    "obligation_type",
    "applies_to",
]

# Defaults when a chunk is not enriched (schema satisfaction)
FUND_DATA_ENRICHMENT_DEFAULTS: dict[str, Any] = {
    "clause_type":     None,
    "party_role":      None,
    "obligation_type": None,
    "applies_to":      None,
}

# ── Main function ─────────────────────────────────────────────────────────────

def enrich_fund_data_chunks(
    chunks: list[dict],
    openai_client: Any = None,   # deprecated — ignored, kept for call-site compat
    *,
    model: str | None = None,
    max_tokens: int = 150,
    cache_path: Path | None = None,
) -> list[dict]:
    """Per-chunk LLM enrichment for fund-data source.

    Extracts: clause_type, party_role, obligation_type, applies_to

    Only runs on chunks where doc_type is in FUND_DATA_ENRICHMENT_DOC_TYPES.
    Chunks outside the eligible set receive null defaults.

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
        for field, default in FUND_DATA_ENRICHMENT_DEFAULTS.items():
            if field not in chunk:
                chunk[field] = default

    # ── Identify eligible chunks ──────────────────────────────────────────
    target_chunks = [
        c for c in chunks
        if c.get("doc_type") in FUND_DATA_ENRICHMENT_DOC_TYPES
    ]

    model = model or get_model("extraction")

    if not target_chunks:
        logger.info("[fund_data_enrich] No eligible chunks — skipping enrichment.")
        return chunks

    logger.info(
        "[fund_data_enrich] Enriching %d / %d chunks with %s",
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
                "extraction/fund_data_enrichment.j2",
                content=content,
            )
            result = create_completion(
                system_prompt="You are a fund governance analyst specializing in legal document extraction.",
                user_prompt=user_prompt,
                model=model,
                temperature=0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            extracted: dict[str, Any] = json.loads(result.text or "{}")
            updates: dict[str, Any] = {}
            for field in ("clause_type", "party_role", "obligation_type", "applies_to"):
                val = extracted.get(field)
                updates[field] = val if (val and val != "null") else None
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
