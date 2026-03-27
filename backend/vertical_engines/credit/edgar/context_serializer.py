"""EDGAR context serializer — build LLM-consumable text with attribution guardrails.

Renders multi-entity EDGAR data as structured text for the evidence pack.
Preserves the DIRECT TARGET / RELATED ENTITY attribution framework.

Section-level truncation: builds context incrementally, tracking char budget.
Never truncates mid-section — drops lowest-priority sections when over budget.

Budget: 12KB total, 3KB sub-cap for insider signals.
"""
from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()

_MAX_CONTEXT_CHARS = 12_000
_MAX_INSIDER_CHARS = 3_000


def build_edgar_multi_entity_context(
    multi_result: dict[str, Any],
    *,
    deal_name: str = "",
    target_vehicle: str = "",
) -> str:
    """Build combined EDGAR context section from multi-entity results.

    Renders each entity with role labels and explicit attribution guardrails.
    Backward-compatible signature and output structure.
    """
    results = multi_result.get("results", [])
    if not results:
        return ""

    target_label = target_vehicle or deal_name or "the target investment vehicle"

    # If ALL results are NOT_FOUND/SKIPPED, emit short message
    found_any = any(
        r.get("status") in ("FOUND", "FORM_D_ONLY") for r in results
    )
    if not found_any:
        entities_tried = [r.get("lookup_entity", "?") for r in results]
        return (
            "=== SEC EDGAR PUBLIC FILING DATA ===\n"
            f"Entities searched: {', '.join(entities_tried)}\n"
            "Status: No EDGAR filings found for any related entity.\n"
            "All entities may be private/foreign-registered. "
            "Absence of EDGAR data is not itself a flaw."
        )

    has_direct_target = any(r.get("is_direct_target", False) for r in results)
    if not has_direct_target:
        target_label = "the target investment vehicle (not yet identified in EDGAR)"

    # ── Build sections with budget tracking ──
    sections: list[str] = []
    remaining = _MAX_CONTEXT_CHARS

    # Header + attribution framework (always included, ~1.5KB)
    header = _build_header(
        multi_result, target_label, deal_name, has_direct_target,
    )
    sections.append(header)
    remaining -= len(header)

    # Sort entities: direct target first, then by found status
    sorted_results = sorted(
        results,
        key=lambda r: (not r.get("is_direct_target", False), r.get("status") == "NOT_FOUND"),
    )

    for r in sorted_results:
        entity_section = _build_entity_section(r, target_label)
        if len(entity_section) <= remaining:
            sections.append(entity_section)
            remaining -= len(entity_section)
        else:
            # Budget exhausted — log and stop
            logger.info(
                "edgar_context_truncated",
                remaining=remaining,
                skipped_entity=r.get("lookup_entity", "?"),
            )
            sections.append("\n[Additional entities omitted due to context budget]\n")
            break

    # Warnings
    if multi_result.get("combined_warnings"):
        warning_text = f"\nWarnings: {'; '.join(multi_result['combined_warnings'][:5])}"
        if len(warning_text) <= remaining:
            sections.append(warning_text)

    return "\n".join(sections)


def _build_header(
    multi_result: dict[str, Any],
    target_label: str,
    deal_name: str,
    has_direct_target: bool,
) -> str:
    """Build the header with attribution framework."""
    lines = [
        "=== SEC EDGAR PUBLIC FILING DATA (Multi-Entity) ===",
        "",
        "╔══════════════════════════════════════════════════════════════════╗",
        "║       ⚠  EDGAR DATA ATTRIBUTION RULES — READ FIRST  ⚠        ║",
        "╠══════════════════════════════════════════════════════════════════╣",
        "║ Multiple entities related to this deal were searched in EDGAR. ║",
        "║ Each entity below is labeled DIRECT TARGET or RELATED ENTITY.  ║",
        "║                                                                ║",
        "║ CRITICAL RULES:                                                ║",
        "║ 1. Financial metrics from a RELATED ENTITY belong to THAT      ║",
        "║    entity only — NEVER attribute them to the target vehicle.    ║",
        "║ 2. A publicly listed BDC/REIT managed by the same sponsor is   ║",
        "║    a DIFFERENT vehicle from the private fund under review.      ║",
        "║ 3. Financial ratios from RELATED ENTITY filings describe THAT  ║",
        "║    entity's financial health, not the target fund's.           ║",
        "║ 4. Income/balance sheet data must be attributed to the specific ║",
        "║    entity and filing period.                                    ║",
        "║ 5. Insider trading signals from a RELATED ENTITY indicate      ║",
        "║    manager/sponsor activity, not target fund performance.       ║",
        "╚══════════════════════════════════════════════════════════════════╝",
        "",
    ]

    if not has_direct_target:
        lines.extend([
            "╔══════════════════════════════════════════════════════════════════╗",
            "║  ⚠⚠  NO DIRECT TARGET VEHICLE IDENTIFIED IN EDGAR  ⚠⚠        ║",
            "╠══════════════════════════════════════════════════════════════════╣",
            "║ The target investment vehicle was NOT found. ALL data below     ║",
            "║ belongs to RELATED entities — NOT the target fund.             ║",
            "║ Do NOT use ANY financial metric below as a proxy for the fund. ║",
            "╚══════════════════════════════════════════════════════════════════╝",
            "",
            f"Deal name: {deal_name or 'N/A'} "
            f"(identified as sponsor/manager — not the investment vehicle)",
        ])
    else:
        lines.append(f"Target vehicle under analysis: {target_label}")

    lines.extend([
        f"Searched {multi_result.get('entities_tried', 0)} entities, "
        f"found {multi_result.get('entities_found', 0)} in EDGAR "
        f"({multi_result.get('unique_ciks', 0)} unique CIKs).",
        "",
    ])

    return "\n".join(lines)


def _build_entity_section(r: dict[str, Any], target_label: str) -> str:
    """Build the section for a single entity result."""
    status = r.get("status", "NOT_FOUND")
    role = r.get("role", "unknown")
    name = r.get("lookup_entity") or r.get("matched_name") or "?"
    is_direct = r.get("is_direct_target", False)
    rel_desc = r.get("relationship_desc", "")

    if status == "SKIPPED":
        return ""

    lines: list[str] = []

    # Entity header
    target_tag = "DIRECT TARGET" if is_direct else "RELATED ENTITY"
    lines.append(f"--- [{target_tag}] {role.upper()}: {name} ---")

    if not is_direct and rel_desc:
        lines.append(f"  Relationship: {rel_desc}")

    if status == "NOT_FOUND":
        lines.append("  Not found in EDGAR (entity may be private/offshore).")
        lines.append("")
        return "\n".join(lines)

    if status == "FORM_D_ONLY":
        lines.append("  Private entity — not in EDGAR index.")
        form_d = r.get("form_d")
        if form_d:
            lines.append(f"  Form D (Reg D): filed {form_d.get('filing_date', 'n/a')}")
            lines.append(f"    Entity: {form_d.get('entity_name', 'n/a')}")
        lines.append("")
        return "\n".join(lines)

    # FOUND — full render
    lines.append(f"  Entity: {r.get('matched_name') or name}")
    lines.append(f"  CIK: {r.get('cik')}")

    # Resolution confidence
    confidence = r.get("resolution_confidence", 1.0)
    if confidence < 0.8:
        lines.append(f"  ⚠ Match confidence: {confidence:.0%} — verify entity identity")

    also = r.get("also_matched_as", [])
    if also:
        aliases = ", ".join(f"{a['name']} ({a['role']})" for a in also)
        lines.append(f"  Also matched: {aliases}")

    # Entity metadata
    meta = r.get("entity_metadata", {})
    if meta:
        if meta.get("sic"):
            lines.append(f"  SIC: {meta.get('sic', 'n/a')} — {meta.get('sic_description', '')}")
        if meta.get("state_of_incorporation"):
            lines.append(f"  State: {meta['state_of_incorporation']}")

    # Going concern
    gc = r.get("going_concern")
    gc_detail = r.get("going_concern_detail", {})
    if gc is True:
        verdict = gc_detail.get("verdict", "confirmed")
        if is_direct:
            lines.append(f"  ⚠ GOING CONCERN DETECTED ({verdict}) ⚠ — escalate immediately")
        else:
            lines.append(
                f"  ⚠ GOING CONCERN DETECTED ({verdict}) in {name} ⚠ — "
                f"assess contagion risk to {target_label}",
            )
    elif gc is False:
        lines.append("  Going concern: Not detected")

    # Financial metrics (BDC/REIT or AM Platform)
    metrics = r.get("financial_metrics", {})
    metrics_type = r.get("metrics_type", "BDC_REIT")
    if metrics:
        if is_direct:
            lines.append("  XBRL Metrics (DIRECT TARGET — may use for underwriting):")
        else:
            lines.append(
                f"  XBRL Metrics (⚠ belong to {name}, NOT to {target_label}):",
            )
        _render_metrics(lines, metrics, metrics_type)

    # Structured financials summary (new — most recent period only)
    structured = r.get("structured_financials", {})
    if structured and structured.get("periods_available", 0) > 0:
        _render_structured_financials(lines, structured, is_direct, name, target_label)

    # Ratios
    ratios = structured.get("ratios", {}) if structured else {}
    if any(v is not None for v in ratios.values()):
        lines.append("  Financial Ratios:")
        for label, key in [
            ("Leverage", "leverage_ratio"),
            ("Interest Coverage", "interest_coverage"),
            ("DSCR", "debt_service_coverage"),
            ("NII Coverage", "nii_dividend_coverage"),
        ]:
            val = ratios.get(key)
            if val is not None:
                lines.append(f"    {label}: {val:.2f}x")

    # Insider signals (with sub-cap)
    insider_signals = r.get("insider_signals", [])
    if insider_signals:
        _render_insider_signals(lines, insider_signals, is_direct, name, target_label)

    # Form D
    form_d = r.get("form_d")
    if form_d:
        lines.append(
            f"  Form D: filed {form_d.get('filing_date', 'n/a')} "
            f"— {form_d.get('entity_name', 'n/a')}",
        )

    lines.append("")  # blank between entities
    return "\n".join(lines)


def _render_metrics(
    lines: list[str],
    metrics: dict[str, Any],
    metrics_type: str,
) -> None:
    """Render BDC/REIT or AM Platform metrics."""
    if metrics_type == "BDC_REIT":
        for key, label in [
            ("total_assets_usd", "Total assets"),
            ("total_debt_usd", "Total debt"),
            ("leverage_ratio", "Leverage"),
            ("net_investment_income_usd", "NII"),
            ("nii_dividend_coverage", "NII coverage"),
        ]:
            val = metrics.get(key)
            if val and isinstance(val, dict):
                v = val.get("val")
                if v is not None:
                    lines.append(f"    {label}: {_fmt_val(v, key)}")
    elif metrics_type == "AM_PLATFORM":
        for key, label in [
            ("total_assets_usd", "Total assets"),
            ("total_revenues_usd", "Revenue"),
            ("aum_usd", "AUM"),
            ("management_fee_revenue_usd", "Mgmt fee revenue"),
            ("fee_related_earnings_usd", "FRE"),
            ("distributable_earnings_usd", "DE"),
        ]:
            val = metrics.get(key)
            if val and isinstance(val, dict):
                v = val.get("val")
                if v is not None:
                    lines.append(f"    {label}: {_fmt_val(v, key)}")


def _render_structured_financials(
    lines: list[str],
    structured: dict[str, Any],
    is_direct: bool,
    name: str,
    target_label: str,
) -> None:
    """Render most recent period from structured financials."""
    periods = structured.get("periods_available", 0)
    lines.append(f"  Structured Financials ({periods} periods available):")

    # Show most recent period for income statement
    income = structured.get("income_statement")
    if income and len(income) > 0:
        latest = income[0]
        period = latest.get("period", "")
        lines.append(f"    Income Statement (period: {period}):")
        for key, val in list(latest.items())[:8]:
            if key != "period" and isinstance(val, (int, float)):
                lines.append(f"      {key}: {_fmt_val(val, key)}")

    # Most recent balance sheet
    balance = structured.get("balance_sheet")
    if balance and len(balance) > 0:
        latest = balance[0]
        period = latest.get("period", "")
        lines.append(f"    Balance Sheet (period: {period}):")
        for key, val in list(latest.items())[:8]:
            if key != "period" and isinstance(val, (int, float)):
                lines.append(f"      {key}: {_fmt_val(val, key)}")


def _render_insider_signals(
    lines: list[str],
    signals: list[dict[str, Any]],
    is_direct: bool,
    name: str,
    target_label: str,
) -> None:
    """Render insider trading signals within 3KB sub-cap."""
    signal_lines: list[str] = []
    if is_direct:
        signal_lines.append("  ### Insider Trading Signals (DIRECT TARGET):")
    else:
        signal_lines.append(
            f"  ### Insider Trading Signals (⚠ {name}, NOT {target_label}):",
        )

    for sig in signals[:5]:  # max 5 signals per entity
        severity = sig.get("severity", "watch")
        sig_type = sig.get("signal_type", "unknown")
        desc = sig.get("description", "")
        value = sig.get("aggregate_value", 0)
        signal_lines.append(f"    [{severity.upper()}] {sig_type}: {desc}")
        if value:
            signal_lines.append(f"      Aggregate value: ${value:,.0f}")

    # Apply 3KB sub-cap
    signal_text = "\n".join(signal_lines)
    if len(signal_text) > _MAX_INSIDER_CHARS:
        signal_text = signal_text[:_MAX_INSIDER_CHARS - 50] + "\n    [Signals truncated]"
        signal_lines = signal_text.split("\n")

    lines.extend(signal_lines)


def _fmt_val(v: float, key: str = "") -> str:
    """Format a financial value for display."""
    if abs(v) >= 1e9:
        return f"${v / 1e9:,.1f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:,.1f}M"
    if "ratio" in key or "coverage" in key:
        return f"{v:.2f}x"
    return f"${v:,.0f}"
