"""Chapter generation — per-chapter LLM calls for DD Reports.

Generates individual chapters using evidence pack context + Jinja2 prompts.
Each chapter call is bounded by per-chapter timeout (30s default).
Sanitizes all LLM output before returning.
"""

from __future__ import annotations

from typing import Any

import structlog

from ai_engine.governance.output_safety import sanitize_llm_text
from ai_engine.prompts.registry import get_prompt_registry
from vertical_engines.wealth.dd_report.evidence_pack import EvidencePack
from vertical_engines.wealth.dd_report.models import CHAPTER_REGISTRY, ChapterResult
from vertical_engines.wealth.shared_protocols import CallOpenAiFn

logger = structlog.get_logger()

# Template subdirectory for DD chapter prompts
_TEMPLATE_PREFIX = "dd_chapters"


def _get_chapter_def(tag: str) -> dict[str, Any] | None:
    """Look up chapter definition by tag."""
    return next((ch for ch in CHAPTER_REGISTRY if ch["tag"] == tag), None)


def generate_chapter(
    call_openai_fn: CallOpenAiFn,
    *,
    chapter_tag: str,
    evidence_context: dict[str, Any],
    chapter_summaries: dict[str, str] | None = None,
    evidence_pack: EvidencePack | None = None,
) -> ChapterResult:
    """Generate a single DD Report chapter via LLM.

    Never raises — returns a ChapterResult with status='failed' on error.

    Parameters
    ----------
    call_openai_fn : CallOpenAiFn
        Injected LLM call function.
    chapter_tag : str
        Chapter identifier (e.g., 'executive_summary').
    evidence_context : dict
        Filtered evidence pack context for this chapter.
    chapter_summaries : dict
        For recommendation chapter: summaries of chapters 1-7.

    Returns
    -------
    ChapterResult
        Generated chapter content (frozen dataclass).

    """
    ch_def = _get_chapter_def(chapter_tag)
    if not ch_def:
        return ChapterResult(
            tag=chapter_tag, order=0, title="Unknown",
            content_md=None, status="failed",
            error=f"Unknown chapter tag: {chapter_tag}",
        )

    try:
        registry = get_prompt_registry()
        template_name = f"{_TEMPLATE_PREFIX}/{chapter_tag}.j2"

        # Build template context
        ctx = {**evidence_context}
        if chapter_summaries:
            ctx["chapter_summaries"] = chapter_summaries

        # Inject source-aware metadata for template preambles
        if evidence_pack is not None:
            ctx.update(evidence_pack.compute_source_metadata(chapter_tag))

        # Render prompt
        if registry.has_template(template_name):
            system_prompt = registry.render(template_name, **ctx)
        else:
            # Fallback: basic prompt if template not yet registered
            system_prompt = (
                f"You are a senior investment analyst writing the "
                f"'{ch_def['title']}' chapter of a fund due diligence report.\n\n"
                f"Write a thorough, institutional-quality analysis in markdown."
            )

        user_content = _build_user_content(chapter_tag, evidence_context)

        # Call LLM in text mode (chapters produce markdown, not JSON)
        from ai_engine.llm import call_openai_text

        raw_content = call_openai_text(
            system_prompt,
            user_content,
            max_tokens=ch_def["max_tokens"],
        )

        # Sanitize LLM output (6-stage pipeline)
        content_md = sanitize_llm_text(raw_content) if raw_content else None

        logger.info(
            "chapter_generated",
            chapter_tag=chapter_tag,
            content_length=len(content_md) if content_md else 0,
        )

        return ChapterResult(
            tag=chapter_tag,
            order=ch_def["order"],
            title=ch_def["title"],
            content_md=content_md,
            evidence_refs={"documents_used": len(evidence_context.get("documents", []))},
            quant_data=evidence_context.get("quant_profile", {}),
            status="completed",
        )

    except Exception as exc:
        logger.exception("chapter_generation_failed", chapter_tag=chapter_tag)
        return ChapterResult(
            tag=chapter_tag,
            order=ch_def["order"],
            title=ch_def["title"],
            content_md=None,
            status="failed",
            error=str(exc),
        )


def _build_user_content(
    chapter_tag: str,
    evidence_context: dict[str, Any],
) -> str:
    """Build the user message content from evidence context."""
    parts: list[str] = []

    # Fund identity
    parts.append(f"Fund: {evidence_context.get('fund_name', 'Unknown')}")
    if evidence_context.get("isin"):
        parts.append(f"ISIN: {evidence_context['isin']}")
    if evidence_context.get("manager_name"):
        parts.append(f"Manager: {evidence_context['manager_name']}")

    # Quant metrics for relevant chapters
    quant = evidence_context.get("quant_profile", {})
    if quant and chapter_tag in (
        "executive_summary", "performance_analysis", "risk_framework", "recommendation",
    ):
        parts.append("\n## Quantitative Metrics")
        for key, val in quant.items():
            if val is not None and key != "score_components":
                parts.append(f"- {key}: {val}")

    # Prospectus data for performance and fee chapters
    prospectus_stats = evidence_context.get("prospectus_stats", {})
    if prospectus_stats.get("prospectus_stats_available"):
        if chapter_tag == "performance_analysis":
            prospectus_returns = evidence_context.get("prospectus_returns", [])
            if prospectus_returns:
                parts.append("\n## Prospectus Annual Returns (SEC RR1)")
                for r in prospectus_returns:
                    parts.append(f"- {r['year']}: {r['annual_return_pct']:.2f}%")
            if prospectus_stats.get("avg_annual_return_1y") is not None:
                parts.append("\n## Prospectus Average Annual Returns")
                parts.append(f"- 1 Year: {prospectus_stats['avg_annual_return_1y']:.2f}%")
                if prospectus_stats.get("avg_annual_return_5y") is not None:
                    parts.append(f"- 5 Years: {prospectus_stats['avg_annual_return_5y']:.2f}%")
                if prospectus_stats.get("avg_annual_return_10y") is not None:
                    parts.append(f"- 10 Years: {prospectus_stats['avg_annual_return_10y']:.2f}%")

    if chapter_tag == "performance_analysis":
        parts.extend(_render_attribution_block(evidence_context))

        if chapter_tag == "fee_analysis":
            parts.append("\n## Prospectus Fee Table (SEC RR1)")
            if prospectus_stats.get("expense_ratio_pct") is not None:
                parts.append(f"- Total Expenses: {prospectus_stats['expense_ratio_pct']:.4f}%")
            if prospectus_stats.get("net_expense_ratio_pct") is not None:
                parts.append(f"- Net Expenses: {prospectus_stats['net_expense_ratio_pct']:.4f}%")
            if prospectus_stats.get("management_fee_pct") is not None:
                parts.append(f"- Management Fee: {prospectus_stats['management_fee_pct']:.4f}%")
            if prospectus_stats.get("fee_waiver_pct") is not None:
                parts.append(f"- Fee Waiver: {prospectus_stats['fee_waiver_pct']:.4f}%")
            if prospectus_stats.get("expense_example_1y") is not None:
                parts.append(f"- Expense Example 1Y: ${prospectus_stats['expense_example_1y']:.0f}")

    # Risk metrics for risk chapter
    risk = evidence_context.get("risk_metrics", {})
    if risk and chapter_tag == "risk_framework":
        parts.append("\n## Risk Metrics")
        for key, val in risk.items():
            if val is not None:
                # Qualitative mapping for EVT shape parameter (PR-Q6)
                if key == "evt_xi_shape":
                    label = _map_tail_heaviness(val)
                    if label:
                        parts.append(f"- Tail Heaviness: {label}")
                    continue
                # NEVER expose raw xi, u, beta values in copy (PR-Q6 invariant)
                if key in ("evt_u_threshold", "evt_beta_scale"):
                    continue
                parts.append(f"- {key}: {val}")

    # SEC holdings data for investment_strategy (N-PORT primary, 13F overlay)
    if chapter_tag == "investment_strategy":
        if evidence_context.get("nport_available"):
            parts.append(f"\n## Fund Portfolio Holdings (N-PORT, {evidence_context.get('nport_report_date', 'latest')})")
            nport_aa = evidence_context.get("nport_asset_allocation", {})
            if nport_aa:
                parts.append("Asset Allocation:")
                for ac, pct in nport_aa.items():
                    parts.append(f"- {ac}: {pct * 100:.1f}%")
            nport_sw = evidence_context.get("nport_sector_weights", {})
            if nport_sw:
                parts.append("Sector Exposure:")
                for sector, weight in nport_sw.items():
                    parts.append(f"- {sector}: {weight * 100:.1f}%")
            top_h = evidence_context.get("nport_top_holdings", [])
            if top_h:
                parts.append("Top Holdings (by % of NAV):")
                for h in top_h[:10]:
                    parts.append(f"- {h.get('name', 'Unknown')} ({h.get('cusip', '')}): {h.get('pct_of_nav', 0):.2f}%")
            fund_style = evidence_context.get("fund_style", {})
            if fund_style:
                parts.append(f"Style: {fund_style.get('style_label', 'N/A')} | "
                             f"Equity: {fund_style.get('equity_pct', 'N/A')}% | "
                             f"FI: {fund_style.get('fi_pct', 'N/A')}%")
        if evidence_context.get("thirteenf_available"):
            if evidence_context.get("nport_available"):
                parts.append("\n## Manager Firm 13F Context (supplementary)")
            else:
                parts.append("\n## Manager Firm 13F Holdings (proxy — no fund-level N-PORT available)")
            sector_weights = evidence_context.get("sector_weights", {})
            if sector_weights:
                parts.append("Firm-level sector allocation (most recent quarter):")
                for sector, weight in sector_weights.items():
                    parts.append(f"- {sector}: {weight * 100:.1f}%")
            if evidence_context.get("drift_detected"):
                parts.append("⚠ Sector drift detected between recent quarters")
            parts.append(f"Quarters of 13F data available: {evidence_context.get('drift_quarters', 0)}")

    # SEC ADV + N-PORT data for manager_assessment
    if chapter_tag == "manager_assessment":
        # Fund-level context from N-PORT
        if evidence_context.get("nport_available"):
            fund_style = evidence_context.get("fund_style", {})
            if fund_style:
                parts.append("\n## Fund-Level Context (N-PORT)")
                parts.append(f"- Style: {fund_style.get('style_label', 'N/A')}")
                parts.append(f"- Equity: {fund_style.get('equity_pct', 'N/A')}% | "
                             f"FI: {fund_style.get('fi_pct', 'N/A')}%")
            if evidence_context.get("fund_style_drift_detected"):
                parts.append("⚠ Style drift detected — fund classification changed recently")

        # Firm-level context from ADV
        adv_aum = evidence_context.get("adv_aum_history", {})
        if adv_aum:
            parts.append("\n## Manager Firm Context (SEC ADV — supplementary)")
            for key, val in adv_aum.items():
                parts.append(f"- Firm {key}: {val}")
        adv_team = evidence_context.get("adv_team", [])
        if adv_team:
            parts.append(f"\n## SEC ADV — Firm Personnel ({len(adv_team)} members)")
            for member in adv_team:
                line = f"- {member.get('person_name', 'Unknown')}"
                if member.get("title"):
                    line += f" ({member['title']})"
                parts.append(line)

    # Fund enrichment (N-CEN + XBRL) for relevant chapters
    enrichment = evidence_context.get("fund_enrichment", {})
    if enrichment.get("enrichment_available"):
        if chapter_tag == "fee_analysis":
            share_classes = enrichment.get("share_classes", [])
            if share_classes:
                parts.append("\n## Share Class Fee Data (SEC N-CSR XBRL)")
                for sc in share_classes:
                    ticker = sc.get("ticker") or sc.get("class_id", "N/A")
                    er = sc.get("expense_ratio_pct")
                    er_str = f"ER {er}%" if er is not None else "ER N/A"
                    na = sc.get("net_assets")
                    na_str = f"Net Assets ${na:,.0f}M" if na is not None else ""
                    turn = sc.get("portfolio_turnover_pct")
                    turn_str = f"Turnover {turn}%" if turn is not None else ""
                    parts.append(f"- {ticker}: {er_str} | {na_str} | {turn_str}".rstrip(" |"))
            ncen_fees = enrichment.get("ncen_fees", {})
            if ncen_fees.get("management_fee") is not None:
                parts.append(f"Management Fee (N-CEN): {ncen_fees['management_fee']}%")
            if ncen_fees.get("net_operating_expenses") is not None:
                parts.append(f"Net Operating Expenses (N-CEN): {ncen_fees['net_operating_expenses']}%")
            vehicle = enrichment.get("vehicle_specific", {})
            if vehicle.get("type") == "etf":
                if vehicle.get("tracking_difference_net") is not None:
                    parts.append(f"ETF Tracking Difference (Net): {vehicle['tracking_difference_net']}%")

        if chapter_tag in ("investment_strategy", "executive_summary", "recommendation"):
            if enrichment.get("strategy_label"):
                parts.append(f"\nSEC Strategy Classification: {enrichment['strategy_label']}")
            classification = enrichment.get("classification", {})
            flags = [k for k, v in classification.items() if v]
            if flags:
                parts.append(f"Fund Flags: {', '.join(flags)}")

        if chapter_tag == "operational_dd":
            ops = enrichment.get("operational", {})
            if ops.get("is_sec_lending_authorized") is not None:
                if ops["is_sec_lending_authorized"]:
                    lending_status = "Active" if ops.get("did_lend_securities") else "Authorized, not active"
                    parts.append(f"\n## Securities Lending: {lending_status}")
                else:
                    parts.append("\n## Securities Lending: Not authorized")
            if ops.get("has_swing_pricing"):
                parts.append("Swing Pricing: Yes")
            if ops.get("did_pay_broker_research") is not None:
                parts.append(f"Soft Dollar / Broker Research: {'Yes' if ops['did_pay_broker_research'] else 'No'}")
            classification = enrichment.get("classification", {})
            flags = [k for k, v in classification.items() if v]
            if flags:
                parts.append(f"Fund Classification Flags: {', '.join(flags)}")

        if chapter_tag == "manager_assessment":
            if enrichment.get("strategy_label"):
                parts.append(f"\nSEC Strategy Classification: {enrichment['strategy_label']}")

    # Compliance disclosures for operational_dd
    if chapter_tag == "operational_dd":
        disclosures = evidence_context.get("compliance_disclosures")
        if disclosures is not None:
            parts.append(f"\n## SEC Compliance Disclosures: {disclosures}")

    # Document excerpts
    docs = evidence_context.get("documents", [])
    if docs:
        parts.append(f"\n## Document Evidence ({len(docs)} chunks)")
        for i, doc in enumerate(docs[:20]):  # Cap at 20 chunks
            text = doc.get("text", doc.get("content", ""))[:2000]
            source = doc.get("source", doc.get("title", f"doc_{i}"))
            parts.append(f"\n### [{source}]\n{text}")

    # Chapter summaries (for recommendation chapter)
    summaries = evidence_context.get("chapter_summaries", {})
    if summaries:
        parts.append("\n## Previous Chapter Summaries")
        for tag, summary in summaries.items():
            parts.append(f"\n### {tag}\n{summary[:500]}")

    return "\n".join(parts)


# Sanitised copy for Netz-owned rail badges. Frontend and LLM prompts read
# this mapping — never the raw quant vocabulary ("Sharpe regression", etc).
_RAIL_BADGE_COPY: dict[str, tuple[str, str]] = {
    "RAIL_HOLDINGS": (
        "HIGH CONFIDENCE — position-level",
        "Attribution derived from disclosed holdings.",
    ),
    "RAIL_IPCA": (
        "MEDIUM-HIGH CONFIDENCE — factor model",
        "Attribution derived from a proprietary factor model.",
    ),
    "RAIL_PROXY": (
        "MEDIUM CONFIDENCE — benchmark proxy",
        "Attribution derived from the fund's primary benchmark exposure.",
    ),
    "RAIL_RETURNS": (
        "LOW-MEDIUM CONFIDENCE — style regression",
        "Attribution inferred from {n_months} months of returns.",
    ),
    "RAIL_NONE": (
        "INSUFFICIENT DATA",
        "Not enough history to produce a reliable attribution.",
    ),
}


def _render_attribution_block(evidence_context: dict[str, Any]) -> list[str]:
    """Render the sanitised attribution section for performance_analysis.

    Consumes the dispatcher output attached upstream as
    ``evidence_context["attribution"]`` — never surfaces raw quant terms
    (R², tracking error labels, regression jargon) in UI copy.
    """
    attribution = evidence_context.get("attribution")
    if not attribution:
        return []

    badge = attribution.get("badge")
    copy = _RAIL_BADGE_COPY.get(str(badge)) if badge else None
    if copy is None:
        return []

    heading, subtitle_template = copy
    out: list[str] = ["\n## Attribution"]
    out.append(f"- Confidence: **{heading}**")

    returns_based = attribution.get("returns_based")
    n_months = (returns_based or {}).get("n_months")
    subtitle = (
        subtitle_template.format(n_months=n_months)
        if n_months and "{n_months}" in subtitle_template
        else subtitle_template.replace(" {n_months} months", "")
    )
    out.append(f"- {subtitle}")

    if badge == "RAIL_HOLDINGS":
        holdings_based = attribution.get("holdings_based")
        sectors = (holdings_based or {}).get("sectors") or []
        coverage = float((holdings_based or {}).get("coverage_pct") or 0.0)
        if sectors:
            out.append("\n### Sector Weights")
            # Cap at 11 rows to mirror the GICS ceiling; matview may return
            # more when issuer_category splits are non-trivial.
            for sec in sectors[:11]:
                weight = float(sec.get("weight", 0.0))
                if weight < 1e-4:
                    continue
                label = _sanitize_sector_label(str(sec.get("sector", "")))
                out.append(f"- {label}: {weight * 100:.1f}%")
            out.append(f"\n- Portfolio coverage: {coverage * 100:.1f}%")

    if badge == "RAIL_PROXY":
        out.extend(_render_proxy_block(attribution))

    if badge == "RAIL_IPCA":
        ipca = attribution.get("ipca")
        if ipca:
            out.append("\n### Style Exposures")
            names = ipca.get("factor_names", [])
            exposures = ipca.get("factor_exposures", [])
            for i, name in enumerate(names):
                if i < len(exposures):
                    val = float(exposures[i])
                    # PR-Q9 invariant: Zero raw beta values in copy, format as %
                    out.append(f"- {name}: {val * 100:.1f}%")

    if badge == "RAIL_RETURNS" and returns_based:
        exposures = returns_based.get("exposures") or []
        if exposures:
            out.append("\n### Style Exposures")
            for exp in exposures:
                weight = float(exp.get("weight", 0.0))
                if weight < 1e-4:
                    continue
                out.append(f"- {exp.get('ticker', '—')}: {weight * 100:.1f}%")

    return out


_PROXY_INTRO = (
    "Why the manager beat/lagged — asset mix vs. stock picks vs. timing"
)


def _render_proxy_block(attribution: dict[str, Any]) -> list[str]:
    """Render the Brinson-Fachler table when the proxy rail wins.

    Sanitised copy: raw quant vocabulary ("Brinson-Fachler",
    "allocation effect") never leaves this module. UI headings use the
    product phrasing ("Asset mix contribution", "Security selection",
    "Timing & interaction").
    """
    proxy = attribution.get("proxy")
    if not proxy:
        return []

    brinson = proxy.get("brinson") or {}
    sectors = brinson.get("by_sector") or []

    out: list[str] = [f"\n### {_PROXY_INTRO}"]

    out.append(
        f"- Asset mix contribution: {float(brinson.get('allocation_effect', 0.0)) * 100:.2f}%",
    )
    out.append(
        f"- Security selection: {float(brinson.get('selection_effect', 0.0)) * 100:.2f}%",
    )
    out.append(
        f"- Timing & interaction: {float(brinson.get('interaction_effect', 0.0)) * 100:.2f}%",
    )
    out.append(
        f"- Total active return: {float(brinson.get('total_active_return', 0.0)) * 100:.2f}%",
    )

    if sectors:
        out.append("\n### Sector breakdown")
        # Top 11 sectors by absolute total effect (allocation + selection + interaction)
        ranked = sorted(
            sectors,
            key=lambda s: abs(
                float(s.get("allocation_effect", 0.0))
                + float(s.get("selection_effect", 0.0))
                + float(s.get("interaction_effect", 0.0)),
            ),
            reverse=True,
        )
        for sec in ranked[:11]:
            label = _sanitize_sector_label(str(sec.get("sector", "")))
            total = (
                float(sec.get("allocation_effect", 0.0))
                + float(sec.get("selection_effect", 0.0))
                + float(sec.get("interaction_effect", 0.0))
            )
            out.append(f"- {label}: {total * 100:+.2f}%")

    resolution = proxy.get("resolution") or {}
    ticker = resolution.get("proxy_etf_ticker")
    if ticker:
        out.append(f"\n- Benchmark proxy: {ticker}")

    return out


# Raw N-PORT issuer codes are never shown to clients. Keep everything else
# pass-through — the enrichment worker already resolves equity CUSIPs to GICS.
_NPORT_SECTOR_COPY: dict[str, str] = {
    "CORP": "Corporate",
    "UST": "US Treasury",
    "USGA": "US Government Agency",
    "USGSE": "US Government Sponsored Enterprise",
    "NUSS": "Non-US Sovereign",
    "MUN": "Municipal",
    "RF": "Registered Fund",
    "PF": "Private Fund",
    "OTHER": "Other",
    "Unknown": "Other",
    "Unclassified": "Other",
}


def _map_tail_heaviness(xi: float | Any) -> str | None:
    """Map GPD shape parameter xi to qualitative tail-heaviness labels.

    Reference: PR-Q6 and EDHEC Spec §4.
    """
    if xi is None:
        return None
    try:
        val = float(xi)
        if val < 0:
            return "Light"
        if val < 0.15:
            return "Normal"
        if val < 0.5:
            return "Heavy"
        return "Extreme"
    except (TypeError, ValueError):
        return None


def _sanitize_sector_label(raw: str) -> str:
    key = raw.strip()
    return _NPORT_SECTOR_COPY.get(key, key or "Other")
