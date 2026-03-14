"""LLM-Powered Compliance Obligation Extractor
============================================

Reads document chunks from the fund-data-index (Azure AI Search) across
all three compliance domains (REGULATORY, CONSTITUTION, SERVICE_PROVIDER),
sends them to the LLM for structured obligation extraction, and writes
the results into the ``obligations`` DB table that the Compliance UI reads.

This replaces the regex-only ``obligation_extractor.py`` approach with
institutional-grade AI extraction using ``create_completion()`` and
``get_model("compliance_extraction")``.

Flow:
  1. AzureComplianceKBAdapter.fetch_live() → pull chunks per domain
  2. Group chunks into batches and build LLM prompts
  3. create_completion() → JSON array of extracted obligations
  4. Deduplicate against existing DB obligations (by name)
  5. service.create_obligation() → persist into obligations table
"""

from __future__ import annotations

import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_engine.model_config import get_model
from ai_engine.openai_client import create_completion
from ai_engine.prompts import prompt_registry
from app.core.security.auth import Actor
from app.domains.credit.compliance.kb.azure_kb_adapter import (
    FUND_DATA_CATEGORY_MAP,
    AzureComplianceKBAdapter,
)
from app.domains.credit.modules.compliance.models import Obligation
from app.domains.credit.modules.compliance.schemas import ObligationCreate

logger = logging.getLogger(__name__)

# Map domain → source_type for the Obligation table
_DOMAIN_SOURCE_TYPE: dict[str, str] = {
    "REGULATORY": "CIMA",
    "CONSTITUTION": "IMA",
    "SERVICE_PROVIDER": "SERVICE_CONTRACT",
}

def _get_system_prompt() -> str:
    return prompt_registry.render("extraction/compliance_system.j2")


def _build_user_prompt(domain: str, chunks_text: str) -> str:
    return prompt_registry.render(
        "extraction/compliance_user.j2",
        domain=domain,
        chunks_text=chunks_text,
    )


def _fetch_domain_chunks(domain: str, top: int = 50) -> str:
    """Fetch chunks from fund-data-index for a given compliance domain."""
    try:
        chunks = AzureComplianceKBAdapter.fetch_live(domain=domain, top=top)
    except Exception as exc:
        logger.warning(
            "compliance_extractor: fetch_live failed for %s — %s", domain, exc,
        )
        return ""

    if not chunks:
        return ""

    # Build concatenated text with source annotations
    parts: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        source = chunk.source_blob or "unknown"
        parts.append(f"[Chunk {i} | {source}]\n{chunk.chunk_text}\n")

    return "\n".join(parts)


def _parse_obligations_json(raw: str) -> list[dict[str, Any]]:
    """Parse the LLM response as a JSON array of obligations."""
    text = raw.strip()
    # Handle markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("compliance_extractor: failed to parse LLM JSON output")
        return []

    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and "obligations" in parsed:
        return parsed["obligations"]
    return []


def _infer_next_due_date(raw_date: str | None, frequency: str | None) -> date | None:
    """Parse an ISO date or infer from frequency."""
    if raw_date:
        try:
            return date.fromisoformat(raw_date)
        except (ValueError, TypeError):
            pass

    # Infer based on frequency
    today = date.today()
    year = today.year
    if frequency == "ANNUAL":
        candidate = date(year, 12, 31)
        return candidate if candidate > today else date(year + 1, 12, 31)
    if frequency == "QUARTERLY":
        # Next quarter end
        for m in [3, 6, 9, 12]:
            candidate = date(
                year, m, 28 if m == 2 else 30 if m in (4, 6, 9, 11) else 31,
            )
            if candidate > today:
                return candidate
        return date(year + 1, 3, 31)
    if frequency == "MONTHLY":
        if today.month == 12:
            return date(year + 1, 1, 28)
        return date(year, today.month + 1, 28)
    return None


def extract_obligations_from_index(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor: Actor,
    top_per_domain: int = 50,
) -> list[Obligation]:
    """Extract obligations from fund-data-index using LLM and persist them.

    Returns the list of newly created Obligation records.
    """
    model = get_model("compliance_extraction")
    all_created: list[Obligation] = []

    # Load existing obligation names for deduplication
    existing_names: set[str] = set()
    try:
        rows = (
            db.execute(select(Obligation.name).where(Obligation.fund_id == fund_id))
            .scalars()
            .all()
        )
        existing_names = {n.lower().strip() for n in rows if n}
    except Exception as exc:
        logger.error(
            "compliance_extractor: failed to load existing obligations — %s", exc,
        )
        # Continue with empty set — will create obligations without dedup
        existing_names = set()

    # Phase 1: Fetch chunks (I/O) and build prompts — main thread
    domain_prompts: list[tuple[str, str, str]] = []  # (domain, source_type, user_prompt)
    for domain in FUND_DATA_CATEGORY_MAP:
        source_type = _DOMAIN_SOURCE_TYPE.get(domain, "CIMA")
        logger.info(
            "compliance_extractor: fetching %s chunks from fund-data-index",
            domain,
        )
        chunks_text = _fetch_domain_chunks(domain, top=top_per_domain)
        if not chunks_text.strip():
            logger.info("compliance_extractor: no chunks for domain %s", domain)
            continue
        if len(chunks_text) > 60_000:
            chunks_text = chunks_text[:60_000]
        domain_prompts.append((domain, source_type, _build_user_prompt(domain, chunks_text)))

    # Phase 2: LLM calls in parallel (thread-safe — no DB access)
    def _llm_for_domain(domain: str, user_prompt: str) -> tuple[str, list[dict[str, Any]]]:
        logger.info("compliance_extractor: calling LLM for domain %s (model=%s)", domain, model)
        try:
            result = create_completion(
                system_prompt=_get_system_prompt(),
                user_prompt=user_prompt,
                model=model,
                temperature=0.1,
                max_tokens=8192,
                response_format={"type": "json_object"},
                stage="compliance_extraction",
            )
        except Exception as exc:
            logger.error("compliance_extractor: LLM call failed for %s — %s", domain, exc)
            return domain, []
        parsed = _parse_obligations_json(result.text)
        logger.info("compliance_extractor: LLM returned %d obligations for %s", len(parsed), domain)
        return domain, parsed

    llm_results: dict[str, tuple[str, list[dict[str, Any]]]] = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_llm_for_domain, domain, prompt): (domain, source_type)
            for domain, source_type, prompt in domain_prompts
        }
        for future in as_completed(futures):
            domain, source_type = futures[future]
            try:
                _, raw_obligations = future.result()
            except Exception as exc:
                logger.error("compliance_extractor: future failed for %s — %s", domain, exc)
                raw_obligations = []
            llm_results[domain] = (source_type, raw_obligations)

    # Phase 3: Persist results — main thread (DB session is not thread-safe)
    for domain, source_type, _ in domain_prompts:
        if domain not in llm_results:
            continue
        source_type, raw_obligations = llm_results[domain]

        for raw in raw_obligations:
            name = (raw.get("name") or "").strip()
            if not name or len(name) < 3:
                continue

            # Deduplicate by name
            if name.lower().strip() in existing_names:
                logger.info(
                    "compliance_extractor: skipping duplicate '%s'",
                    name[:80],
                )
                continue

            frequency = raw.get("frequency", "ANNUAL")
            if frequency not in ("ANNUAL", "QUARTERLY", "MONTHLY", "AD_HOC"):
                frequency = "ANNUAL"

            risk_level = raw.get("risk_level", "MEDIUM")
            if risk_level not in ("HIGH", "MEDIUM", "LOW"):
                risk_level = "MEDIUM"

            next_due = _infer_next_due_date(
                raw.get("next_due_date"),
                frequency,
            )

            payload = ObligationCreate(
                name=name[:200],
                regulator=raw.get("regulator", source_type)[:64]
                if raw.get("regulator")
                else source_type,
                description=raw.get("description", ""),
                is_active=True,
                source_type=raw.get("source_type", source_type),
                frequency=frequency,
                next_due_date=next_due,
                risk_level=risk_level,
                responsible_party=raw.get("responsible_party"),
                document_reference=raw.get("document_reference"),
                legal_basis=raw.get("legal_basis"),
            )

            try:
                from app.domains.credit.modules.compliance import service

                ob = service.create_obligation(
                    db,
                    fund_id=fund_id,
                    actor=actor,
                    payload=payload,
                )
                all_created.append(ob)
                existing_names.add(name.lower().strip())
                logger.info(
                    "compliance_extractor: created obligation '%s' (id=%s)",
                    name[:80],
                    ob.id,
                )
            except Exception as exc:
                logger.warning(
                    "compliance_extractor: failed to create '%s' — %s",
                    name[:80],
                    exc,
                )

    logger.info(
        "compliance_extractor: extraction complete — %d obligations created",
        len(all_created),
    )
    return all_created
