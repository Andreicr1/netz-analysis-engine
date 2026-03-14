"""Batch API Client — Netz Private Credit OS
==========================================

OpenAI Batch API support for deep review chapter generation.
Submits all chapter requests as a single batch for 50% input cost discount.

Usage:
    from ai_engine.intelligence.batch_client import submit_chapter_batch, poll_batch, parse_batch_results

    batch_id = submit_chapter_batch(requests)
    await poll_batch(batch_id, timeout=1800)
    results = parse_batch_results(batch_id)

Architecture:
  - Each chapter request is serialised as a Responses API call in JSONL
  - Submitted via OpenAI Batch API (POST /v1/batches)
  - Polled with exponential backoff until completion
  - Results parsed back into chapter dicts

Note: Batch API offers 50% discount on input tokens but has latency
(typically 1-15 minutes for 14 chapter requests, max 24h guarantee).
Use for non-interactive deep review runs (e.g. background processing).
"""
from __future__ import annotations

import io
import json
import logging
import time
from typing import Any

from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)


def _get_batch_client() -> OpenAI:
    """Return an OpenAI client configured for batch operations."""
    api_key = settings.OPENAI_API_KEY
    if not api_key:
        raise ValueError("OPENAI_API_KEY required for Batch API (not supported on Azure OpenAI)")
    return OpenAI(api_key=api_key, timeout=120.0)


def build_chapter_request(
    *,
    custom_id: str,
    system_prompt: str,
    user_content: str,
    model: str,
    max_tokens: int,
    response_format: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a single Batch API request entry for a chapter.

    Returns a dict matching the OpenAI Batch JSONL format:
    {"custom_id": "...", "method": "POST", "url": "/v1/responses", "body": {...}}
    """
    body: dict[str, Any] = {
        "model": model,
        "instructions": system_prompt,
        "input": user_content,
        "max_output_tokens": max_tokens,
    }
    if response_format:
        body["text"] = {"format": response_format}

    return {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/responses",
        "body": body,
    }


def submit_chapter_batch(
    requests: list[dict[str, Any]],
    *,
    metadata: dict[str, str] | None = None,
) -> str:
    """Submit a batch of chapter requests to the OpenAI Batch API.

    Parameters
    ----------
    requests : list[dict]
        List of request dicts from build_chapter_request().
    metadata : dict | None
        Optional metadata (e.g. deal_id, version_tag) for tracking.

    Returns
    -------
    str
        The batch ID for polling.

    """
    client = _get_batch_client()

    # Build JSONL content
    jsonl_lines = [json.dumps(req, default=str) for req in requests]
    jsonl_content = "\n".join(jsonl_lines)

    logger.info(
        "BATCH_SUBMIT_START requests=%d total_chars=%d",
        len(requests), len(jsonl_content),
    )

    # Upload JSONL file
    file_obj = io.BytesIO(jsonl_content.encode("utf-8"))
    uploaded = client.files.create(
        file=("batch_chapters.jsonl", file_obj),
        purpose="batch",
    )

    logger.info("BATCH_FILE_UPLOADED file_id=%s", uploaded.id)

    # Create batch
    batch = client.batches.create(
        input_file_id=uploaded.id,
        endpoint="/v1/responses",
        completion_window="24h",
        metadata=metadata or {},
    )

    logger.info("BATCH_CREATED batch_id=%s status=%s", batch.id, batch.status)
    return batch.id


def poll_batch(
    batch_id: str,
    *,
    timeout: float = 1800,
    poll_interval: float = 10.0,
    max_interval: float = 60.0,
) -> dict[str, Any]:
    """Poll a batch until it completes or times out.

    Parameters
    ----------
    batch_id : str
        Batch ID from submit_chapter_batch().
    timeout : float
        Maximum seconds to wait (default 30 minutes).
    poll_interval : float
        Initial polling interval in seconds.
    max_interval : float
        Maximum polling interval (exponential backoff cap).

    Returns
    -------
    dict
        Batch status object with keys: status, request_counts, output_file_id, etc.

    Raises
    ------
    TimeoutError
        If the batch doesn't complete within the timeout.
    RuntimeError
        If the batch fails or is cancelled.

    """
    client = _get_batch_client()
    start = time.monotonic()
    interval = poll_interval

    while True:
        batch = client.batches.retrieve(batch_id)
        status = batch.status
        request_counts = batch.request_counts

        logger.info(
            "BATCH_POLL batch_id=%s status=%s completed=%s/%s failed=%s",
            batch_id, status,
            getattr(request_counts, "completed", "?"),
            getattr(request_counts, "total", "?"),
            getattr(request_counts, "failed", "?"),
        )

        if status == "completed":
            return {
                "status": "completed",
                "output_file_id": batch.output_file_id,
                "error_file_id": batch.error_file_id,
                "request_counts": {
                    "total": getattr(request_counts, "total", 0),
                    "completed": getattr(request_counts, "completed", 0),
                    "failed": getattr(request_counts, "failed", 0),
                },
            }

        if status in ("failed", "cancelled", "expired"):
            errors = []
            if batch.errors and batch.errors.data:
                errors = [
                    {"code": e.code, "message": e.message}
                    for e in batch.errors.data[:5]
                ]
            raise RuntimeError(
                f"Batch {batch_id} {status}: {errors}",
            )

        elapsed = time.monotonic() - start
        if elapsed > timeout:
            raise TimeoutError(
                f"Batch {batch_id} still {status} after {elapsed:.0f}s "
                f"(timeout={timeout}s)",
            )

        time.sleep(interval)
        interval = min(interval * 1.5, max_interval)


def parse_batch_results(batch_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Parse the output JSONL from a completed batch.

    Parameters
    ----------
    batch_result : dict
        Result from poll_batch() with output_file_id.

    Returns
    -------
    dict[str, dict]
        Mapping of custom_id → parsed JSON response body.
        Failed requests have an "error" key instead of parsed content.

    """
    client = _get_batch_client()

    output_file_id = batch_result.get("output_file_id")
    if not output_file_id:
        raise ValueError("No output_file_id in batch result — batch may have failed")

    # Download output JSONL
    content = client.files.content(output_file_id)
    text = content.text

    results: dict[str, dict[str, Any]] = {}

    for line in text.strip().split("\n"):
        if not line.strip():
            continue
        entry = json.loads(line)
        custom_id = entry.get("custom_id", "unknown")
        response = entry.get("response", {})
        status_code = response.get("status_code", 0)

        if status_code == 200:
            body = response.get("body", {})
            # Extract text from Responses API output
            output_text = ""
            if isinstance(body, dict):
                output_text = body.get("output_text", "")
                if not output_text:
                    # Try extracting from output array
                    for item in body.get("output", []):
                        if item.get("type") == "message":
                            for content_item in item.get("content", []):
                                if content_item.get("type") == "output_text":
                                    output_text = content_item.get("text", "")

            try:
                parsed = json.loads(output_text)
                results[custom_id] = parsed
            except json.JSONDecodeError:
                results[custom_id] = {
                    "error": f"Invalid JSON in batch response: {output_text[:200]}",
                }
        else:
            error_body = response.get("body", {})
            results[custom_id] = {
                "error": f"HTTP {status_code}: {json.dumps(error_body, default=str)[:300]}",
            }

    logger.info(
        "BATCH_RESULTS_PARSED total=%d successful=%d failed=%d",
        len(results),
        sum(1 for r in results.values() if "error" not in r),
        sum(1 for r in results.values() if "error" in r),
    )

    # Also parse error file if present
    error_file_id = batch_result.get("error_file_id")
    if error_file_id:
        try:
            error_content = client.files.content(error_file_id)
            for line in error_content.text.strip().split("\n"):
                if not line.strip():
                    continue
                entry = json.loads(line)
                custom_id = entry.get("custom_id", "unknown")
                if custom_id not in results:
                    results[custom_id] = {
                        "error": json.dumps(entry.get("error", {}), default=str)[:300],
                    }
        except Exception as exc:
            logger.warning("BATCH_ERROR_FILE_PARSE_FAILED: %s", exc)

    return results
