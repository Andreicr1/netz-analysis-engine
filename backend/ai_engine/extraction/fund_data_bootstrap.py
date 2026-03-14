"""
fund_data_bootstrap.py — Stage A for fund-data source
======================================================
Extracts fund-level metadata for documents stored in the `fund-data` Azure Blob
container (fund constitution, regulatory, service-provider documents).

Unlike entity_bootstrap.py (which extracts deal-specific entities), this module
derives metadata from blob path + blob tags only — no OCR or LLM calls needed,
because the folder structure and blob tags are authoritative for this source.

The resulting fund_context.json is consumed by prepare_pdfs_full.process_folder()
exactly the same way that entity_bootstrap produces it for deals.

Output written to: <item_dir>/fund_context.json

Usage (from pipeline_azure.py):
    metadata = bootstrap_fund_folder(item_dir, blob_service, input_container, item_folder)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from azure.storage.blob import BlobServiceClient

logger = logging.getLogger(__name__)


# ── Category mapping — blob path component → canonical fund_data_category ────
_CATEGORY_MAP: dict[str, str] = {
    "fund-constitution": "fund-constitution",
    "regulatory":        "regulatory",
    "service-providers": "service-providers",
}

# ── Default fund identity for all fund-data documents ────────────────────────
_FUND_ID   = "netz-private-credit-fund"
_FUND_NAME = "Netz Private Credit Fund"


def _infer_category_from_path(blob_name: str) -> str | None:
    """
    Infer fund_data_category from the blob path.
    e.g. "fund-constitution/netz-private-credit-fund-im.pdf" → "fund-constitution"
    e.g. "regulatory/cima-regulations-2024.pdf"              → "regulatory"
    """
    parts = blob_name.split("/")
    for part in parts:
        if part in _CATEGORY_MAP:
            return _CATEGORY_MAP[part]
    return None


def get_blob_tags(
    blob_service: BlobServiceClient,
    container: str,
    blob_name: str,
) -> dict[str, str]:
    """Fetch blob tags for a single blob. Returns empty dict on error."""
    try:
        cc = blob_service.get_container_client(container)
        bc = cc.get_blob_client(blob_name)
        return bc.get_blob_tags() or {}
    except Exception as e:
        logger.warning("[fund_data_bootstrap] Could not fetch tags for %s: %s", blob_name, e)
        return {}


def build_fund_document_metadata(
    blob_name: str,
    blob_tags: dict[str, str],
) -> dict:
    """
    Build the metadata dict for a single fund-data document.

    Parameters
    ----------
    blob_name : str
        Full blob name, e.g. "fund-constitution/netz-private-credit-fund-im.pdf"
    blob_tags : dict
        Blob tags, e.g. {"fund_data_category": "fund-constitution",
                         "jurisdiction": "cayman", "doc_language": "en"}

    Returns
    -------
    dict
        Metadata injected into every chunk from this document.
    """
    inferred_category = _infer_category_from_path(blob_name)

    return {
        "fund_data_category": blob_tags.get("fund_data_category", inferred_category or "unknown"),
        "jurisdiction":       blob_tags.get("jurisdiction", "cayman"),
        "doc_language":       blob_tags.get("doc_language", "en"),
        "effective_date":     blob_tags.get("effective_date"),
        "superseded_by":      blob_tags.get("superseded_by"),
        # v4 identity fields — no deal context for fund-data
        "deal_id":            None,
        "deal_name":          None,
        "fund_id":            _FUND_ID,
        "fund_name":          _FUND_NAME,
    }


def bootstrap_fund_folder(
    item_dir: Path,
    blob_service: BlobServiceClient,
    input_container: str,
    item_folder: str,
) -> dict:
    """
    Stage A for fund-data source.

    Determines the fund_data_category from the item_folder name (which is the
    first-level path segment in the fund-data container, e.g. "fund-constitution").

    Writes fund_context.json to item_dir so that prepare_pdfs_full.process_folder()
    picks it up automatically.

    Parameters
    ----------
    item_dir        : Path  — local temp directory for this item
    blob_service    : BlobServiceClient
    input_container : str  — "fund-data"
    item_folder     : str  — e.g. "fund-constitution", "regulatory", "service-providers"

    Returns
    -------
    dict — the fund context metadata (also written to fund_context.json)
    """
    logger.info("Fund Data Bootstrap — category inference for '%s'", item_folder)

    # ── Infer category from folder name (primary) ─────────────────────────
    category = _CATEGORY_MAP.get(item_folder, "unknown")
    if category == "unknown":
        # Fallback: try to infer from any blob name in the folder
        try:
            cc = blob_service.get_container_client(input_container)
            for blob in cc.list_blobs(name_starts_with=f"{item_folder}/"):
                if blob.name.lower().endswith(".pdf"):
                    inferred = _infer_category_from_path(blob.name)
                    if inferred:
                        category = inferred
                        break
        except Exception as e:
            logger.warning("Blob scan failed: %s", e)

    # ── Fetch representative blob tags (from first PDF in folder) ─────────
    sample_tags: dict[str, str] = {}
    try:
        cc = blob_service.get_container_client(input_container)
        for blob in cc.list_blobs(name_starts_with=f"{item_folder}/"):
            if blob.name.lower().endswith(".pdf"):
                sample_tags = get_blob_tags(blob_service, input_container, blob.name)
                if sample_tags:
                    break
    except Exception as e:
        logger.warning("Tags fetch failed: %s", e)

    # Use folder-level tags as defaults; per-blob tags are fetched at chunk-injection time
    fund_context = {
        "fund_id":            _FUND_ID,
        "fund_name":          _FUND_NAME,
        "deal_name":          item_folder,    # used as section label in breadcrumbs
        "fund_data_category": sample_tags.get("fund_data_category", category),
        "jurisdiction":       sample_tags.get("jurisdiction", "cayman"),
        "doc_language":       sample_tags.get("doc_language", "en"),
        "effective_date":     sample_tags.get("effective_date", None),
        "superseded_by":      None,
        # source type marker — used by pipeline_azure.py for enrichment dispatch
        "metadata_source":    "fund_data_bootstrap",
        # Empty aliases/entities so process_folder does not error
        "discovered_aliases": [],
        "validated_vehicles": {},
        "fund_strategy":      ["fund-data"],
        "fund_jurisdiction":  sample_tags.get("jurisdiction", "cayman"),
        "key_terms":          {},
    }

    # ── Write fund_context.json for process_folder() ──────────────────────
    ctx_path = item_dir / "fund_context.json"
    ctx_path.write_text(
        json.dumps(fund_context, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(
        "category='%s' | fund='%s' | tags=%s",
        category, _FUND_NAME, dict(list(sample_tags.items())[:3]),
    )
    logger.info("fund_context.json → %s", ctx_path)

    return fund_context


def inject_fund_data_metadata(
    chunks: list[dict],
    fund_context: dict,
    blob_service: BlobServiceClient,
    input_container: str,
) -> list[dict]:
    """
    Post-process: inject fund-data-specific fields into every chunk.

    The blob-level tags are fetched per unique blob_name so that documents
    within the same folder can have different jurisdictions or languages.

    Parameters
    ----------
    chunks          : list of chunk dicts (from cu_chunks.json)
    fund_context    : the result of bootstrap_fund_folder()
    blob_service    : BlobServiceClient
    input_container : str — "fund-data"

    Returns
    -------
    list[dict] — enriched chunks
    """
    # Cache blob tags per blob_name to avoid redundant API calls
    tags_cache: dict[str, dict[str, str]] = {}

    for chunk in chunks:
        blob_name = chunk.get("blob_name", "")

        if blob_name and blob_name not in tags_cache:
            tags_cache[blob_name] = get_blob_tags(
                blob_service, input_container, blob_name
            )
        tags = tags_cache.get(blob_name, {})

        # Build per-chunk metadata from blob tags (overrides folder-level defaults)
        inferred_cat = _infer_category_from_path(blob_name)
        chunk.update({
            "fund_data_category": tags.get(
                "fund_data_category",
                fund_context.get("fund_data_category", inferred_cat or "unknown"),
            ),
            "jurisdiction":  tags.get("jurisdiction", fund_context.get("jurisdiction", "cayman")),
            "doc_language":  tags.get("doc_language", fund_context.get("doc_language", "en")),
            "effective_date": tags.get("effective_date", fund_context.get("effective_date")),
            "superseded_by": tags.get("superseded_by", None),
            "fund_id":   fund_context["fund_id"],
            "fund_name": fund_context["fund_name"],
            # Override deal_id: null (no deal context for fund-data)
            "deal_id":   None,
            "deal_name": None,
        })

    return chunks
