"""Domain-aware AI analysis service.

After documents are indexed, this module performs domain-specific AI analysis:

- PIPELINE mode -> research output (investment thesis, risk map, etc.)
- PORTFOLIO mode -> monitoring output (covenant flags, performance alerts, etc.)

Uses hybrid retrieval (BM25 + vector) from global-vector-chunks-v2
before calling GPT-4o for structured analysis.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from sqlalchemy.orm import Session

from ai_engine.extraction.embedding_service import generate_embeddings
from ai_engine.extraction.search_upsert_service import search_deal_chunks
from ai_engine.prompts import prompt_registry
from app.domains.credit.modules.deals.ai_mode import AIMode

logger = structlog.get_logger()

# ── Context retrieval ─────────────────────────────────────────────────


def _retrieve_context(
    deal_id: uuid.UUID,
    deal_name: str,
    *,
    organization_id: uuid.UUID | str,
    max_chunks: int = 20,
) -> str:
    """Hybrid retrieval: embed the deal name as query vector + BM25 text search.

    NOTE: pipeline_engine._retrieve_deal_context() performs a similar
    embed+search flow but with institutional-scale parameters (80 chunks,
    authority enrichment, curated surfaces).  This lighter version is
    intentionally kept separate for PORTFOLIO monitoring which needs
    fewer chunks and no chapter-level curation.
    """
    try:
        query_text = f"{deal_name} credit analysis risk assessment"
        emb = generate_embeddings([query_text])
        query_vector = emb.vectors[0] if emb.vectors else None
    except Exception:
        logger.warning("domain_ai.retrieve_context.embedding_failed")
        query_vector = None
        query_text = deal_name

    try:
        chunks = search_deal_chunks(
            deal_id=deal_id,
            organization_id=organization_id,
            query_text=query_text,
            query_vector=query_vector,
            top=max_chunks,
        )
    except Exception:
        logger.warning("domain_ai.retrieve_context.search_failed", deal_id=str(deal_id), exc_info=True)
        return ""

    if not chunks:
        return ""

    context_parts: list[str] = []
    for chunk in chunks:
        header = f"[{chunk.get('doc_type', 'unknown')} | pages {chunk.get('page_start', '?')}-{chunk.get('page_end', '?')}]"
        context_parts.append(f"{header}\n{chunk.get('content', '')}")

    return "\n\n---\n\n".join(context_parts)


# ── GPT call ──────────────────────────────────────────────────────────


def _call_gpt(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    """Call GPT via the centralised openai_client and parse JSON output."""
    import json as _json

    from ai_engine.openai_client import create_completion

    result = create_completion(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.2,
        max_tokens=8192,
        response_format={"type": "json_object"},
    )
    text = (result.text or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    obj = _json.loads(text)
    if isinstance(obj, dict):
        meta = obj.get("_meta")
        if not isinstance(meta, dict):
            meta = {}
        meta.setdefault("engine", "domain_ai_engine")
        meta.setdefault("modelVersion", result.model)
        obj["_meta"] = meta
    return obj


# ── Pipeline analysis ─────────────────────────────────────────────────


def run_pipeline_analysis(
    db: Session,
    *,
    deal_id: uuid.UUID,
    fund_id: uuid.UUID,
    deal_name: str,
    sponsor_name: str | None,
    organization_id: uuid.UUID | str | None = None,
) -> dict[str, Any]:
    """Run PIPELINE-mode AI analysis.

    Delegates to the consolidated pipeline engine which performs a single
    RAG + GPT pass and writes both research_output AND derived summary columns.
    """
    from vertical_engines.credit.pipeline import generate_pipeline_intelligence

    return generate_pipeline_intelligence(
        db,
        deal_id=deal_id,
        deal_name=deal_name,
        sponsor_name=sponsor_name,
        fund_id=fund_id,
        organization_id=organization_id,
    )


# ── Portfolio analysis ────────────────────────────────────────────────


def run_portfolio_analysis(
    db: Session,
    *,
    deal_id: uuid.UUID,
    fund_id: uuid.UUID,
    deal_name: str,
    sponsor_name: str | None,
    organization_id: uuid.UUID | str,
) -> dict[str, Any]:
    """Run PORTFOLIO-mode AI analysis: monitoring output.

    Retrieves indexed chunks + cashflow data, calls GPT, writes result to deals.
    """
    context = _retrieve_context(deal_id, deal_name, organization_id=organization_id)

    # Fetch cashflow and performance data
    cashflow_summary, performance_summary = _get_portfolio_financials(db, deal_id=deal_id, fund_id=fund_id)

    if not context and not cashflow_summary:
        logger.info("domain_ai.portfolio_analysis.skipped", deal_id=str(deal_id))
        return {}

    system = prompt_registry.render(
        "domain_portfolio.j2",
        deal_name=deal_name,
        sponsor_name=sponsor_name or "Unknown",
        cashflow_summary=cashflow_summary or "No cashflows recorded yet.",
        performance_summary=performance_summary or "No performance data available.",
    )
    user = f"Document excerpts:\n\n{context}" if context else "No document excerpts available. Analyze based on financial data only."

    try:
        output = _call_gpt(system, user)
    except Exception:
        logger.error("domain_ai.portfolio_analysis.gpt_failed", deal_id=str(deal_id), exc_info=True)
        return {}

    # Writeback to deals
    _write_portfolio_output(db, deal_id=deal_id, data=output)
    return output


def _get_portfolio_financials(
    db: Session,
    *,
    deal_id: uuid.UUID,
    fund_id: uuid.UUID,
) -> tuple[str, str]:
    """Retrieve cashflow and performance summaries for the AI prompt."""
    try:
        from app.domains.credit.modules.deals.cashflow_service import (
            calculate_performance,
            list_cashflows,
        )

        cashflows = list_cashflows(db, fund_id=fund_id, deal_id=deal_id, limit=50)
        if not cashflows:
            return "", ""

        cf_lines = []
        for cf in cashflows:
            cf_lines.append(
                f"  {cf.flow_date} | {cf.flow_type} | {cf.currency} {float(cf.amount):,.2f}"
                + (f" | {cf.description}" if cf.description else ""),
            )
        cashflow_summary = "\n".join(cf_lines)

        perf = calculate_performance(db, fund_id=fund_id, deal_id=deal_id)
        perf_lines = [
            f"Total invested: {perf['total_invested']:,.2f}",
            f"Total received: {perf['total_received']:,.2f}",
            f"Net cashflow: {perf['net_cashflow']:,.2f}",
        ]
        if perf.get("moic") is not None:
            perf_lines.append(f"MOIC: {perf['moic']:.4f}x")
        if perf.get("cash_to_cash_days") is not None:
            perf_lines.append(f"Cash-to-cash: {perf['cash_to_cash_days']} days")
        performance_summary = "\n".join(perf_lines)

        return cashflow_summary, performance_summary

    except Exception:
        logger.warning("domain_ai.portfolio_financials.failed", deal_id=str(deal_id), exc_info=True)
        return "", ""


def _write_portfolio_output(db: Session, *, deal_id: uuid.UUID, data: dict[str, Any]) -> None:
    """Write monitoring output to deals.monitoring_output JSONB."""
    _write_jsonb_column(db, table="deals", column="monitoring_output", entity_id=deal_id, data=data)
    logger.info("domain_ai.portfolio_output_written", deal_id=str(deal_id))


# ── Shared JSONB writer ──────────────────────────────────────────────


# Allowed table/column pairs for JSONB writes — prevents SQL injection
_ALLOWED_JSONB_TARGETS: dict[str, set[str]] = {
    "pipeline_deals": {"research_output", "monitoring_output"},
    "deals": {"research_output", "monitoring_output"},
}


def _write_jsonb_column(
    db: Session,
    *,
    table: str,
    column: str,
    entity_id: uuid.UUID,
    data: dict[str, Any],
) -> None:
    """JSONB column writer with allow-list validation."""
    from sqlalchemy import text

    allowed_cols = _ALLOWED_JSONB_TARGETS.get(table)
    if allowed_cols is None or column not in allowed_cols:
        logger.error(
            "domain_ai.jsonb_write_blocked",
            table=table,
            column=column,
        )
        return

    # table/column are now guaranteed to be in the allow-list
    try:
        db.execute(
            text(f"UPDATE {table} SET {column} = :data WHERE id = :id"),  # noqa: S608
            {"data": json.dumps(data), "id": str(entity_id)},
        )
        db.flush()
    except Exception:
        logger.debug("domain_ai.jsonb_column_missing", table=table, column=column, exc_info=True)


# ── Unified entrypoint ───────────────────────────────────────────────


def run_deal_ai_analysis(
    db: Session,
    *,
    deal_id: uuid.UUID,
    fund_id: uuid.UUID,
    domain: str,
    deal_name: str,
    sponsor_name: str | None = None,
    organization_id: uuid.UUID | str | None = None,
) -> dict[str, Any]:
    """Unified entrypoint for domain-aware AI analysis."""
    if domain == AIMode.PIPELINE or domain == "pipeline":
        return run_pipeline_analysis(
            db, deal_id=deal_id, fund_id=fund_id, deal_name=deal_name, sponsor_name=sponsor_name,
            organization_id=organization_id,
        )
    elif domain == AIMode.PORTFOLIO or domain == "portfolio":
        return run_portfolio_analysis(
            db, deal_id=deal_id, fund_id=fund_id, deal_name=deal_name, sponsor_name=sponsor_name,
            organization_id=organization_id,
        )
    else:
        raise ValueError(f"Unknown domain: {domain}")
