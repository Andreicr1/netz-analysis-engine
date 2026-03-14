"""
extraction_orchestrator.py — Cloud-Native Pipeline Orchestrator
================================================================
Adapted from cu-pdf-prepare/pipeline_azure.py for use as a module
inside the FastAPI backend on Azure App Service.

All Azure credentials are read at runtime from environment variables
(Key Vault references via App Service appsettings):
    AZURE_STORAGE_CONNECTION_STRING — Azure Blob Storage
    AZURE_SEARCH_ENDPOINT           — Azure AI Search endpoint
    AZURE_SEARCH_API_KEY            — Azure AI Search admin key
    MISTRAL_API_KEY                 — Mistral OCR (public API)
    AZURE_API_KEY                   — Cohere Rerank (Azure AI Foundry)
    OPENAI_API_KEY                  — direct OpenAI primary provider (optional)
    AZURE_OPENAI_KEY                — Azure OpenAI provider key
    AZURE_OPENAI_ENDPOINT           — Azure OpenAI provider endpoint
    AZURE_OPENAI_API_VERSION        — Azure OpenAI API version

Public API
----------
    run_extraction_pipeline(source, ...) -> str (job_id)
    get_job_status(job_id)              -> dict
    list_pipeline_jobs()                -> list[dict]
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path

import requests
from azure.storage.blob import BlobServiceClient
from openai import OpenAI

from ai_engine.extraction.embed_chunks import embed_folder
from ai_engine.extraction.entity_bootstrap import bootstrap_folder
from ai_engine.extraction.prepare_pdfs_full import process_folder

logger = logging.getLogger(__name__)

# ============================================================
# MULTI-SOURCE CONFIGURATION
# ============================================================

SOURCE_CONFIG: dict[str, dict] = {
    "deals": {
        "input_container":  "investment-pipeline-intelligence",
        "output_container": "vector-chunks-v4",
        "indexer":          "global-vector-chunks-v4-indexer",
        "index":            "global-vector-chunks-v4",
        "metadata_extractor": "deal_bootstrap",
        "description":      "Deal PDFs → global-vector-chunks-v4",
    },
    "fund-data": {
        "input_container":  "fund-data",
        "output_container": "vector-chunks-fund-data",
        "indexer":          "fund-data-indexer",
        "index":            "fund-data-index",
        "metadata_extractor": "fund_data_bootstrap",
        "description":      "Constitutional/regulatory/service-provider docs → fund-data-index",
    },
    "market-data": {
        "input_container":  "market-data",
        "output_container": "vector-chunks-market-data",
        "indexer":          "market-data-indexer",
        "index":            "market-data-index",
        "metadata_extractor": "market_data_bootstrap",
        "description":      "PitchBook benchmarks + market research → market-data-index",
    },
}

SEARCH_API_VER = "2023-11-01"

# ============================================================
# IN-MEMORY JOB STORE
# ============================================================

_JOBS: dict[str, dict] = {}
_MAX_JOBS = 50  # keep only the last N jobs in memory


def _new_job(source: str, deals_filter: str) -> str:
    job_id = str(uuid.uuid4())
    _JOBS[job_id] = {
        "job_id":       job_id,
        "source":       source,
        "deals_filter": deals_filter,
        "status":       "pending",
        "started_at":   None,
        "finished_at":  None,
        "results":      [],
        "error":        None,
    }
    # Trim oldest jobs
    if len(_JOBS) > _MAX_JOBS:
        oldest = sorted(_JOBS.keys())[0]
        del _JOBS[oldest]
    return job_id


def _update_job(job_id: str, **kwargs) -> None:
    if job_id in _JOBS:
        _JOBS[job_id].update(kwargs)


def get_job_status(job_id: str) -> dict:
    """Return status dict for a job, or {"error": "Not found"} if unknown."""
    return _JOBS.get(job_id, {"error": "Job not found", "job_id": job_id})


def list_pipeline_jobs() -> list[dict]:
    """Return all tracked jobs, most recent first."""
    return sorted(_JOBS.values(), key=lambda j: j.get("started_at") or "", reverse=True)


# ============================================================
# SECRET ACCESSORS (always fresh from env)
# ============================================================

def _storage_conn_str() -> str:
    v = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    if not v:
        raise OSError("AZURE_STORAGE_CONNECTION_STRING not set")
    return v


def _search_endpoint() -> str:
    return os.environ.get("AZURE_SEARCH_ENDPOINT", "").rstrip("/")


def _search_headers() -> dict:
    return {
        "api-key":      os.environ.get("AZURE_SEARCH_API_KEY", ""),
        "Content-Type": "application/json",
    }


def _mistral_key() -> str:
    return os.environ.get("MISTRAL_API_KEY", "")


def _azure_key() -> str:
    return os.environ.get("AZURE_API_KEY", "")


def _openai_key() -> str:
    return os.environ.get("OPENAI_API_KEY", "")


def _az_openai_key() -> str:
    return os.environ.get("AZURE_OPENAI_KEY", os.environ.get("AZURE_OPENAI_API_KEY", ""))


def _az_openai_ep() -> str:
    return os.environ.get("AZURE_OPENAI_ENDPOINT", "https://netzai.services.ai.azure.com")


def _az_openai_ver() -> str:
    return os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")


# ============================================================
# BLOB HELPERS
# ============================================================

def get_blob_service() -> BlobServiceClient:
    return BlobServiceClient.from_connection_string(_storage_conn_str())


def list_source_folders(blob_service: BlobServiceClient, container: str) -> list[str]:
    """Return sorted list of unique top-level folder prefixes containing PDFs."""
    cc = blob_service.get_container_client(container)
    seen: set[str] = set()
    for blob in cc.list_blobs():
        parts = blob.name.split("/", 1)
        if len(parts) == 2 and blob.name.lower().endswith(".pdf"):
            seen.add(parts[0])
    return sorted(seen)


def download_to_temp(
    blob_service: BlobServiceClient,
    container: str,
    item_folder: str,
    temp_dir: Path,
) -> int:
    """Download all PDFs + JSON from container/item_folder/ into temp_dir/item_folder/."""
    cc = blob_service.get_container_client(container)
    target_dir = temp_dir / item_folder
    target_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{item_folder}/"
    count = 0

    _DOWNLOAD_EXTS = {".pdf", ".json"}

    for blob in cc.list_blobs(name_starts_with=prefix):
        relative = blob.name[len(prefix):]
        local_path = target_dir / relative
        ext = Path(relative).suffix.lower()
        if ext not in _DOWNLOAD_EXTS:
            continue
        local_path.parent.mkdir(parents=True, exist_ok=True)
        blob_client = cc.get_blob_client(blob.name)
        with open(local_path, "wb") as fh:
            fh.write(blob_client.download_blob().readall())
        size_kb = local_path.stat().st_size // 1024
        logger.info("dl %s (%d KB)", relative, size_kb)
        count += 1

    return count


def ensure_container(blob_service: BlobServiceClient, container_name: str) -> None:
    cc = blob_service.get_container_client(container_name)
    try:
        cc.get_container_properties()
    except Exception:
        cc.create_container()
        logger.info("Created container '%s'", container_name)


def upload_file_to_blob(
    blob_service: BlobServiceClient,
    container_name: str,
    blob_name: str,
    local_path: Path,
) -> None:
    container = blob_service.get_container_client(container_name)
    with open(local_path, "rb") as fh:
        container.get_blob_client(blob_name).upload_blob(fh, overwrite=True)
    size_kb = local_path.stat().st_size // 1024
    logger.info("ul %s (%d KB)", blob_name, size_kb)


# ============================================================
# INDEXER CONTROL
# ============================================================

def reset_and_run_indexer(
    indexer_name: str,
    poll_timeout: int = 600,
) -> None:
    endpoint = _search_endpoint()
    headers = _search_headers()
    reset_url = f"{endpoint}/indexers/{indexer_name}/reset?api-version={SEARCH_API_VER}"
    run_url   = f"{endpoint}/indexers/{indexer_name}/run?api-version={SEARCH_API_VER}"
    stat_url  = f"{endpoint}/indexers/{indexer_name}/status?api-version={SEARCH_API_VER}"

    logger.info("Indexer reset + run: %s", indexer_name)

    resp = requests.post(reset_url, headers=headers)
    logger.info("Reset: HTTP %d", resp.status_code)
    time.sleep(2)
    resp = requests.post(run_url, headers=headers)
    logger.info("Run: HTTP %d", resp.status_code)

    elapsed = 0
    interval = 15
    while elapsed < poll_timeout:
        resp = requests.get(stat_url, headers=headers)
        if not resp.ok:
            logger.warning("Status check HTTP %d", resp.status_code)
            break
        last   = resp.json().get("lastResult", {}) or {}
        status = last.get("status", "unknown")
        docs   = last.get("itemsProcessed", "?")
        failed = last.get("itemsFailed", "?")
        logger.info("[%4ds] %s docs=%s failed=%s", elapsed, status, docs, failed)
        if status == "success":
            logger.info("Indexer complete — %s documents indexed", docs)
            return
        if status in ("transientFailure", "persistentFailure"):
            logger.warning("Indexer failed: %s", last.get('errorMessage', ''))
            return
        time.sleep(interval)
        elapsed += interval

    logger.warning("Indexer still running after %ds — check Azure portal", poll_timeout)


# ============================================================
# STAGE A — source-specific bootstrap dispatch
# ============================================================

def _run_stage_a_bootstrap(
    item_dir: Path,
    item_folder: str,
    source_cfg: dict,
    blob_service: BlobServiceClient,
    gpt_client: OpenAI | None,
    embed_client: OpenAI | None,
    dry_run: bool,
) -> dict:
    extractor = source_cfg["metadata_extractor"]

    if extractor == "deal_bootstrap":
        bootstrap_folder(
            item_dir, _mistral_key(), _azure_key(),
            dry_run=dry_run,
        )
        return {}

    elif extractor == "fund_data_bootstrap":
        from ai_engine.extraction.fund_data_bootstrap import bootstrap_fund_folder
        return bootstrap_fund_folder(
            item_dir, blob_service, source_cfg["input_container"], item_folder
        )

    elif extractor == "market_data_bootstrap":
        from ai_engine.extraction.market_data_bootstrap import bootstrap_market_folder
        return bootstrap_market_folder(
            item_dir, blob_service, source_cfg["input_container"], item_folder
        )

    else:
        logger.warning("Unknown metadata_extractor '%s' — skipping Stage A", extractor)
        return {}


# ============================================================
# POST-PROCESS CHUNKS — metadata injection + Stage B.5 enrichment
# ============================================================

def _post_process_chunks(
    item_dir: Path,
    item_folder: str,
    source_cfg: dict,
    blob_stage_a_meta: dict,
    blob_service: BlobServiceClient,
    gpt_client: OpenAI | None,
    skip_enrich: bool = False,
) -> None:
    extractor = source_cfg["metadata_extractor"]
    cu_chunks_path = item_dir / "cu_chunks.json"
    if not cu_chunks_path.exists():
        return

    chunks = json.loads(cu_chunks_path.read_bytes())

    if extractor == "deal_bootstrap":
        if not skip_enrich:
            from ai_engine.extraction.deals_enrichment import enrich_deals_chunks
            logger.info("Stage B.5 — deals enrichment (%d chunks)", len(chunks))
            cache_file = item_dir / "deals_enrichment_cache.json"
            chunks = enrich_deals_chunks(chunks, gpt_client, cache_path=cache_file)
        else:
            logger.info("Stage B.5 — deals enrichment SKIPPED")

    elif extractor == "fund_data_bootstrap":
        if blob_stage_a_meta:
            from ai_engine.extraction.fund_data_bootstrap import inject_fund_data_metadata
            logger.info("Injecting fund-data metadata into %d chunks", len(chunks))
            chunks = inject_fund_data_metadata(
                chunks, blob_stage_a_meta, blob_service, source_cfg["input_container"]
            )
        if not skip_enrich:
            from ai_engine.extraction.fund_data_enrichment import enrich_fund_data_chunks
            logger.info("Stage B.5 — fund-data enrichment (%d chunks)", len(chunks))
            cache_file = item_dir / "fund_data_enrichment_cache.json"
            chunks = enrich_fund_data_chunks(chunks, gpt_client, cache_path=cache_file)
        else:
            logger.info("Stage B.5 — fund-data enrichment SKIPPED")

    elif extractor == "market_data_bootstrap" and blob_stage_a_meta:
        from ai_engine.extraction.market_data_bootstrap import (
            enrich_benchmark_chunks,
            inject_market_metadata,
        )
        logger.info("Injecting market-data metadata into %d chunks", len(chunks))
        chunks = inject_market_metadata(
            chunks, blob_stage_a_meta, blob_service, source_cfg["input_container"]
        )
        if not skip_enrich and blob_stage_a_meta.get("source_type") == "BENCHMARK":
            cache_file = item_dir / "benchmark_enrichment_cache.json"
            chunks = enrich_benchmark_chunks(
                chunks, gpt_client, cache_path=cache_file
            )

    cu_chunks_path.write_text(
        json.dumps(chunks, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ============================================================
# PIPELINE PER ITEM
# ============================================================

def run_item(
    blob_service: BlobServiceClient,
    item_folder: str,
    source_cfg: dict,
    gpt_client: OpenAI | None,
    embed_client: OpenAI | None,
    dry_run: bool = False,
    skip_bootstrap: bool = False,
    skip_prepare: bool = False,
    skip_embed: bool = False,
    skip_enrich: bool = False,
) -> dict:
    """Full 5-stage pipeline for one source item in a temporary directory."""
    input_container  = source_cfg["input_container"]
    output_container = source_cfg["output_container"]
    safe_prefix      = item_folder[:20].replace("/", "_")

    with tempfile.TemporaryDirectory(prefix=f"netz_{safe_prefix}_") as tmp:
        temp_dir = Path(tmp)
        result: dict = {"deal": item_folder, "status": "ok", "chunks": 0}

        try:
            # ── Step 1 ─────────────────────────────────────────────────────
            logger.info("[1/5] Download blobs from %s/%s/", input_container, item_folder)
            n_files = download_to_temp(blob_service, input_container, item_folder, temp_dir)
            if n_files == 0:
                logger.info("No PDFs or metadata found — item folder empty")
                result["status"] = "empty"
                return result
            logger.info("Downloaded: %d files", n_files)

            item_dir = temp_dir / item_folder

            # ── Step 2 ─────────────────────────────────────────────────────
            stage_a_meta: dict = {}
            if not skip_bootstrap:
                stage_a_meta = _run_stage_a_bootstrap(
                    item_dir, item_folder, source_cfg,
                    blob_service, gpt_client, embed_client, dry_run
                )
            else:
                logger.info("[2/5] Stage A Bootstrap — SKIPPED")

            # ── Step 3 ─────────────────────────────────────────────────────
            if not skip_prepare:
                logger.info("[3/5] prepare_pdfs_full — OCR + Classification + Chunking")
                process_folder(
                    str(item_dir),
                    _mistral_key(),
                    _azure_key(),
                    dry_run,
                )
                if not dry_run and (stage_a_meta or source_cfg["metadata_extractor"] == "deal_bootstrap"):
                    logger.info("[3b/5] Post-process chunks — metadata injection + Stage B.5 enrichment")
                    _post_process_chunks(
                        item_dir, item_folder, source_cfg, stage_a_meta,
                        blob_service, gpt_client,
                        skip_enrich=skip_enrich,
                    )
            else:
                logger.info("[3/5] prepare_pdfs_full — SKIPPED")

            # ── Step 4 ─────────────────────────────────────────────────────
            if not skip_embed and not dry_run:
                cu_chunks_path = item_dir / "cu_chunks.json"
                if not cu_chunks_path.exists():
                    logger.info("[4/5] Embedding — SKIP (cu_chunks.json not found)")
                else:
                    logger.info("[4/5] Embedding — text-embedding-3-large")
                    n = embed_folder(
                        str(item_dir),
                        dry_run=False,
                    )
                    result["chunks"] = n
            else:
                logger.info("[4/5] Embedding — SKIPPED")

            # ── Step 5 ─────────────────────────────────────────────────────
            if not dry_run:
                logger.info("[5/5] Upload outputs → %s", output_container)

                MAX_CHUNKS_PER_FILE = 250
                embedded_path = item_dir / "cu_chunks_embedded.json"
                if embedded_path.exists():
                    chunks_all = json.loads(embedded_path.read_bytes())
                    if len(chunks_all) <= MAX_CHUNKS_PER_FILE:
                        blob_name = f"{item_folder}/cu_chunks_embedded.json"
                        upload_file_to_blob(blob_service, output_container, blob_name, embedded_path)
                    else:
                        shard_idx = 0
                        for shard_idx, start in enumerate(range(0, len(chunks_all), MAX_CHUNKS_PER_FILE)):
                            shard = chunks_all[start : start + MAX_CHUNKS_PER_FILE]
                            shard_path = item_dir / f"cu_chunks_embedded_{shard_idx:03d}.json"
                            shard_path.write_text(json.dumps(shard), encoding="utf-8")
                            blob_name = f"{item_folder}/cu_chunks_embedded_{shard_idx:03d}.json"
                            upload_file_to_blob(blob_service, output_container, blob_name, shard_path)
                        logger.info("%d chunks → %d shards of %d", len(chunks_all), shard_idx+1, MAX_CHUNKS_PER_FILE)
                else:
                    logger.info("cu_chunks_embedded.json not found, skipping upload")

                # Side-upload metadata files back to input container
                for fname, container in [
                    ("fund_context.json",             input_container),
                    ("cu_preparation_report.json",    input_container),
                    ("benchmark_enrichment_cache.json", input_container),
                    ("deals_enrichment_cache.json",   input_container),
                    ("fund_data_enrichment_cache.json", input_container),
                ]:
                    fpath = item_dir / fname
                    if fpath.exists():
                        upload_file_to_blob(
                            blob_service, container,
                            f"{item_folder}/{fname}", fpath
                        )
            else:
                logger.info("[5/5] Upload — DRY-RUN, skipped")

        except Exception as exc:
            result["status"] = "error"
            result["error"]  = str(exc)
            logger.warning("Item failed: %s", exc, exc_info=True)

        return result


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

def run_extraction_pipeline(
    source: str = "deals",
    deals_filter: str = "",
    dry_run: bool = False,
    skip_bootstrap: bool = False,
    skip_prepare: bool = False,
    skip_embed: bool = False,
    skip_enrich: bool = False,
    no_index: bool = False,
    poll_timeout: int = 600,
    job_id: str | None = None,
) -> str:
    """
    Run the full extraction pipeline for *source* (or all sources when source=="all").

    Parameters
    ----------
    source          : "deals" | "fund-data" | "market-data" | "all"
    deals_filter    : comma-separated partial item names (empty = all items)
    dry_run         : OCR + classify but do not upload or index
    skip_bootstrap  : skip Stage A (reuse existing fund_context.json)
    skip_prepare    : skip OCR+chunking (reuse existing cu_chunks.json)
    skip_embed      : skip embedding stage
    skip_enrich     : skip Stage B.5 LLM enrichment
    no_index        : skip triggering the AI Search indexer
    poll_timeout    : seconds to wait for indexer after upload
    job_id          : pre-allocated job ID (created automatically if not given)

    Returns
    -------
    str — job_id that can be polled via get_job_status()
    """
    if job_id is None:
        job_id = _new_job(source, deals_filter)
    else:
        if job_id not in _JOBS:
            _new_job(source, deals_filter)
            _JOBS[job_id] = _JOBS.pop(list(_JOBS.keys())[-1])
            _JOBS[job_id]["job_id"] = job_id

    _update_job(job_id,
                status="running",
                started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    try:
        mistral = _mistral_key()
        azure   = _azure_key()
        openai_ = _openai_key()
        az_openai = _az_openai_key()

        missing = []
        if not mistral:
            missing.append("MISTRAL_API_KEY")
        if not azure:
            missing.append("AZURE_API_KEY")
        if not (openai_ or az_openai):
            missing.append("OPENAI_API_KEY or AZURE_OPENAI_KEY")
        if missing:
            raise OSError(f"Missing env vars: {', '.join(missing)}")

        # The downstream enrichment/embedding layers now use ai_engine.openai_client,
        # so a direct OpenAI SDK client is only needed for legacy call-site compatibility.
        gpt_client = OpenAI(api_key=openai_) if openai_ else None
        embed_client = OpenAI(api_key=openai_) if openai_ else None
        blob_service = get_blob_service()

        sources_to_run = list(SOURCE_CONFIG.keys()) if source == "all" else [source]

        all_results: list[dict] = []
        for source_key in sources_to_run:
            source_cfg = SOURCE_CONFIG[source_key]
            ensure_container(blob_service, source_cfg["output_container"])

            # Discover items
            all_items = list_source_folders(blob_service, source_cfg["input_container"])
            if deals_filter:
                filters = [f.strip().lower() for f in deals_filter.split(",") if f.strip()]
                all_items = [d for d in all_items if any(f in d.lower() for f in filters)]

            logger.info("Source: %s — %d items", source_key, len(all_items))
            for item in all_items:
                logger.info("  %s", item)

            for idx, item in enumerate(all_items, 1):
                logger.info("[%d/%d] %s", idx, len(all_items), item)
                r = run_item(
                    blob_service, item, source_cfg,
                    gpt_client, embed_client,
                    dry_run=dry_run,
                    skip_bootstrap=skip_bootstrap,
                    skip_prepare=skip_prepare,
                    skip_embed=skip_embed,
                    skip_enrich=skip_enrich,
                )
                all_results.append(r)
                icon = "[OK]" if r["status"] == "ok" else (
                    "[EMPTY]" if r["status"] == "empty" else "[FAIL]"
                )
                logger.info("%s %s → status=%s chunks=%d", icon, item, r['status'], r.get('chunks', 0))

            # Trigger indexer
            ok_items = [r for r in all_results if r["status"] == "ok"]
            if not no_index and not dry_run and ok_items:
                reset_and_run_indexer(
                    source_cfg["indexer"], poll_timeout=poll_timeout
                )

        ok    = len([r for r in all_results if r["status"] == "ok"])
        empty = len([r for r in all_results if r["status"] == "empty"])
        errs  = len([r for r in all_results if r["status"] == "error"])
        total_chunks = sum(r.get("chunks", 0) for r in all_results)

        _update_job(job_id,
                    status="completed",
                    finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    results=all_results,
                    summary={
                        "total": len(all_results),
                        "ok": ok, "empty": empty, "errors": errs,
                        "total_chunks": total_chunks,
                    })

    except Exception as exc:
        _update_job(job_id,
                    status="failed",
                    finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    error=str(exc))
        logger.warning("Pipeline failed: %s", exc, exc_info=True)

    return job_id
