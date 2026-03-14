"""market_data_bootstrap.py — Stage A for market-data source
==========================================================
Extracts market-data metadata for documents stored in the `market-data` Azure Blob
container (PitchBook benchmarks, market research, performance benchmarks, etc.).

Metadata is derived from blob tags + path heuristics. No OCR or external API calls
are made during bootstrap — all AI enrichment happens as a post-chunking pass inside
pipeline_azure.py (benchmark_enrich_chunks).

Output written to: <item_dir>/fund_context.json

Usage (from pipeline_azure.py):
    metadata = bootstrap_market_folder(item_dir, blob_service, input_container, item_folder)

Per-chunk BENCHMARK enrichment:
    After process_folder() runs, call enrich_benchmark_chunks() to extract
    structured fields (asset_class, sub_strategy, metric_type, vintage_year, geography)
    from each chunk using gpt-4.1-mini.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from azure.storage.blob import BlobServiceClient

from ai_engine.model_config import get_model
from ai_engine.openai_client import create_completion
from ai_engine.prompts import prompt_registry

logger = logging.getLogger(__name__)


# ── Source type candidates ─────────────────────────────────────────────────────
_SOURCE_TYPE_MAP: dict[str, str] = {
    "benchmarks": "BENCHMARK",
    "research":   "RESEARCH",
    "macro":      "MACRO",
    "news":       "NEWS",
}

# ── Publisher heuristics (blob path component → publisher) ────────────────────
_PUBLISHER_MAP: dict[str, str] = {
    "pitchbook":  "PitchBook",
    "preqin":     "Preqin",
    "bloomberg":  "Bloomberg",
    "fred":       "FRED",
    "cambridge":  "Cambridge Associates",
    "hamilton":   "Hamilton Lane",
    "burgiss":    "Burgiss",
    "msci":       "MSCI",
}

def _infer_source_type_from_path(blob_name: str) -> str:
    """Infer source_type from blob path components."""
    lower = blob_name.lower()
    for segment, stype in _SOURCE_TYPE_MAP.items():
        if segment in lower:
            return stype
    return "BENCHMARK"  # default for market-data container


def _infer_publisher_from_path(blob_name: str) -> str:
    """Infer publisher from blob path/filename."""
    lower = blob_name.lower()
    for segment, pub in _PUBLISHER_MAP.items():
        if segment in lower:
            return pub
    return "UNKNOWN"


def _infer_reference_date_from_path(blob_name: str) -> str:
    """Infer reference_date from blob filename patterns.
    Looks for patterns like: q2-2025, q2_2025, 2025-q2, 2025q2, fy2024, 2024
    """
    import re
    lower = blob_name.lower()
    # Quarter-year patterns
    m = re.search(r"(q[1-4])[-_]?(\d{4})|(\d{4})[-_]?(q[1-4])", lower)
    if m:
        if m.group(1) and m.group(2):
            return f"{m.group(1).upper()} {m.group(2)}"
        elif m.group(3) and m.group(4):
            return f"{m.group(4).upper()} {m.group(3)}"
    # Full year
    m = re.search(r"\b(20\d{2})\b", lower)
    if m:
        return m.group(1)
    return "UNKNOWN"


def get_blob_tags(
    blob_service: BlobServiceClient,
    container: str,
    blob_name: str,
) -> dict[str, str]:
    """Fetch blob tags. Returns empty dict on error."""
    try:
        cc = blob_service.get_container_client(container)
        bc = cc.get_blob_client(blob_name)
        return bc.get_blob_tags() or {}
    except Exception as e:
        logger.warning("Could not fetch tags for %s: %s", blob_name, e)
        return {}


def build_market_document_metadata(
    blob_name: str,
    blob_tags: dict[str, str],
) -> dict:
    """Build the metadata dict for a single market-data document.

    Parameters
    ----------
    blob_name  : full blob name, e.g. "benchmarks/pitchbook/q2-2025-pitchbook-benchmarks.pdf"
    blob_tags  : blob tags, e.g. {"source_type": "BENCHMARK", "publisher": "PitchBook",
                                   "reference_date": "Q2 2025", "asset_class": "private_markets"}

    Returns
    -------
    dict — metadata injected into every chunk from this document

    """
    return {
        "source_type":    blob_tags.get("source_type",    _infer_source_type_from_path(blob_name)),
        "publisher":      blob_tags.get("publisher",      _infer_publisher_from_path(blob_name)),
        "reference_date": blob_tags.get("reference_date", _infer_reference_date_from_path(blob_name)),
        "asset_class":    blob_tags.get("asset_class",    "private_markets"),
        "geography":      blob_tags.get("geography",      "global"),
        "sub_strategy":   blob_tags.get("sub_strategy"),
        "vintage_year":   None,    # populated per-chunk by enrich_benchmark_chunks()
        "metric_type":    None,    # populated per-chunk by enrich_benchmark_chunks()
    }


def bootstrap_market_folder(
    item_dir: Path,
    blob_service: BlobServiceClient,
    input_container: str,
    item_folder: str,
) -> dict:
    """Stage A for market-data source.

    Infers metadata from the item_folder (e.g. "benchmarks") and from blob tags
    of the first PDF found in that folder. Writes a fund_context.json-equivalent
    so that prepare_pdfs_full.process_folder() can load it.

    Parameters
    ----------
    item_dir        : Path  — local temp directory for this item
    blob_service    : BlobServiceClient
    input_container : str  — "market-data"
    item_folder     : str  — e.g. "benchmarks", "research", "macro"

    Returns
    -------
    dict — the market context metadata (also written to fund_context.json)

    """
    logger.info("Market Data Bootstrap — source type inference for '%s'", item_folder)

    # ── Fetch representative blob tags from first PDF ─────────────────────
    sample_tags: dict[str, str] = {}
    sample_blob: str = ""
    try:
        cc = blob_service.get_container_client(input_container)
        for blob in cc.list_blobs(name_starts_with=f"{item_folder}/"):
            if blob.name.lower().endswith(".pdf"):
                sample_blob = blob.name
                sample_tags = get_blob_tags(blob_service, input_container, blob.name)
                if sample_tags:
                    break
    except Exception as e:
        logger.warning("Blob scan failed: %s", e)

    # ── Build metadata ────────────────────────────────────────────────────
    inferred_blob = sample_blob or f"{item_folder}/unknown.pdf"
    source_type    = sample_tags.get("source_type",    _infer_source_type_from_path(inferred_blob))
    publisher      = sample_tags.get("publisher",      _infer_publisher_from_path(inferred_blob))
    reference_date = sample_tags.get("reference_date", _infer_reference_date_from_path(inferred_blob))
    asset_class    = sample_tags.get("asset_class",    "private_markets")
    geography      = sample_tags.get("geography",      "global")
    sub_strategy   = sample_tags.get("sub_strategy",   None)

    market_context = {
        # Identity — reuse fund_context.json schema for process_folder compatibility
        "fund_id":            "market-data",
        "fund_name":          f"Market Data — {publisher} ({reference_date})",
        "deal_name":          item_folder,
        "fund_strategy":      [source_type.lower()],
        "fund_jurisdiction":  None,
        "key_terms":          {},
        "discovered_aliases": [],
        "validated_vehicles": {},
        # Market-data specific fields
        "source_type":    source_type,
        "publisher":      publisher,
        "reference_date": reference_date,
        "asset_class":    asset_class,
        "geography":      geography,
        "sub_strategy":   sub_strategy,
        "vintage_year":   None,
        "metric_type":    None,
        # Source type marker
        "metadata_source": "market_data_bootstrap",
    }

    # ── Write fund_context.json for process_folder() ────────────────────
    ctx_path = item_dir / "fund_context.json"
    ctx_path.write_text(
        json.dumps(market_context, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(
        "source_type='%s' publisher='%s' ref='%s'",
        source_type, publisher, reference_date,
    )
    logger.info("fund_context.json → %s", ctx_path)

    return market_context


def inject_market_metadata(
    chunks: list[dict],
    market_context: dict,
    blob_service: BlobServiceClient,
    input_container: str,
) -> list[dict]:
    """Post-process: inject market-data-specific fields into every chunk from blob tags.

    Parameters
    ----------
    chunks          : list of chunk dicts (from cu_chunks.json)
    market_context  : result of bootstrap_market_folder()
    blob_service    : BlobServiceClient
    input_container : str — "market-data"

    Returns
    -------
    list[dict] — chunks with market-data fields injected

    """
    tags_cache: dict[str, dict[str, str]] = {}

    for chunk in chunks:
        blob_name = chunk.get("blob_name", "")

        if blob_name and blob_name not in tags_cache:
            tags_cache[blob_name] = get_blob_tags(
                blob_service, input_container, blob_name,
            )
        tags = tags_cache.get(blob_name, {})

        # Per-blob overrides from tags; fall back to folder-level defaults
        blob_meta = build_market_document_metadata(blob_name, tags) if tags else {}

        chunk.update({
            "source_type":    blob_meta.get("source_type",    market_context["source_type"]),
            "publisher":      blob_meta.get("publisher",      market_context["publisher"]),
            "reference_date": blob_meta.get("reference_date", market_context["reference_date"]),
            "asset_class":    blob_meta.get("asset_class",    market_context["asset_class"]),
            "geography":      blob_meta.get("geography",      market_context["geography"]),
            "sub_strategy":   blob_meta.get("sub_strategy",   market_context.get("sub_strategy")),
            # vintage_year and metric_type are set by enrich_benchmark_chunks()
            "vintage_year":   None,
            "metric_type":    None,
            # No deal identity for market-data
            "deal_id":   None,
            "deal_name": None,
            "fund_id":   "market-data",
        })

    return chunks


def enrich_benchmark_chunks(
    chunks: list[dict],
    openai_client: Any = None,  # deprecated — ignored, kept for call-site compat
    *,
    model: str | None = None,
    max_tokens: int = 150,
    cache_path: Path | None = None,
    source_type_filter: str = "BENCHMARK",
) -> list[dict]:
    """Per-chunk GPT enrichment for BENCHMARK documents.

    Extracts: asset_class, sub_strategy, metric_type, vintage_year, geography
    from each chunk using a fast LLM call. Results are cached to avoid re-processing
    on re-runs when --skip-prepare is set.

    Only runs on chunks where source_type == source_type_filter (default: "BENCHMARK").

    Parameters
    ----------
    chunks             : list of chunk dicts (after inject_market_metadata)
    openai_client      : deprecated — ignored (uses centralized create_completion)
    model              : LLM model id (default via get_model("extraction"))
    max_tokens         : max output tokens per call
    cache_path         : optional Path to a JSON file used as enrichment cache
    source_type_filter : only enrich chunks with this source_type

    Returns
    -------
    list[dict] — chunks with vintage_year, metric_type, asset_class, etc. populated

    """
    # ── Load enrichment cache ─────────────────────────────────────────────
    cache: dict[str, dict] = {}
    if cache_path and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    model = model or get_model("extraction")

    target_chunks = [c for c in chunks if c.get("source_type") == source_type_filter]
    if not target_chunks:
        logger.info("[benchmark_enrich] No %s chunks — skipping enrichment.", source_type_filter)
        return chunks

    logger.info("[benchmark_enrich] Enriching %d %s chunks with %s", len(target_chunks), source_type_filter, model)

    enriched_count = 0
    cache_hits = 0
    errors = 0

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
                "extraction/market_data_enrichment.j2",
                content=content,
            )
            result = create_completion(
                system_prompt="You are a private markets benchmark analyst specializing in data extraction.",
                user_prompt=user_prompt,
                model=model,
                temperature=0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            extracted = json.loads(result.text or "{}")
            updates: dict[str, Any] = {}
            for field in ("asset_class", "sub_strategy", "metric_type", "vintage_year", "geography"):
                val = extracted.get(field)
                if val and val != "null":
                    updates[field] = val
            return chunk_id, updates
        except Exception as e:
            logger.warning("chunk_id=%s: %s", chunk_id, e)
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
