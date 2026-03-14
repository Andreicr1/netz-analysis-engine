"""Deep Review PDF Report Generator — ReportLab / Unicode.

Migrated from FPDF2 to ReportLab Platypus, sharing the canonical
pdf_base.py module for logos, branding, cover page, styles, and header/footer.

Reads persisted AI deep review data from Postgres (DealIntelligenceProfile,
DealRiskFlag, DealICBrief, InvestmentMemorandumDraft) and renders a
professional IC-grade PDF document addressed to the Investment Committee.

Usage:
    cd backend
    python -m ai_engine.pdf.generate_deep_review_pdf --deal "Garrington Capital"
    python -m ai_engine.pdf.generate_deep_review_pdf --deal-id <UUID>
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from dotenv import load_dotenv
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from ai_engine.pdf.pdf_base import (
    AMBER,
    GREEN,
    MED_GREY,
    RED,
    WHITE,
    build_ic_cover_story,
    build_institutional_table,
    build_netz_styles,
    create_netz_document,
    netz_header_footer,
    safe_text,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("deep_review_pdf")


# ── Data retrieval ────────────────────────────────────────────────────


def _load_review_data(
    deal_name: str | None = None,
    deal_id: str | None = None,
) -> dict:
    """Load all deep review artefacts from Postgres."""
    from sqlalchemy import text as sa_text

    db = async_session_factory()
    try:
        if deal_id:
            row = db.execute(
                sa_text(
                    "SELECT id, deal_name, title, sponsor_name, borrower_name, fund_id "
                    "FROM pipeline_deals WHERE id = :did"
                ),
                {"did": deal_id},
            ).fetchone()
        else:
            row = db.execute(
                sa_text(
                    "SELECT id, deal_name, title, sponsor_name, borrower_name, fund_id "
                    "FROM pipeline_deals WHERE deal_name ILIKE :n LIMIT 1"
                ),
                {"n": f"%{deal_name}%"},
            ).fetchone()

        if not row:
            raise ValueError(f"Deal not found: {deal_name or deal_id}")

        did = str(row[0])
        fid = str(row[5])
        name = row[1] or row[2] or "Unknown"
        spon = row[3] or row[4] or "Unknown"

        profile = db.execute(
            sa_text(
                "SELECT strategy_type, geography, sector_focus, target_return, "
                "risk_band, liquidity_profile, capital_structure_type, "
                "key_risks, differentiators, summary_ic_ready, last_ai_refresh "
                "FROM deal_intelligence_profiles WHERE deal_id = :d AND fund_id = :f"
            ),
            {"d": did, "f": fid},
        ).fetchone()

        risks = db.execute(
            sa_text(
                "SELECT risk_type, severity, reasoning "
                "FROM deal_risk_flags WHERE deal_id = :d AND fund_id = :f "
                "ORDER BY CASE severity WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END"
            ),
            {"d": did, "f": fid},
        ).fetchall()

        brief = db.execute(
            sa_text(
                "SELECT executive_summary, opportunity_overview, return_profile, "
                "downside_case, risk_summary, comparison_peer_funds, recommendation_signal "
                "FROM deal_ic_briefs WHERE deal_id = :d AND fund_id = :f"
            ),
            {"d": did, "f": fid},
        ).fetchone()

        im = db.execute(
            sa_text(
                "SELECT version_tag, executive_summary, opportunity_overview, "
                "investment_terms_section, corporate_structure_section, "
                "return_profile_section, downside_case_section, "
                "risk_summary_section, peer_comparison_section, "
                "recommendation, recommendation_rationale, generated_at, model_version "
                "FROM investment_memorandum_drafts WHERE deal_id = :d AND fund_id = :f "
                "ORDER BY generated_at DESC LIMIT 1"
            ),
            {"d": did, "f": fid},
        ).fetchone()

        research = db.execute(
            sa_text(
                "SELECT research_output, intelligence_status, intelligence_generated_at "
                "FROM pipeline_deals WHERE id = :d"
            ),
            {"d": did},
        ).fetchone()

        kyc = db.execute(
            sa_text(
                "SELECT entity_type, first_name, last_name, entity_name, "
                "status, total_matches, pep_hits, sanctions_hits, adverse_media_hits "
                "FROM kyc_screenings "
                "WHERE deal_id = :d AND fund_id = :f "
                "ORDER BY entity_type, entity_name"
            ),
            {"d": did, "f": fid},
        ).fetchall()

        return {
            "deal_id": did,
            "deal_name": name,
            "sponsor": spon,
            "fund_id": fid,
            "profile": profile,
            "risks": risks,
            "brief": brief,
            "im": im,
            "research": research,
            "kyc_screenings": kyc,
        }
    finally:
        db.close()


# ── Helpers ───────────────────────────────────────────────────────────


def _parse_json_field(raw: Any) -> Any:
    """Parse a field that may be a JSON string or already a dict/list."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return raw
    return raw


def _badge_para(text: str, color: Any, styles: dict) -> Paragraph:
    """Render a coloured signal badge as a centred Table-wrapped Paragraph."""
    return Paragraph(
        safe_text(text), styles["badge_green"]
    )  # overridden by Table bg below


def _signal_badge_table(
    label: str,
    color: Any,
    styles: dict,
    width_mm: float = 120,
) -> Table:
    """Return a single-cell Table that renders a filled colour badge."""
    inner_style = build_netz_styles()["body_bold"]
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.styles import ParagraphStyle

    badge_style = ParagraphStyle(
        "SignalBadge",
        parent=inner_style,
        fontSize=11,
        leading=14,
        textColor=WHITE,
        fontName="Helvetica-Bold",
        alignment=TA_CENTER,
    )
    para = Paragraph(safe_text(label), badge_style)
    tbl = Table([[para]], colWidths=[width_mm * mm], rowHeights=[10 * mm])
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), color),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    # Centre wrapper
    wrapper = Table([[tbl]], colWidths=[A4[0] - 30 * mm])
    wrapper.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return wrapper


def _risk_signal_color(severity: str) -> Any:
    """Map severity string to badge color."""
    s = (severity or "").upper()
    if s == "HIGH":
        return RED
    if s in ("MEDIUM", "MODERATE"):
        return AMBER
    return GREEN


def _rec_signal(rec: str | None) -> tuple[Any, str]:
    """Map recommendation string to (color, label)."""
    r = (rec or "CONDITIONAL").upper()
    if r == "INVEST":
        return GREEN, "IC RECOMMENDATION: INVEST"
    if r == "PASS":
        return RED, "IC RECOMMENDATION: PASS"
    return AMBER, "IC RECOMMENDATION: CONDITIONAL"


# ── PDF generation ────────────────────────────────────────────────────


def generate_pdf(data: dict, output_path: str | None = None) -> str:
    """Generate a professional IC-grade PDF from deep review data.

    Returns the output file path.
    """
    styles = build_netz_styles()
    deal_name = data["deal_name"]
    sponsor = data["sponsor"]
    profile = data["profile"]
    risks = data["risks"]
    brief = data["brief"]
    im = data["im"]
    research = data["research"]
    kyc_rows = data.get("kyc_screenings") or []

    # ── Timestamps ───────────────────────────────────────────────
    as_of = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    if profile and profile[10]:
        as_of = profile[10].strftime("%Y-%m-%d %H:%M UTC")
    elif im and im[11]:
        as_of = im[11].strftime("%Y-%m-%d %H:%M UTC")

    # ── Recommendation signal ────────────────────────────────────
    signal = "CONDITIONAL"
    signal_rationale = ""
    if brief:
        signal = brief[6] or "CONDITIONAL"
    if im:
        signal = im[9] or signal
        signal_rationale = im[10] or ""

    model_ver = im[12] if im and im[12] else "gpt-4.1"
    version_tag = im[0] if im and im[0] else ""

    # ── Research output ──────────────────────────────────────────
    research_data: dict = {}
    if research and research[0]:
        research_data = _parse_json_field(research[0]) or {}

    critic_score = research_data.get("confidence_score") or research_data.get(
        "critic_score"
    )

    # ── Document setup ───────────────────────────────────────────
    buf = BytesIO()
    doc = create_netz_document(buf, title=f"AI Deep Review — {deal_name}")
    report_title = f"AI Deep Review — {deal_name}"

    def _hf(canvas: Any, doc_inner: Any) -> None:
        netz_header_footer(
            canvas,
            doc_inner,
            report_title=report_title,
            confidentiality="CONFIDENTIAL — FOR INVESTMENT COMMITTEE USE ONLY",
        )

    story: list[Any] = []

    # ═══════════════════════════════════════════════════════════════
    # COVER PAGE  (logos + addressee + badge — shared pdf_base module)
    # ═══════════════════════════════════════════════════════════════

    story.extend(
        build_ic_cover_story(
            report_type="AI Deep Review",
            deal_name=deal_name,
            sponsor=sponsor,
            signal=signal,
            signal_rationale=signal_rationale,
            generated_at=as_of,
            model_version=model_ver,
            critic_score=critic_score,
            version_tag=version_tag,
            styles=styles,
        )
    )
    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════
    # 1. EXECUTIVE SUMMARY
    # ═══════════════════════════════════════════════════════════════

    if brief and brief[0]:
        story.append(Paragraph("1. Executive Summary", styles["section_heading"]))
        story.append(Paragraph(safe_text(brief[0]), styles["body"]))

    # ═══════════════════════════════════════════════════════════════
    # 2. DEAL PROFILE
    # ═══════════════════════════════════════════════════════════════

    if profile:
        story.append(Paragraph("2. Deal Profile", styles["section_heading"]))

        profile_data = [
            ["Field", "Value"],
            ["Strategy Type", safe_text(profile[0])],
            ["Geography", safe_text(profile[1])],
            ["Sector Focus", safe_text(profile[2])],
            ["Target Return", safe_text(profile[3])],
            ["Risk Band", safe_text(profile[4])],
            ["Liquidity Profile", safe_text(profile[5])],
            ["Capital Structure", safe_text(profile[6])],
        ]
        story.append(
            build_institutional_table(
                profile_data,
                col_widths=[55 * mm, 120 * mm],
                styles=styles,
            )
        )
        story.append(Spacer(1, 3 * mm))

        # Differentiators
        diffs = _parse_json_field(profile[8])
        if diffs:
            if isinstance(diffs, str):
                diffs = [diffs]
            story.append(Paragraph("Key Differentiators", styles["subsection"]))
            for d in diffs:
                story.append(Paragraph(f"•  {safe_text(str(d))}", styles["body"]))

    # ═══════════════════════════════════════════════════════════════
    # 3. OPPORTUNITY OVERVIEW
    # ═══════════════════════════════════════════════════════════════

    if brief and brief[1]:
        story.append(Paragraph("3. Opportunity Overview", styles["section_heading"]))
        story.append(Paragraph(safe_text(brief[1]), styles["body"]))

    # ═══════════════════════════════════════════════════════════════
    # 4. INVESTMENT TERMS
    # ═══════════════════════════════════════════════════════════════

    if im and im[3]:
        terms = _parse_json_field(im[3])
        story.append(Paragraph("4. Investment Terms", styles["section_heading"]))
        if isinstance(terms, dict):
            rows = [["Term", "Detail"]]
            for k, v in terms.items():
                label = k.replace("_", " ").title()
                val = ", ".join(str(i) for i in v) if isinstance(v, list) else str(v)
                rows.append([label, safe_text(val)])
            story.append(
                build_institutional_table(
                    rows,
                    col_widths=[60 * mm, 115 * mm],
                    styles=styles,
                )
            )
        else:
            story.append(Paragraph(safe_text(str(terms)), styles["body"]))
        story.append(Spacer(1, 3 * mm))

    # ═══════════════════════════════════════════════════════════════
    # 5. CORPORATE STRUCTURE
    # ═══════════════════════════════════════════════════════════════

    if im and im[4]:
        struct = _parse_json_field(im[4])
        story.append(Paragraph("5. Corporate Structure", styles["section_heading"]))
        if isinstance(struct, dict):
            rows = [["Element", "Detail"]]
            for k, v in struct.items():
                label = k.replace("_", " ").title()
                val = ", ".join(str(i) for i in v) if isinstance(v, list) else str(v)
                rows.append([label, safe_text(val)])
            story.append(
                build_institutional_table(
                    rows,
                    col_widths=[60 * mm, 115 * mm],
                    styles=styles,
                )
            )
        else:
            story.append(Paragraph(safe_text(str(struct)), styles["body"]))
        story.append(Spacer(1, 3 * mm))

    # ═══════════════════════════════════════════════════════════════
    # 6. RETURN PROFILE
    # ═══════════════════════════════════════════════════════════════

    if brief and brief[2]:
        story.append(Paragraph("6. Return Profile", styles["section_heading"]))
        story.append(Paragraph(safe_text(brief[2]), styles["body"]))

    # ═══════════════════════════════════════════════════════════════
    # 7. RISK ANALYSIS
    # ═══════════════════════════════════════════════════════════════

    story.append(Paragraph("7. Risk Analysis", styles["section_heading"]))

    if risks:
        risk_rows = [["Risk Factor", "Severity", "Reasoning / Mitigation"]]
        for r in risks:
            risk_rows.append(
                [
                    safe_text(str(r[0])),
                    safe_text(r[1] or "LOW"),
                    safe_text(str(r[2])[:300]),
                ]
            )
        story.append(
            build_institutional_table(
                risk_rows,
                col_widths=[55 * mm, 22 * mm, 98 * mm],
                styles=styles,
            )
        )
        story.append(Spacer(1, 3 * mm))

    if brief and brief[4]:
        story.append(Paragraph("Risk Summary", styles["subsection"]))
        story.append(Paragraph(safe_text(brief[4]), styles["body"]))

    # ═══════════════════════════════════════════════════════════════
    # 8. DOWNSIDE CASE
    # ═══════════════════════════════════════════════════════════════

    if brief and brief[3]:
        story.append(Paragraph("8. Downside Case", styles["section_heading"]))
        story.append(Paragraph(safe_text(brief[3]), styles["body"]))

    # ═══════════════════════════════════════════════════════════════
    # 9. PEER COMPARISON
    # ═══════════════════════════════════════════════════════════════

    if brief and brief[5]:
        story.append(Paragraph("9. Peer Comparison", styles["section_heading"]))
        story.append(Paragraph(safe_text(brief[5]), styles["body"]))

    # ═══════════════════════════════════════════════════════════════
    # 10–13. STRUCTURED INTELLIGENCE (from research_output)
    # ═══════════════════════════════════════════════════════════════

    if research_data:
        # Investment thesis
        thesis = research_data.get("investment_thesis", {})
        if isinstance(thesis, dict) and (
            thesis.get("strengths") or thesis.get("weaknesses")
        ):
            story.append(Paragraph("10. Investment Thesis", styles["section_heading"]))

            strengths = thesis.get("strengths", [])
            if strengths:
                story.append(Paragraph("Strengths", styles["subsection"]))
                for s in strengths:
                    story.append(
                        Paragraph(
                            f"<font color='green'>+</font>  {safe_text(str(s))}",
                            styles["body"],
                        )
                    )

            weaknesses = thesis.get("weaknesses", [])
            if weaknesses:
                story.append(Paragraph("Weaknesses", styles["subsection"]))
                for w in weaknesses:
                    story.append(
                        Paragraph(
                            f"<font color='red'>-</font>  {safe_text(str(w))}",
                            styles["body"],
                        )
                    )

            rec = thesis.get("recommendation", "")
            if rec:
                story.append(Paragraph("Recommendation Note", styles["subsection"]))
                story.append(Paragraph(safe_text(rec), styles["body"]))

        # Exit scenarios
        exits = research_data.get("exit_scenarios", [])
        if exits:
            story.append(Paragraph("11. Exit Scenarios", styles["section_heading"]))
            exit_rows = [["Scenario", "Probability", "Timeline", "Recovery"]]
            for ex in exits:
                exit_rows.append(
                    [
                        safe_text(ex.get("scenario", "")),
                        safe_text(str(ex.get("probability", ""))),
                        safe_text(ex.get("timeline", "")),
                        safe_text(ex.get("recovery", "")),
                    ]
                )
            story.append(
                build_institutional_table(
                    exit_rows,
                    col_widths=[60 * mm, 30 * mm, 40 * mm, 45 * mm],
                    styles=styles,
                )
            )
            story.append(Spacer(1, 3 * mm))

        # Comparable deals
        comps = research_data.get("comparables", [])
        if comps:
            story.append(Paragraph("12. Comparable Deals", styles["section_heading"]))
            comp_rows = [["Deal Name", "Similarity", "Outcome"]]
            for c in comps:
                comp_rows.append(
                    [
                        safe_text(c.get("deal_name", "")),
                        safe_text(c.get("similarity", "")),
                        safe_text(c.get("outcome", "")),
                    ]
                )
            story.append(
                build_institutional_table(
                    comp_rows,
                    col_widths=[60 * mm, 60 * mm, 55 * mm],
                    styles=styles,
                )
            )
            story.append(Spacer(1, 3 * mm))

        # Investment memo text (if available)
        memo = research_data.get("investment_memo", "")
        if memo and len(memo) > 200:
            story.append(
                Paragraph("13. Full Investment Memorandum", styles["section_heading"])
            )
            for para in memo.split("\n\n"):
                para = para.strip()
                if para:
                    story.append(Paragraph(safe_text(para), styles["body"]))

    # ═══════════════════════════════════════════════════════════════
    # IC RECOMMENDATION (final)
    # ═══════════════════════════════════════════════════════════════

    story.append(Paragraph("IC Recommendation", styles["section_heading"]))

    sig_color, sig_label = _rec_signal(signal)
    story.append(Spacer(1, 3 * mm))
    story.append(_signal_badge_table(sig_label, sig_color, styles))
    story.append(Spacer(1, 5 * mm))

    if im and im[10]:
        story.append(Paragraph("Rationale", styles["subsection"]))
        story.append(Paragraph(safe_text(im[10]), styles["body"]))

    # ═══════════════════════════════════════════════════════════════
    # APPENDIX I — KYC / AML SCREENING RESULTS
    # ═══════════════════════════════════════════════════════════════

    if kyc_rows:
        story.append(PageBreak())
        story.append(
            Paragraph(
                "Appendix I — KYC / AML Screening Results",
                styles["section_heading"],
            )
        )
        story.append(Spacer(1, 3 * mm))
        story.append(
            Paragraph(
                "Automated screening performed via KYC Spider against PEP, Sanctions, "
                "and Adverse Media databases. Results below cover all entities and key "
                "persons identified during the Deep Review analysis.",
                styles["body"],
            )
        )
        story.append(Spacer(1, 4 * mm))

        # Separate persons and organisations
        person_rows = [r for r in kyc_rows if r[0] == "PERSON"]
        org_rows = [r for r in kyc_rows if r[0] == "ORGANISATION"]

        def _status_label(status: str) -> str:
            s = (status or "PENDING").upper()
            if s == "CLEARED":
                return '<font color="#00875A">CLEARED</font>'
            if s == "FLAGGED":
                return '<font color="#DE350B">FLAGGED</font>'
            return f'<font color="#FF991F">{s}</font>'

        # -- Organisations table -----------------------------------------
        if org_rows:
            story.append(Paragraph("Organisation Screening", styles["subsection"]))
            org_tdata: list[list[str | Paragraph]] = [
                ["Entity Name", "Status", "Matches", "PEP", "Sanctions", "Adv. Media"]
            ]
            for r in org_rows:
                # r: entity_type(0), first(1), last(2), entity_name(3), status(4),
                #    total(5), pep(6), sanctions(7), adverse(8)
                org_tdata.append(
                    [
                        safe_text(r[3] or ""),
                        Paragraph(_status_label(r[4]), styles["body"]),
                        str(r[5] or 0),
                        str(r[6] or 0),
                        str(r[7] or 0),
                        str(r[8] or 0),
                    ]
                )
            story.append(
                build_institutional_table(
                    org_tdata,
                    col_widths=[55 * mm, 25 * mm, 20 * mm, 20 * mm, 25 * mm, 25 * mm],
                    styles=styles,
                )
            )
            story.append(Spacer(1, 4 * mm))

        # -- Key Persons table -------------------------------------------
        if person_rows:
            story.append(Paragraph("Key Person Screening", styles["subsection"]))
            person_tdata: list[list[str | Paragraph]] = [
                ["Person Name", "Status", "Matches", "PEP", "Sanctions", "Adv. Media"]
            ]
            for r in person_rows:
                name = f"{r[1] or ''} {r[2] or ''}".strip() or r[3] or ""
                person_tdata.append(
                    [
                        safe_text(name),
                        Paragraph(_status_label(r[4]), styles["body"]),
                        str(r[5] or 0),
                        str(r[6] or 0),
                        str(r[7] or 0),
                        str(r[8] or 0),
                    ]
                )
            story.append(
                build_institutional_table(
                    person_tdata,
                    col_widths=[55 * mm, 25 * mm, 20 * mm, 20 * mm, 25 * mm, 25 * mm],
                    styles=styles,
                )
            )
            story.append(Spacer(1, 4 * mm))

        # -- Summary counts -
        cleared = sum(1 for r in kyc_rows if (r[4] or "").upper() == "CLEARED")
        flagged = sum(1 for r in kyc_rows if (r[4] or "").upper() == "FLAGGED")
        total = len(kyc_rows)
        story.append(
            Paragraph(
                f"<b>Summary:</b> {total} entities screened — "
                f"{cleared} cleared, {flagged} flagged.",
                styles["body"],
            )
        )

    # ═══════════════════════════════════════════════════════════════
    # DISCLAIMER
    # ═══════════════════════════════════════════════════════════════

    story.append(Spacer(1, 6 * mm))
    story.append(
        HRFlowable(
            width="100%",
            thickness=0.3,
            color=MED_GREY,
            spaceAfter=3 * mm,
        )
    )
    story.append(
        Paragraph(
            "DISCLAIMER: This report was generated by Netz Private Credit OS, an AI-assisted "
            "investment analysis platform, and is addressed exclusively to the members of the "
            "Investment Committee of Netz Private Credit Fund. The analysis is based on documents "
            "available in the deal data room at the time of generation and should be reviewed by "
            "qualified investment professionals before any investment decision is made. "
            "AI-generated content may contain errors or omissions. Unauthorised distribution is "
            "strictly prohibited.",
            styles["disclaimer"],
        )
    )

    # ── Build ─────────────────────────────────────────────────────
    doc.build(story, onFirstPage=_hf, onLaterPages=_hf)

    if not output_path:
        safe_name = deal_name.replace(" ", "_").lower()
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            f"_deep_review_{safe_name}.pdf",
        )

    with open(output_path, "wb") as f:
        f.write(buf.getvalue())

    return output_path


# ── CLI ───────────────────────────────────────────────────────────────


def _generate_v4_pdf(deal_id: str, output: str | None = None) -> str:
    """Generate PDF from V4 memo_chapters table via memo_md_to_pdf."""
    import tempfile

    from sqlalchemy import select

    from ai_engine.pdf.memo_md_to_pdf import generate_memo_pdf
    from app.domains.credit.modules.ai.models import MemoChapter

    SessionLocal = async_session_factory
    db = SessionLocal()
    try:
        chapters = db.execute(
            select(MemoChapter)
            .where(MemoChapter.deal_id == deal_id, MemoChapter.is_current.is_(True))
            .order_by(MemoChapter.chapter_number)
        ).scalars().all()

        if not chapters:
            raise SystemExit(f"No V4 memo chapters found for deal_id={deal_id}")

        md_parts = []
        for ch in chapters:
            # Strip leading heading from content_md if the LLM repeated it
            content = (ch.content_md or "").strip()
            if content:
                first_line = content.split("\n", 1)[0].strip()
                if re.match(r"^#{1,2}\s+", first_line):
                    # Remove the LLM-echoed heading (first line only)
                    content = content.split("\n", 1)[1].strip() if "\n" in content else ""
            md_parts.append(f"## {ch.chapter_number}. {ch.chapter_title}\n\n{content}")

        md_text = "\n\n---\n\n".join(md_parts)

        md_path = tempfile.mktemp(suffix=".md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_text)

        if not output:
            safe = deal_id.replace("-", "")[:12]
            output = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                f"_deep_review_v4_{safe}.pdf",
            )

        path = generate_memo_pdf(md_path, output)
        os.unlink(md_path)
        return path
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Generate AI Deep Review PDF (ReportLab / Unicode)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--deal", type=str, help="Deal name (partial match)")
    group.add_argument("--deal-id", type=str, help="Deal UUID")
    parser.add_argument("--output", "-o", type=str, help="Output PDF path")
    parser.add_argument("--v4", action="store_true", help="Use V4 memo_chapters (14-chapter format)")
    args = parser.parse_args()

    print("\n" + "=" * 72)
    print("  NETZ AI — AI DEEP REVIEW PDF (ReportLab / Unicode)")
    print("=" * 72)

    if args.v4:
        deal_id = args.deal_id
        if not deal_id:
            raise SystemExit("--v4 mode requires --deal-id (UUID)")
        print(f"\n  [V4] Generating 14-chapter PDF for deal_id={deal_id} ...")
        path = _generate_v4_pdf(deal_id, output=args.output)
        size_kb = os.path.getsize(path) / 1024
        print(f"\n  PDF written to: {path}")
        print(f"  Size: {size_kb:.1f} KB")
        print("\n" + "=" * 72 + "\n")
        return path

    print(f"\n  Loading review data for: {args.deal or args.deal_id} ...")
    data = _load_review_data(deal_name=args.deal, deal_id=args.deal_id)

    print(f"  Deal:    {data['deal_name']}")
    print(f"  Profile: {'Yes' if data['profile'] else 'No'}")
    print(f"  Risks:   {len(data['risks'])}")
    print(f"  IC Brief:{' Yes' if data['brief'] else ' No'}")
    print(f"  IM Draft:{' Yes' if data['im'] else ' No'}")
    print(f"  Research:{' Yes' if data['research'] and data['research'][0] else ' No'}")

    out = args.output
    if not out:
        safe_name = data["deal_name"].replace(" ", "_").lower()
        out = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            f"_deep_review_{safe_name}.pdf",
        )

    print("\n  Generating PDF ...")
    path = generate_pdf(data, output_path=out)

    size_kb = os.path.getsize(path) / 1024
    print(f"\n  PDF written to: {path}")
    print(f"  Size: {size_kb:.1f} KB")
    print("\n" + "=" * 72 + "\n")
    return path


if __name__ == "__main__":
    main()
