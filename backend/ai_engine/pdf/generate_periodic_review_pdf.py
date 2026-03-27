"""Periodic Review PDF Report Generator (Portfolio Monitoring).

Reads persisted AI periodic review data from Postgres (ActiveInvestment,
PeriodicReviewReport, CovenantStatusRegister, InvestmentRiskRegistry,
BoardMonitoringBrief, monitoring_output JSONB) and renders a professional
investment-grade PDF document.

This is the PORTFOLIO monitoring equivalent of the IC Memorandum PDF,
but it justifies capital PRESERVATION — not allocation.

PDF engine: reportlab.platypus (institutional quality)
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import UTC, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s")
logger = logging.getLogger("periodic_review_pdf")

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ai_engine.pdf.pdf_base import (  # noqa: E402
    ACCENT,
    AMBER,
    DARK_GREY,
    GREEN,
    LIGHT_BG,
    MED_GREY,
    NAVY,
    RED,
    WHITE,
    _normalise_unicode_dashes,
    build_netz_styles,
)

# ── Style factory ─────────────────────────────────────────────────────

def _build_styles() -> dict:
    """Extend the canonical Netz styles with periodic-review-specific overrides."""
    return build_netz_styles()


# ── Utilities ─────────────────────────────────────────────────────────

def _clean(text) -> str:
    """Sanitise text for reportlab Paragraph (XML-safe).

    Uses the shared _normalise_unicode_dashes from pdf_base for consistent
    handling of Unicode dash variants across all PDF generators.
    """
    if text is None:
        return "N/A"
    s = str(text)
    s = _normalise_unicode_dashes(s)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Additional Unicode → ASCII fallbacks (quotes, bullets, etc.)
    replacements = {
        "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"', "\u2022": "•", "\u2026": "...",
        "\u00a0": " ", "\u00b7": "·",
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    return s


def _fmt_currency(value) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
        if abs(v) >= 1_000_000:
            return f"${v / 1_000_000:,.1f}M"
        if abs(v) >= 1_000:
            return f"${v / 1_000:,.0f}K"
        return f"${v:,.0f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_pct(value) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _fmt_date(dt_val) -> str:
    if dt_val is None:
        return "N/A"
    if isinstance(dt_val, str):
        try:
            dt_val = datetime.fromisoformat(dt_val)
        except (ValueError, TypeError):
            return str(dt_val)
    if hasattr(dt_val, "strftime"):
        return dt_val.strftime("%Y-%m-%d %H:%M UTC")
    return str(dt_val)


def _rating_style(styles: dict, rating: str) -> ParagraphStyle:
    r = (rating or "").upper()
    if r in ("GREEN", "PASS", "OK"):
        return styles["badge_green"]
    if r in ("RED", "FAIL", "BREACH", "CRITICAL"):
        return styles["badge_red"]
    return styles["badge_amber"]


def _severity_color(severity: str) -> colors.Color:
    s = (severity or "").upper()
    if s == "HIGH":
        return RED
    if s == "MEDIUM":
        return AMBER
    return GREEN


def _status_color(status: str) -> colors.Color:
    s = (status or "").upper()
    if s == "BREACH":
        return RED
    if s in ("WARNING", "NOT_TESTED", "NOT_CONFIGURED"):
        return AMBER
    return GREEN


# ── Data table builder ────────────────────────────────────────────────

def _build_table(headers: list[str], rows: list[list], styles: dict,
                 col_widths: list | None = None) -> Table:
    """Build a styled platypus Table with header row."""
    header_cells = [
        Paragraph(_clean(h), styles["table_header"]) for h in headers
    ]
    body_rows = []
    for row in rows:
        body_rows.append([
            Paragraph(_clean(str(cell)), styles["table_cell"]) for cell in row
        ])

    data = [header_cells] + body_rows

    if not col_widths:
        page_w = A4[0] - 30 * mm  # margins
        col_widths = [page_w / len(headers)] * len(headers)

    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BACKGROUND", (0, 1), (-1, -1), WHITE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_BG]),
        ("TEXTCOLOR", (0, 1), (-1, -1), DARK_GREY),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.3, MED_GREY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


# ── Header / footer ──────────────────────────────────────────────────

def _header_footer(canvas, doc, deal_name: str, as_of: str):
    """Draw persistent header and footer on every page."""
    canvas.saveState()
    # Header line
    canvas.setStrokeColor(ACCENT)
    canvas.setLineWidth(0.5)
    canvas.line(15 * mm, A4[1] - 12 * mm, A4[0] - 15 * mm, A4[1] - 12 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MED_GREY)
    canvas.drawString(15 * mm, A4[1] - 10 * mm,
                      f"Netz International  |  Portfolio Monitoring Report  |  {deal_name}")
    canvas.drawRightString(A4[0] - 15 * mm, A4[1] - 10 * mm, f"As of: {as_of}")

    # Footer
    canvas.setStrokeColor(MED_GREY)
    canvas.setLineWidth(0.3)
    canvas.line(15 * mm, 14 * mm, A4[0] - 15 * mm, 14 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(15 * mm, 10 * mm, "CONFIDENTIAL — For authorised personnel only")
    canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


# ── Data Loading ──────────────────────────────────────────────────────

def _load_review_data(
    *,
    investment_id: str,
    review_id: str | None = None,
) -> dict:
    """Load all periodic review artefacts from Postgres.

    Returns a dict with all data needed to render the PDF.
    No DB mutations — read-only.
    """
    from sqlalchemy import text as sa_text

    from app.core.db.engine import async_session_factory

    db = async_session_factory()

    try:
        # 1. ActiveInvestment
        inv = db.execute(sa_text(
            "SELECT id, investment_name, manager_name, lifecycle_status, "
            "strategy_type, target_return, committed_capital_usd, "
            "deployed_capital_usd, current_nav_usd, last_monitoring_at, "
            "fund_id, deal_id "
            "FROM active_investments WHERE id = :iid",
        ), {"iid": investment_id}).fetchone()

        if not inv:
            raise ValueError(f"Active investment not found: {investment_id}")

        fund_id = str(inv[10])
        deal_id = str(inv[11]) if inv[11] else None

        # 2. PeriodicReviewReport (specific or latest)
        if review_id:
            review = db.execute(sa_text(
                "SELECT id, review_type, overall_rating, executive_summary, "
                "performance_assessment, covenant_compliance, material_changes, "
                "risk_evolution, liquidity_assessment, valuation_view, "
                "recommended_actions, reviewed_at, model_version "
                "FROM periodic_review_reports WHERE id = :rid AND investment_id = :iid",
            ), {"rid": review_id, "iid": investment_id}).fetchone()
        else:
            review = db.execute(sa_text(
                "SELECT id, review_type, overall_rating, executive_summary, "
                "performance_assessment, covenant_compliance, material_changes, "
                "risk_evolution, liquidity_assessment, valuation_view, "
                "recommended_actions, reviewed_at, model_version "
                "FROM periodic_review_reports WHERE investment_id = :iid "
                "ORDER BY reviewed_at DESC LIMIT 1",
            ), {"iid": investment_id}).fetchone()

        # 3. CovenantStatusRegister
        covenants = db.execute(sa_text(
            "SELECT covenant_name, status, severity, details, "
            "last_tested_at, next_test_due_at "
            "FROM covenant_status_register WHERE investment_id = :iid AND fund_id = :fid "
            "ORDER BY CASE severity WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END",
        ), {"iid": investment_id, "fid": fund_id}).fetchall()

        # 4. InvestmentRiskRegistry
        risks = db.execute(sa_text(
            "SELECT risk_type, risk_level, trend, rationale "
            "FROM investment_risk_registry WHERE investment_id = :iid AND fund_id = :fid "
            "ORDER BY CASE risk_level WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END",
        ), {"iid": investment_id, "fid": fund_id}).fetchall()

        # 5. BoardMonitoringBrief
        brief = db.execute(sa_text(
            "SELECT executive_summary, performance_view, covenant_view, "
            "liquidity_view, risk_reclassification_view, recommended_actions, "
            "last_generated_at "
            "FROM board_monitoring_briefs WHERE investment_id = :iid AND fund_id = :fid",
        ), {"iid": investment_id, "fid": fund_id}).fetchone()

        # 6. monitoring_output JSONB from portfolio deal
        monitoring_output = None
        if deal_id:
            mo_row = db.execute(sa_text(
                "SELECT monitoring_output FROM deals WHERE id = :did",
            ), {"did": deal_id}).fetchone()
            if mo_row and mo_row[0]:
                monitoring_output = mo_row[0]
    finally:
        db.close()

    return {
        "investment_id": str(inv[0]),
        "investment_name": inv[1] or "Unknown",
        "manager_name": inv[2] or "Unknown",
        "lifecycle_status": inv[3] or "ACTIVE",
        "strategy_type": inv[4] or "",
        "target_return": inv[5] or "",
        "committed_capital_usd": inv[6],
        "deployed_capital_usd": inv[7],
        "current_nav_usd": inv[8],
        "last_monitoring_at": inv[9],
        "fund_id": fund_id,
        "review": review,
        "covenants": covenants,
        "risks": risks,
        "brief": brief,
        "monitoring_output": monitoring_output,
    }


# ── PDF Generation ────────────────────────────────────────────────────

def generate_pdf(data: dict, output_path: str | None = None) -> str:
    """Generate a professional Portfolio Monitoring Report PDF.

    Uses reportlab.platypus exclusively (no canvas hacks).

    Args:
        data: Dict returned by _load_review_data().
        output_path: Optional file path. If None, writes to temp location.

    Returns:
        Absolute path to the generated PDF file.

    """
    investment_name = data["investment_name"]
    manager_name = data["manager_name"]
    review = data["review"]
    covenants = data["covenants"]
    risks = data["risks"]
    brief = data["brief"]
    monitoring_output = data.get("monitoring_output") or {}

    # Review metadata
    reviewed_at_str = "N/A"
    model_version = "unknown"
    overall_rating = "N/A"
    review_type = "PERIODIC"
    if review:
        reviewed_at_str = _fmt_date(review[11])  # reviewed_at
        model_version = review[12] or "unknown"
        overall_rating = review[2] or "N/A"
        review_type = review[1] or "PERIODIC"

    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    as_of = reviewed_at_str if review else now_str

    styles = _build_styles()

    # Output path
    if not output_path:
        safe_name = investment_name.replace(" ", "_").lower()
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            f"_periodic_review_{safe_name}.pdf",
        )

    # Build document
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        title=f"Periodic Review — {investment_name}",
        author="Netz International AI Engine",
    )

    story = []

    # ══════════════════════════════════════════════════════════════════
    # COVER PAGE
    # ══════════════════════════════════════════════════════════════════

    story.append(Spacer(1, 30 * mm))
    story.append(Paragraph("Portfolio Monitoring Report", styles["cover_title"]))
    story.append(Spacer(1, 4 * mm))

    # Accent line
    story.append(HRFlowable(
        width="40%", thickness=1, color=ACCENT,
        spaceAfter=8 * mm, hAlign="CENTER",
    ))

    story.append(Paragraph(_clean(investment_name), styles["cover_subtitle"]))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(f"Manager: {_clean(manager_name)}", styles["cover_meta"]))
    story.append(Paragraph(f"Review Type: {_clean(review_type)}", styles["cover_meta"]))
    story.append(Paragraph(f"As-of Date: {as_of}", styles["cover_meta"]))
    story.append(Paragraph(f"Model: {_clean(model_version)}", styles["cover_meta"]))
    story.append(Spacer(1, 10 * mm))

    # Overall Rating badge
    rating_style = _rating_style(styles, overall_rating)
    story.append(Paragraph(f"Overall Rating: {_clean(overall_rating)}", rating_style))
    story.append(Spacer(1, 6 * mm))

    story.append(HRFlowable(
        width="60%", thickness=0.3, color=MED_GREY,
        spaceAfter=6 * mm, hAlign="CENTER",
    ))

    story.append(Paragraph(
        f"Generated: {now_str}", styles["cover_meta"],
    ))
    story.append(Paragraph(
        "CONFIDENTIAL — For authorised personnel of Netz International only",
        styles["cover_meta"],
    ))

    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════
    # SECTION 1 — Executive Monitoring Summary
    # ══════════════════════════════════════════════════════════════════

    story.append(Paragraph("1. Executive Monitoring Summary", styles["section_heading"]))

    if review:
        # Monitoring status from overall_rating
        status_label = overall_rating.upper() if overall_rating else "N/A"
        story.append(Paragraph(
            f"<b>Monitoring Status:</b> {_clean(status_label)}", styles["body"],
        ))

        exec_summary = review[3] or "No executive summary available."
        story.append(Paragraph(_clean(exec_summary), styles["body"]))

        # Material changes
        material_changes = review[6] or []
        if material_changes and isinstance(material_changes, list) and len(material_changes) > 0:
            story.append(Paragraph("Material Changes:", styles["subsection"]))
            for mc in material_changes:
                story.append(Paragraph(f"• {_clean(mc)}", styles["body"]))

        # Recommended actions
        rec_actions = review[10] or []
        if rec_actions and isinstance(rec_actions, list) and len(rec_actions) > 0:
            story.append(Paragraph("Recommended Actions:", styles["subsection"]))
            for ra in rec_actions:
                story.append(Paragraph(f"• {_clean(ra)}", styles["body"]))
    else:
        story.append(Paragraph(
            "No periodic review has been generated for this investment.",
            styles["body"],
        ))

    # ══════════════════════════════════════════════════════════════════
    # SECTION 2 — Performance Overview
    # ══════════════════════════════════════════════════════════════════

    story.append(Paragraph("2. Performance Overview", styles["section_heading"]))

    perf_rows = [
        ["Strategy Type", _clean(data.get("strategy_type", ""))],
        ["Target Return", _clean(data.get("target_return", ""))],
        ["Committed Capital", _fmt_currency(data.get("committed_capital_usd"))],
        ["Deployed Capital", _fmt_currency(data.get("deployed_capital_usd"))],
        ["Current NAV", _fmt_currency(data.get("current_nav_usd"))],
        ["Status", _clean(data.get("lifecycle_status", ""))],
    ]

    # Add cashflow from monitoring_output if available
    cf = monitoring_output.get("cashflow_summary") or {}
    if cf:
        if cf.get("interest_received") is not None:
            perf_rows.append(["Interest Received", _fmt_currency(cf.get("interest_received"))])
        if cf.get("principal_returned") is not None:
            perf_rows.append(["Principal Returned", _fmt_currency(cf.get("principal_returned"))])
        if cf.get("net_cash_position") is not None:
            perf_rows.append(["Net Cash Position", _fmt_currency(cf.get("net_cash_position"))])
        if cf.get("irr_estimate") is not None:
            perf_rows.append(["IRR Estimate", _fmt_pct(cf.get("irr_estimate"))])
        if cf.get("cash_to_cash_multiple") is not None:
            perf_rows.append(["Cash-to-Cash Multiple", f"{cf.get('cash_to_cash_multiple'):.2f}x"])

    page_w = A4[0] - 30 * mm
    story.append(_build_table(
        ["Metric", "Value"], perf_rows, styles,
        col_widths=[page_w * 0.4, page_w * 0.6],
    ))

    if review:
        perf_text = review[4]  # performance_assessment
        if perf_text:
            story.append(Spacer(1, 3 * mm))
            story.append(Paragraph("Performance Assessment:", styles["subsection"]))
            story.append(Paragraph(_clean(perf_text), styles["body"]))

    # ══════════════════════════════════════════════════════════════════
    # SECTION 3 — Covenant Monitoring
    # ══════════════════════════════════════════════════════════════════

    story.append(Paragraph("3. Covenant Monitoring", styles["section_heading"]))

    if covenants and len(covenants) > 0:
        cov_headers = ["Covenant", "Status", "Severity", "Details", "Last Tested", "Next Due"]
        cov_rows = []
        for c in covenants:
            cov_rows.append([
                c[0] or "",         # covenant_name
                c[1] or "",         # status
                c[2] or "",         # severity
                (c[3] or "")[:80],  # details (truncated)
                _fmt_date(c[4]),    # last_tested_at
                _fmt_date(c[5]),    # next_test_due_at
            ])
        cw = page_w
        story.append(_build_table(
            cov_headers, cov_rows, styles,
            col_widths=[cw * 0.18, cw * 0.10, cw * 0.10, cw * 0.30, cw * 0.16, cw * 0.16],
        ))
    else:
        story.append(Paragraph(
            "No covenant data available for this investment.", styles["body"],
        ))

    if review:
        cov_text = review[5]  # covenant_compliance
        if cov_text:
            story.append(Spacer(1, 3 * mm))
            story.append(Paragraph("AI Covenant Compliance Assessment:", styles["subsection"]))
            story.append(Paragraph(_clean(cov_text), styles["body"]))

    # ══════════════════════════════════════════════════════════════════
    # SECTION 4 — Risk Registry
    # ══════════════════════════════════════════════════════════════════

    story.append(Paragraph("4. Risk Registry", styles["section_heading"]))

    if risks and len(risks) > 0:
        risk_headers = ["Risk Type", "Level", "Trend", "Rationale"]
        risk_rows = []
        for r in risks:
            risk_rows.append([
                r[0] or "",         # risk_type
                r[1] or "",         # risk_level
                r[2] or "STABLE",   # trend
                (r[3] or "")[:120], # rationale (truncated)
            ])
        story.append(_build_table(
            risk_headers, risk_rows, styles,
            col_widths=[page_w * 0.18, page_w * 0.12, page_w * 0.12, page_w * 0.58],
        ))
    else:
        story.append(Paragraph(
            "No risk entries registered for this investment.", styles["body"],
        ))

    if review:
        risk_text = review[7]  # risk_evolution
        if risk_text:
            story.append(Spacer(1, 3 * mm))
            story.append(Paragraph("AI Risk Evolution Assessment:", styles["subsection"]))
            story.append(Paragraph(_clean(risk_text), styles["body"]))

    # ══════════════════════════════════════════════════════════════════
    # SECTION 5 — Concentration Context
    # ══════════════════════════════════════════════════════════════════

    story.append(Paragraph("5. Concentration Context", styles["section_heading"]))

    concentration = monitoring_output.get("concentration") or monitoring_output.get("concentration_analysis") or {}
    if concentration and isinstance(concentration, dict):
        conc_items = []
        if concentration.get("fund_exposure_pct") is not None:
            conc_items.append(["Fund Exposure %", _fmt_pct(concentration["fund_exposure_pct"])])
        if concentration.get("manager_exposure_pct") is not None:
            conc_items.append(["Manager Exposure %", _fmt_pct(concentration["manager_exposure_pct"])])
        limit_breached = concentration.get("limit_breached", False)
        conc_items.append(["Limit Breached", "YES" if limit_breached else "No"])
        board_override = concentration.get("requires_board_override", False)
        conc_items.append(["Requires Board Override", "YES" if board_override else "No"])

        if conc_items:
            story.append(_build_table(
                ["Metric", "Value"], conc_items, styles,
                col_widths=[page_w * 0.4, page_w * 0.6],
            ))

        summary = concentration.get("summary") or concentration.get("executive_summary") or ""
        if summary:
            story.append(Paragraph(_clean(summary), styles["body"]))
    else:
        story.append(Paragraph(
            "No concentration data available in monitoring output.", styles["body"],
        ))

    # ══════════════════════════════════════════════════════════════════
    # SECTION 6 — Macro Context Snapshot
    # ══════════════════════════════════════════════════════════════════

    story.append(Paragraph("6. Macro Context Snapshot", styles["section_heading"]))

    macro = monitoring_output.get("macro_context") or monitoring_output.get("macro") or {}
    if macro and isinstance(macro, dict):
        macro_items = []
        if macro.get("risk_free_10y") is not None:
            macro_items.append(["Risk-free 10Y", f"{macro['risk_free_10y']}%"])
        if macro.get("yield_curve_2s10s") is not None:
            macro_items.append(["Yield Curve 2s10s", f"{macro['yield_curve_2s10s']} bps"])
        if macro.get("baa_spread_proxy") is not None:
            macro_items.append(["Baa Spread Proxy", f"{macro['baa_spread_proxy']} bps"])
        if macro.get("recession_flag") is not None:
            rf = macro["recession_flag"]
            macro_items.append(["Recession Flag", "YES" if rf else "No"])
        if macro.get("macro_stress_flag") is not None:
            msf = macro["macro_stress_flag"]
            macro_items.append(["Macro Stress Flag", _clean(str(msf))])

        if macro_items:
            story.append(_build_table(
                ["Indicator", "Value"], macro_items, styles,
                col_widths=[page_w * 0.4, page_w * 0.6],
            ))
        else:
            story.append(Paragraph("Macro indicators present but empty.", styles["body"]))
    else:
        story.append(Paragraph(
            "No macro context snapshot available.", styles["body"],
        ))

    # ══════════════════════════════════════════════════════════════════
    # SECTION 7 — Board Brief Narrative
    # ══════════════════════════════════════════════════════════════════

    story.append(Paragraph("7. Board Brief Narrative", styles["section_heading"]))

    if brief:
        sections = [
            ("Executive Summary", brief[0]),
            ("Performance View", brief[1]),
            ("Covenant View", brief[2]),
            ("Liquidity View", brief[3]),
            ("Risk Reclassification", brief[4]),
        ]
        for title, text in sections:
            if text:
                story.append(Paragraph(title, styles["subsection"]))
                story.append(Paragraph(_clean(text), styles["body"]))

        recommended_actions = brief[5] or []
        if recommended_actions and isinstance(recommended_actions, list):
            story.append(Paragraph("Recommended Actions", styles["subsection"]))
            for action in recommended_actions:
                story.append(Paragraph(f"• {_clean(action)}", styles["body"]))
    else:
        story.append(Paragraph(
            "No board monitoring brief has been generated.", styles["body"],
        ))

    # ══════════════════════════════════════════════════════════════════
    # SECTION 8 — Liquidity & Valuation (from review)
    # ══════════════════════════════════════════════════════════════════

    if review:
        liq_text = review[8]  # liquidity_assessment
        val_text = review[9]  # valuation_view
        if liq_text or val_text:
            story.append(Paragraph("8. Liquidity &amp; Valuation", styles["section_heading"]))
            if liq_text:
                story.append(Paragraph("Liquidity Assessment:", styles["subsection"]))
                story.append(Paragraph(_clean(liq_text), styles["body"]))
            if val_text:
                story.append(Paragraph("Valuation View:", styles["subsection"]))
                story.append(Paragraph(_clean(val_text), styles["body"]))

    # ══════════════════════════════════════════════════════════════════
    # APPENDIX placeholder
    # ══════════════════════════════════════════════════════════════════

    story.append(PageBreak())
    story.append(Paragraph("Appendix", styles["section_heading"]))
    story.append(Paragraph(
        "Reserved for future annexes: cashflow waterfall charts, "
        "covenant test history, concentration heatmaps.",
        styles["body"],
    ))

    # ══════════════════════════════════════════════════════════════════
    # DISCLAIMER
    # ══════════════════════════════════════════════════════════════════

    story.append(Spacer(1, 10 * mm))
    story.append(HRFlowable(
        width="100%", thickness=0.3, color=MED_GREY,
        spaceAfter=3 * mm,
    ))
    story.append(Paragraph(
        "DISCLAIMER: This report was generated by Netz International's AI Periodic Review Engine. "
        "The analysis is based on portfolio monitoring data, covenant registers, and risk assessments "
        "available at generation time. AI-generated content may contain errors or omissions and "
        "should be reviewed by qualified investment professionals. This document is confidential "
        "and intended for internal use by authorised personnel of Netz International only.",
        styles["disclaimer"],
    ))

    # ── Build PDF ─────────────────────────────────────────────────────

    def _on_page(canvas, doc):
        _header_footer(canvas, doc, investment_name, as_of)

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    logger.info("PDF generated: %s", output_path)

    return output_path


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate Periodic Review PDF Report")
    parser.add_argument("--investment-id", type=str, required=True, help="Investment UUID")
    parser.add_argument("--review-id", type=str, default=None, help="Specific review UUID (optional)")
    parser.add_argument("--output", "-o", type=str, help="Output PDF path")
    args = parser.parse_args()

    print("\n" + "=" * 72)
    print("  NETZ AI — PERIODIC REVIEW PDF REPORT GENERATOR")
    print("=" * 72)

    print(f"\n▸ Loading review data for investment: {args.investment_id} ...")
    data = _load_review_data(investment_id=args.investment_id, review_id=args.review_id)

    has_review = data["review"] is not None
    has_brief = data["brief"] is not None

    print(f"  Investment: {data['investment_name']}")
    print(f"  Manager: {data['manager_name']}")
    print(f"  Review: {'Yes' if has_review else 'No'}")
    print(f"  Covenants: {len(data['covenants'])}")
    print(f"  Risks: {len(data['risks'])}")
    print(f"  Board Brief: {'Yes' if has_brief else 'No'}")

    print("\n▸ Generating PDF ...")
    path = generate_pdf(data, output_path=args.output)

    size_kb = os.path.getsize(path) / 1024
    print(f"\n  ✓ PDF written to: {path}")
    print(f"  ✓ Size: {size_kb:.1f} KB")
    print("\n" + "=" * 72 + "\n")

    return path


if __name__ == "__main__":
    main()
