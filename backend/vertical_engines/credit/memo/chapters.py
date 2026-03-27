"""Memo chapter generation — individual chapter production and evidence curation.

Imports models, prompts (sibling modules within memo package).

Error contract: never-raises for generation functions (orchestration engine).
generate_chapter and generate_recommendation_chapter catch all exceptions
and return degraded results with status information.
"""
from __future__ import annotations

import json
import re
from typing import Any

import structlog

from ai_engine.model_config import get_model
from ai_engine.prompts import prompt_registry
from vertical_engines.credit.memo.models import CallOpenAiFn
from vertical_engines.credit.memo.prompts import (
    _CHAPTER_CHUNK_BUDGET,
    _CHAPTER_DOC_AFFINITY,
    _CHAPTER_EXTRA_SECTIONS,
    _CHAPTER_MAX_TOKENS,
    _SHARED_PACK_SECTIONS,
)

logger = structlog.get_logger()

# Chapter tags with Jinja2 templates (chXX_name.j2 in credit/prompts/)
_CHAPTER_TAGS = (
    "ch01_exec", "ch02_macro", "ch03_exit", "ch04_sponsor", "ch05_legal",
    "ch06_terms", "ch07_capital", "ch08_returns", "ch09_downside", "ch10_covenants",
    "ch11_risks", "ch12_peers", "ch13_recommendation", "ch14_governance_stress",
)


def _get_chapter_base_prompt(chapter_tag: str, **context: Any) -> str | None:
    """Return system prompt for a chapter from the prompt registry."""
    if chapter_tag in _CHAPTER_TAGS:
        return prompt_registry.render(f"{chapter_tag}.j2", **context)
    return None


def _get_evidence_law() -> str:
    """Return the evidence law prompt."""
    return prompt_registry.render("evidence_law.j2")


def _get_evidence_law_ch13() -> str:
    """Return the Ch13-specific evidence law prompt."""
    return prompt_registry.render("evidence_law_ch13.j2")


def filter_evidence_pack(evidence_pack: dict[str, Any], chapter_tag: str) -> dict[str, Any]:
    """Return a chapter-relevant subset of the evidence pack.

    Reduces input tokens by ~60-70% per chapter by including only
    the sections needed for that specific chapter's analysis.
    Ch01 (exec summary) receives the full pack as it synthesises all.
    """
    allowed = _SHARED_PACK_SECTIONS | _CHAPTER_EXTRA_SECTIONS.get(chapter_tag, frozenset())
    return {k: v for k, v in evidence_pack.items() if k in allowed}


# ---------------------------------------------------------------------------
# Evidence pack summary (F — Cost Governance + E — Prompt Caching)
# ---------------------------------------------------------------------------

def build_evidence_summary(evidence_pack: dict[str, Any]) -> str:
    """Build a compact deterministic summary of the evidence pack.

    Deterministic (no LLM call, zero cost).  ~500-1000 tokens.
    Placed at the top of system_prompt as a shared prefix so OpenAI
    prompt caching activates across chapter calls (E).
    """
    parts: list[str] = []

    # Deal identity
    deal = evidence_pack.get("deal_identity", {})
    parts.append(f"DEAL: {deal.get('deal_name', 'N/A')}")
    parts.append(f"SPONSOR: {deal.get('sponsor_name', 'N/A')}")
    parts.append(f"BORROWER: {deal.get('borrower_name', 'N/A')}")
    parts.append(f"CURRENCY: {deal.get('currency', 'USD')}")
    parts.append(f"AMOUNT: {deal.get('requested_amount', 'N/A')}")

    # Investor identity
    inv = evidence_pack.get("investor_identity", {})
    parts.append(f"\nINVESTOR FUND: {inv.get('fund_name', 'N/A')}")
    parts.append(f"ROLE: {inv.get('role', 'N/A')}")
    disambiguation = inv.get("disambiguation_rule", "")
    if disambiguation:
        parts.append(f"DISAMBIGUATION: {disambiguation}")

    # Deal overview highlights
    overview = evidence_pack.get("deal_overview", {})
    parts.append(f"\nINSTRUMENT TYPE: {overview.get('instrumentType', 'N/A')}")
    summary_text = str(overview.get("dealSummary", "N/A"))
    parts.append(f"DEAL SUMMARY: {summary_text[:600]}")

    # Quant highlights
    quant = evidence_pack.get("quant_profile", {})
    if quant:
        parts.append("\nQUANT PROFILE:")
        for k in ("expectedReturns", "leverage", "creditMetrics",
                   "loanCharacteristics", "sensitivityResults"):
            if k in quant:
                parts.append(f"  {k}: {json.dumps(quant[k], default=str)[:300]}")

    # Terms summary
    terms = evidence_pack.get("terms_summary", {})
    if terms:
        parts.append("\nTERMS:")
        for k, v in terms.items():
            if v:
                parts.append(f"  {k}: {str(v)[:200]}")

    # Risk flags
    risks = evidence_pack.get("risk_flags", [])
    if risks:
        parts.append(f"\nRISK FLAGS ({len(risks)}):")
        for r in risks[:5]:
            parts.append(f"  - {str(r)[:150]}")

    # Policy
    policy = evidence_pack.get("policy_compliance", {})
    if policy:
        status = policy.get("overallStatus", policy.get("status", "N/A"))
        parts.append(f"\nPOLICY STATUS: {status}")
        breaches = policy.get("breaches", [])
        if breaches:
            parts.append(f"POLICY BREACHES ({len(breaches)}):")
            for b in breaches[:3]:
                parts.append(f"  - {str(b)[:150]}")

    # Macro snapshot
    macro = evidence_pack.get("macro_snapshot", {})
    if macro:
        parts.append(
            f"\nMACRO: Federal Funds={macro.get('federal_funds_rate', 'N/A')}, "
            f"10Y={macro.get('treasury_10y', 'N/A')}, "
            f"Spread={macro.get('bbb_spread', 'N/A')}",
        )

    # Sponsor
    sponsor = evidence_pack.get("sponsor_analysis", {})
    if sponsor:
        parts.append(f"\nSPONSOR ANALYSIS: {str(sponsor.get('sponsor_summary', 'N/A'))[:300]}")

    return "\n".join(parts)


def select_chapter_chunks(
    evidence_map: list[dict[str, Any]],
    chapter_tag: str,
    *,
    max_chunks: int | None = None,
    max_chars_per_chunk: int | None = None,
    min_unique_docs: int = 4,
) -> list[dict[str, Any]]:
    """Select the most relevant evidence chunks for a chapter.

    Per-chapter budgets (B — Cost Governance):
    - Critical chapters (ch05, ch06, ch14): 30 chunks × 8000 chars
    - Analytical chapters: 15-20 chunks × 4000 chars
    - Lightweight chapters (ch02, ch03, ch12): 10 chunks × 3000 chars
    - Document diversity enforcement: at least min_unique_docs sources.
    - Affinity-scored: chapter-relevant doc_types ranked higher.
    """
    if chapter_tag == "ch13_recommendation":
        return []  # Synthesis-only — no evidence chunks

    budget = _CHAPTER_CHUNK_BUDGET.get(chapter_tag, (20, 4000))
    if max_chunks is None:
        max_chunks = budget[0]
    if max_chars_per_chunk is None:
        max_chars_per_chunk = budget[1]

    # --- BUG-3 FIX: Forced source documents for Chapter 14 ---
    _CH14_FORCED_SOURCES = frozenset({
        "credit_policy.pdf",
        "investment_policy.pdf",
        "IMA - Netz Private Credit Fund - FINAL.pdf",
        "MutualFundsAct2021Revision",
    })

    forced: list[dict] = []
    remaining: list[dict] = list(evidence_map)

    if chapter_tag == "ch14_governance_stress":
        keep: list[dict] = []
        for chunk in remaining:
            blob = chunk.get("blob_name", chunk.get("title", ""))
            blob_lower = (blob or "").lower()
            if any(src.lower() in blob_lower for src in _CH14_FORCED_SOURCES):
                forced.append(dict(chunk))
            else:
                keep.append(chunk)
        remaining = keep

    affinity = _CHAPTER_DOC_AFFINITY.get(chapter_tag, frozenset())

    scored: list[tuple[int, dict]] = []
    for chunk in remaining:
        raw_type = chunk.get("doc_type") or ""
        score = 3 if (raw_type in affinity or raw_type.upper() in affinity) else 1
        scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)

    selected: list[dict] = list(forced)
    seen_docs: set[str] = {
        (c.get("blob_name", c.get("title", "")) or "") for c in forced
    }

    # First pass: one chunk per unique document (highest scored first)
    for _score, chunk in scored:
        blob = chunk.get("blob_name", chunk.get("title", ""))
        if blob and blob not in seen_docs:
            selected.append(dict(chunk))
            seen_docs.add(blob)
            if len(selected) >= max_chunks:
                break

    # Second pass: fill remaining slots with highest-scored chunks
    if len(selected) < max_chunks:
        selected_ids = {id(c) for c in selected}
        for _score, chunk in scored:
            if id(chunk) not in selected_ids:
                selected.append(dict(chunk))
                if len(selected) >= max_chunks:
                    break

    # Trim chunk content to max_chars_per_chunk
    for chunk in selected:
        content = chunk.get("content", "")
        if len(content) > max_chars_per_chunk:
            chunk["content"] = content[:max_chars_per_chunk]

    return selected


# ---------------------------------------------------------------------------
# Single chapter generation
# ---------------------------------------------------------------------------

def generate_chapter(
    *,
    chapter_num: int,
    chapter_tag: str,
    chapter_title: str,
    evidence_pack: dict[str, Any],
    evidence_chunks: list[dict[str, Any]],
    call_openai_fn: CallOpenAiFn,
    model: str | None = None,
    evidence_summary: str | None = None,
    prepare_only: bool = False,
) -> dict[str, Any]:
    """Generate a single memo chapter.

    Returns dict with at least ``section_text``.  Ch13 also has
    ``recommendation`` and ``confidence_level``.
    """
    # Extract deal_structure for Jinja2 template branching
    deal_identity = evidence_pack.get("deal_identity", {})
    role_map = deal_identity.get("deal_role_map") or (
        evidence_pack.get("investor_identity", {}).get("deal_role_map", {})
    )
    deal_structure = (role_map or {}).get("deal_structure", "unknown")

    base_prompt = _get_chapter_base_prompt(chapter_tag, deal_structure=deal_structure)
    if not base_prompt:
        raise ValueError(f"No system prompt for chapter tag: {chapter_tag}")

    evidence_law = _get_evidence_law()
    if evidence_summary:
        system_prompt = (
            "=== DEAL CONTEXT SUMMARY (shared reference) ===\n"
            + evidence_summary
            + "\n\n=== CHAPTER INSTRUCTIONS ===\n"
            + base_prompt
            + evidence_law
        )
    else:
        system_prompt = base_prompt + evidence_law

    # ── Evidence pack filtering (D): chapter-relevant subset only ──
    filtered_pack = filter_evidence_pack(evidence_pack, chapter_tag)

    # Build user content
    parts: list[str] = []

    # ── Deal Structure Preamble ──────────────────────────────────
    if role_map:
        preamble_lines = [
            "╔══════════════════════════════════════════════════════════╗",
            "║  DEAL STRUCTURE PREAMBLE — READ BEFORE ALL EVIDENCE     ║",
            "╚══════════════════════════════════════════════════════════╝",
            "",
        ]
        structure = role_map.get("deal_structure", "unknown")
        if structure == "direct_loan":
            borrower = role_map.get("borrower", "unknown")
            lender = role_map.get("lender", "unknown")
            preamble_lines += [
                "DEAL STRUCTURE: DIRECT LOAN (not a fund investment)",
                f"BORROWER (deal target): {borrower}",
                f"LENDER (investor side — Netz subsidiary): {lender}",
                "",
                "RULES:",
                f"  • {borrower} is the BORROWER — the entity receiving the loan.",
                f"  • {lender} is the LENDER — the Netz subsidiary deploying capital.",
                "  • There is NO external manager or sponsor in this deal.",
                "  • NEVER reverse these roles. NEVER call the lender 'Borrower'.",
                "  • NEVER list lender directors/officers as deal key persons.",
                "  • The IC evaluates whether to approve this loan to the borrower.",
            ]
        elif structure == "fund_investment":
            manager = role_map.get("manager", "unknown")
            preamble_lines += [
                "DEAL STRUCTURE: FUND INVESTMENT",
                f"EXTERNAL MANAGER/SPONSOR: {manager}",
                "",
                "RULES:",
                f"  • {manager} is the EXTERNAL sponsor managing the target vehicle.",
                "  • Netz entities are on the INVESTOR side, NOT the sponsor.",
                "  • The IC evaluates whether to invest in the vehicle managed by the sponsor.",
            ]
        else:
            note = role_map.get("note", "")
            preamble_lines.append(f"DEAL STRUCTURE: {structure}")
            if note:
                preamble_lines.append(f"NOTE: {note}")

        # ── Third-party counterparty attribution block ───────────
        third_parties = (
            evidence_pack.get("investor_identity", {}).get("third_party_counterparties")
            or deal_identity.get("third_party_counterparties")
            or []
        )
        if third_parties:
            preamble_lines += [
                "",
                "╔═══════════════════════════════════════════════════════════════╗",
                "║  THIRD-PARTY DOCUMENT ATTRIBUTION — CRITICAL                 ║",
                "╚═══════════════════════════════════════════════════════════════╝",
                "",
                "The evidence corpus contains documents from OTHER counterparties",
                "that have SEPARATE, PRE-EXISTING contracts with the borrower.",
                "Their terms must NEVER be presented as the deal under review.",
                "",
            ]
            for tp in third_parties:
                tp_name = tp.get("name", "unknown")
                tp_role = tp.get("role", "")
                tp_docs = tp.get("documents", [])
                tp_ucc = tp.get("ucc_filings", [])
                tp_terms = tp.get("terms_belong_to_this_counterparty", [])
                tp_relevance = tp.get("ic_relevance", "")
                preamble_lines.append(f"  COUNTERPARTY: {tp_name}")
                if tp_role:
                    preamble_lines.append(f"  ROLE: {tp_role}")
                if tp_docs:
                    preamble_lines.append(f"  DOCUMENTS: {', '.join(tp_docs)}")
                if tp_ucc:
                    preamble_lines.append(f"  UCC FILINGS: {', '.join(tp_ucc)}")
                if tp_terms:
                    preamble_lines.append("  TERMS BELONGING TO THIS COUNTERPARTY (NOT the deal):")
                    for term in tp_terms:
                        preamble_lines.append(f"    - {term}")
                if tp_relevance:
                    preamble_lines.append(f"  IC RELEVANCE: {tp_relevance}")
                preamble_lines += [
                    "",
                    "  ATTRIBUTION RULES:",
                    "  • When a source document matches any filename above,",
                    "    its terms belong to THIS counterparty — NOT the deal under review.",
                    "  • Present these as 'Existing Debt / Prior Liens' (risk/diligence).",
                    "  • NEVER populate the deal terms table with values from these documents.",
                    "  • UCC filings from these counterparties show existing liens on the",
                    "    borrower's assets — treat as subordination / competing claims risk.",
                    "",
                ]

        preamble_lines.append("")
        parts.append("\n".join(preamble_lines))

    parts.append("=== MEMO EVIDENCE PACK (filtered for this chapter) ===")
    parts.append(json.dumps(filtered_pack, indent=2, default=str))

    if evidence_chunks:
        parts.append("\n\n=== RELEVANT EVIDENCE CHUNKS ===")
        for i, chunk in enumerate(evidence_chunks, 1):
            chunk_id = chunk.get("chunk_id") or chunk.get("blob_name", f"chunk_{i}")
            blob = chunk.get("blob_name", "unknown")
            doc_type = chunk.get("doc_type", "")
            content = chunk.get("content", "")
            parts.append(
                f"\n--- Chunk {i} | chunk_id: {chunk_id}"
                f" | doc_type: {doc_type} | source: {blob} ---",
            )
            parts.append(content)

    user_content = "\n".join(parts)
    max_tokens = _CHAPTER_MAX_TOKENS.get(chapter_tag, 4000)

    # ── Batch mode: return prepared messages without calling the LLM ──
    if prepare_only:
        return {
            "system_prompt": system_prompt,
            "user_content": user_content,
            "max_tokens": max_tokens,
        }

    logger.info(
        "CHAPTER_GENERATE_START",
        chapter=chapter_num,
        tag=chapter_tag,
        user_chars=len(user_content),
        system_chars=len(system_prompt),
        evidence_chunks=len(evidence_chunks),
        pack_sections=len(filtered_pack),
        max_tokens=max_tokens,
        has_summary_prefix=bool(evidence_summary),
    )

    try:
        data = call_openai_fn(system_prompt, user_content, max_tokens=max_tokens, model=model)
    except Exception as exc:
        logger.error("CHAPTER_GENERATE_FAILED", chapter=chapter_num, tag=chapter_tag, error=str(exc), exc_info=True)
        return {
            "section_text": f"*Chapter {chapter_num}: {chapter_title} — generation failed: {exc}*",
            "citations": [],
            "status": "NOT_ASSESSED",
        }

    section_text = data.get("section_text", "")
    section_text = section_text.replace("\x00", "")
    citations = data.get("citations", [])
    charts = data.get("charts", [])
    omitted_sections = data.get("omitted_sections", [])
    critical_gaps = data.get("critical_gaps", [])

    if not section_text.strip():
        section_text = f"*Chapter {chapter_num}: {chapter_title} — LLM returned empty.*"

    if charts:
        from ai_engine.pdf.chart_renderer import inject_chart_data_into_text
        section_text = inject_chart_data_into_text(section_text, charts)

    logger.info(
        "CHAPTER_GENERATE_COMPLETE",
        chapter=chapter_num,
        tag=chapter_tag,
        output_chars=len(section_text),
        citations_count=len(citations),
        charts_count=len(charts),
        critical_gaps_count=len(critical_gaps),
    )

    result: dict[str, Any] = {
        "section_text": section_text,
        "citations": citations,
        "charts": charts,
        "omitted_sections": omitted_sections,
        "critical_gaps": critical_gaps,
    }
    if chapter_tag == "ch13_recommendation":
        result["recommendation"] = data.get("recommendation", "CONDITIONAL")
        result["confidence_level"] = data.get("confidence_level", "MEDIUM")

    return result


# ---------------------------------------------------------------------------
# Recommendation chapter (synthesis-only)
# ---------------------------------------------------------------------------

def generate_recommendation_chapter(
    *,
    evidence_pack: dict[str, Any],
    quant_summary: dict[str, Any],
    critic_findings: dict[str, Any],
    policy_breaches: dict[str, Any],
    sponsor_red_flags: list[dict[str, Any]],
    call_openai_fn: CallOpenAiFn,
    model: str | None = None,
    decision_anchor: dict[str, Any] | None = None,
    chapter_summaries: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Generate Chapter 13 — Final Recommendation — from synthesis inputs.

    When ``decision_anchor`` is provided, the recommendation is BINDING.
    """
    base_prompt = _get_chapter_base_prompt("ch13_recommendation") or ""

    if decision_anchor:
        _flaws = ", ".join(decision_anchor.get("confirmedFatalFlaws", [])) or "None"
        _breaches = ", ".join(decision_anchor.get("hardBreaches", [])) or "None"
        _gaps = json.dumps(decision_anchor.get("diligenceGaps", []))
        anchor_rule = (
            "\n\n=== DECISION ANCHOR (BINDING) ===\n"
            f"finalDecision: {decision_anchor['finalDecision']}\n"
            f"icGate: {decision_anchor['icGate']}\n"
            f"policyStatus: {decision_anchor['policyStatus']}\n"
            f"hardBreaches: {_breaches}\n"
            f"confirmedFatalFlaws: {_flaws}\n"
            f"diligenceGaps: {_gaps}\n"
            f"\n"
            f"Confirmed fatal flaws are BLOCKERS.\n"
            f"Diligence gaps are NOT blockers unless explicitly stated.\n"
            f"Your 'recommendation' field MUST be \"{decision_anchor['finalDecision']}\".\n"
            f"Your role is to EXPLAIN and JUSTIFY — you do NOT re-adjudicate.\n"
            f"If you analytically disagree, note tension but maintain the binding decision.\n"
            f"=============================================\n"
        )
        base_prompt = anchor_rule + "\n" + base_prompt

    system_prompt = base_prompt + _get_evidence_law_ch13()

    parts: list[str] = [
        "=== MEMO EVIDENCE PACK (frozen truth source) ===",
        json.dumps(evidence_pack, indent=2, default=str),
        "\n\n=== QUANTITATIVE PROFILE SUMMARY ===",
        json.dumps(quant_summary, indent=2, default=str),
        "\n\n=== CRITIC FINDINGS (adversarial review) ===",
        json.dumps(critic_findings, indent=2, default=str),
        "\n\n=== POLICY COMPLIANCE ===",
        json.dumps(policy_breaches, indent=2, default=str),
    ]

    if decision_anchor:
        parts.append("\n\n=== DECISION ANCHOR (authoritative) ===")
        parts.append(json.dumps(decision_anchor, indent=2, default=str))

    if sponsor_red_flags:
        parts.append("\n\n=== SPONSOR RED FLAGS ===")
        parts.append(json.dumps(sponsor_red_flags, indent=2, default=str))

    if chapter_summaries:
        parts.append("\n\n=== CHAPTER SUMMARIES (ch01-ch12) ===")
        for ch_tag in sorted(chapter_summaries):
            parts.append(f"\n--- {ch_tag} ---\n{chapter_summaries[ch_tag]}")

    user_content = "\n".join(parts)

    logger.info("RECOMMENDATION_CHAPTER_START", user_chars=len(user_content))

    try:
        data = call_openai_fn(system_prompt, user_content, max_tokens=3000, model=model)
    except Exception as exc:
        logger.error("RECOMMENDATION_CHAPTER_FAILED", error=str(exc), exc_info=True)
        return {
            "section_text": f"*Final Recommendation — generation failed: {exc}*",
            "recommendation": "CONDITIONAL",
            "confidence_level": "LOW",
            "status": "NOT_ASSESSED",
        }

    rec = data.get("recommendation", "CONDITIONAL")
    if decision_anchor:
        rec = decision_anchor["finalDecision"]

    _rec_text = data.get("section_text", "*Recommendation generation returned empty.*")
    _rec_text = _rec_text.replace("\x00", "")
    result = {
        "section_text": _rec_text,
        "recommendation": rec,
        "confidence_level": data.get("confidence_level", "MEDIUM"),
        "citations": data.get("citations", []),
    }

    logger.info(
        "RECOMMENDATION_CHAPTER_COMPLETE",
        recommendation=result["recommendation"],
        confidence_level=result["confidence_level"],
    )

    return result


# ---------------------------------------------------------------------------
# Appendix builders
# ---------------------------------------------------------------------------

def _build_appendix_1(all_citations: list[dict[str, Any]]) -> str:
    """Build **Appendix 1 — Source Index** from accumulated citations."""
    source_map: dict[str, dict[str, Any]] = {}
    for cit in all_citations:
        cid = cit.get("chunk_id", "UNKNOWN")
        if cid == "NONE":
            continue
        if cid not in source_map:
            source_map[cid] = {
                "source_name": cit.get("source_name", "N/A"),
                "doc_type": cit.get("doc_type", "N/A"),
                "excerpt": (cit.get("excerpt") or "")[:120],
                "page": cit.get("page"),
                "chapters": set(),
            }
        source_map[cid]["chapters"].add(cit.get("chapter_number", 0))

    if not source_map:
        return (
            "## Appendix 1 — Source Index\n\n"
            "*No source-backed citations were generated.  "
            "Self-audit FAIL — review pipeline evidence inputs.*"
        )

    lines: list[str] = [
        "## Appendix 1 — Source Index",
        "",
        "| # | Chunk ID | Source | Doc Type | Chapters | Excerpt | Page |",
        "|---|----------|--------|----------|----------|---------|------|",
    ]

    for ref_num, (cid, info) in enumerate(source_map.items(), 1):
        source = (info["source_name"] or "N/A")[:60]
        doc_type = (info["doc_type"] or "N/A")[:30]
        chapters = ", ".join(f"Ch{n}" for n in sorted(info["chapters"]))
        excerpt = (info["excerpt"] or "").replace("|", "\\|").replace("\n", " ")[:80]
        page = info["page"] or "—"
        cid_display = cid[:70] if len(cid) > 70 else cid
        lines.append(
            f"| {ref_num} | {cid_display} | {source} | {doc_type}"
            f" | {chapters} | {excerpt} | {page} |",
        )

    lines.append("")
    lines.append(f"**Total unique sources cited: {len(source_map)}**")
    return "\n".join(lines)


def _build_appendix_2(all_critical_gaps: list[dict[str, Any]]) -> str:
    """Build **Appendix 2 — Data Gaps Register** from accumulated critical gaps."""
    if not all_critical_gaps:
        return ""

    lines: list[str] = [
        "## Appendix 2 — Data Gaps Register",
        "",
        "_The following critical data gaps were identified during memo generation. "
        "Each gap may block IC approval and must be resolved prior to final committee presentation._",
        "",
        "| # | Chapter | Gap Description |",
        "|---|---------|-----------------|",
    ]

    for i, entry in enumerate(all_critical_gaps, 1):
        ch_num = entry.get("chapter_num", "?")
        ch_title = (entry.get("chapter_title") or "")[:50]
        raw_gap = entry.get("gap") or ""
        if isinstance(raw_gap, dict):
            raw_gap = raw_gap.get("description") or raw_gap.get("gap") or str(raw_gap)
        gap = str(raw_gap).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {i} | Ch{ch_num} — {ch_title} | {gap} |")

    lines.append("")
    lines.append(f"**Total critical gaps: {len(all_critical_gaps)}**")
    return "\n".join(lines)


def _extract_recommendation_from_text(text: str) -> tuple[str, str]:
    """Best-effort extraction of recommendation from cached chapter text."""
    rec = "CONDITIONAL"
    conf = "MEDIUM"
    for pattern in (r"recommendation[:\s]*(INVEST|PASS|CONDITIONAL)", r"\b(INVEST|PASS|CONDITIONAL)\b"):
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            rec = m.group(1).upper()
            break
    for pattern in (r"confidence[:\s]*(HIGH|MEDIUM|LOW)",):
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            conf = m.group(1).upper()
            break
    return rec, conf


def regenerate_chapter_with_critic(
    *,
    ch_tag: str,
    original_text: str,
    critic_addendum: str,
    evidence_pack: dict[str, Any],
    call_openai_fn: CallOpenAiFn,
) -> str | None:
    """Regenerate a single chapter incorporating critic findings.

    Returns the revised section_text, or None if regeneration fails.
    """
    prompt_template = _get_chapter_base_prompt(ch_tag)
    if not prompt_template:
        logger.warning("regenerate_chapter_with_critic: no prompt for %s", ch_tag)
        return None

    system = (
        f"{prompt_template}\n\n"
        "IMPORTANT: This is a REVISION pass. The IC Critic found issues with the "
        "original chapter. You MUST address the findings below while preserving "
        "all factual content and evidence citations from the original.\n\n"
        f"{critic_addendum}"
    )

    user = (
        f"ORIGINAL CHAPTER TEXT:\n{original_text[:12_000]}\n\n"
        f"EVIDENCE PACK:\n{json.dumps(evidence_pack.get('deal_overview', {}), default=str)[:4_000]}\n\n"
        "Rewrite this chapter addressing the critic findings. "
        'Return JSON: {{"section_text": "...revised markdown..."}}'
    )

    try:
        model = get_model(ch_tag) if ch_tag in _CHAPTER_TAGS else get_model("memo")
        result = call_openai_fn(system, user, model=model, max_tokens=4096)
        text = result.text if hasattr(result, "text") else str(result)
        data = json.loads(text)
        revised = data.get("section_text", "")
        if revised and len(revised) > 200:
            logger.info("regenerate_chapter_with_critic", ch_tag=ch_tag, revised_chars=len(revised))
            return revised
    except Exception:
        logger.exception("regenerate_chapter_with_critic failed", ch_tag=ch_tag)
    return None
