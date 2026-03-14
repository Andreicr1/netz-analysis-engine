"""Pipeline Intelligence — Institutional PDF Generator (ReportLab / Unicode).

Uses the shared pdf_base.py for branding, styles, logos, and header/footer.

Usage:
    python -m ai_engine.pdf.pipeline_memo_pdf --deal-id <UUID>
    python -m ai_engine.pdf.pipeline_memo_pdf --deal "Garrington"
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime
from io import BytesIO

from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, PageBreak, Paragraph, Spacer

from ai_engine.pdf.pdf_base import (
    MED_GREY,
    build_ic_cover_story,
    build_institutional_table,
    build_netz_styles,
    create_netz_document,
    netz_header_footer,
    safe_text,
)


def _load_pipeline_data(deal_name=None, deal_id=None):
    from sqlalchemy import text as sa_text
    db = async_session_factory()
    try:
        q = ("SELECT id, deal_name, title, sponsor_name, borrower_name, fund_id, "
             "research_output, intelligence_status, intelligence_generated_at "
             "FROM pipeline_deals WHERE ")
        if deal_id:
            row = db.execute(sa_text(q + "id = :v"), {"v": deal_id}).fetchone()
        else:
            row = db.execute(sa_text(q + "deal_name ILIKE :v LIMIT 1"), {"v": f"%{deal_name}%"}).fetchone()
        if not row:
            raise ValueError(f"Deal not found: {deal_name or deal_id}")
        research = row[6]
        if isinstance(research, str):
            research = json.loads(research)
        return {"deal_id": str(row[0]), "deal_name": row[1] or row[2] or "Unknown",
                "sponsor": row[3] or row[4] or "Unknown", "fund_id": str(row[5]),
                "research_output": research or {}, "status": row[7], "generated_at": row[8]}
    finally:
        db.close()


def _parse_memo_sections(memo_text):
    if not memo_text:
        return []
    memo_text = re.sub(r"\*\*", "", memo_text)
    memo_text = re.sub(r"^#{1,6}\s+", "", memo_text, flags=re.MULTILINE)
    pattern = re.compile(r"^(\d{1,2})\.\s+(.+)$", re.MULTILINE)
    sections, last_h, last_pos = [], None, 0
    for m in pattern.finditer(memo_text):
        if last_h:
            sections.append({"heading": last_h, "body": memo_text[last_pos:m.start()].strip()})
        last_h, last_pos = f"{m.group(1)}. {m.group(2).strip()}", m.end()
    if last_h:
        sections.append({"heading": last_h, "body": memo_text[last_pos:].strip()})
    return sections


def generate_pipeline_memo_pdf(data, output_path=None):
    styles    = build_netz_styles()
    ro        = data.get("research_output", {})
    deal_name = data.get("deal_name", "Unknown")
    sponsor   = data.get("sponsor", "Unknown")
    gen_at    = data.get("generated_at")
    as_of     = gen_at.strftime("%Y-%m-%d %H:%M UTC") if gen_at else datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    thesis    = ro.get("investment_thesis", {}) or {}
    signal    = thesis.get("recommendation", "") if isinstance(thesis, dict) else ""
    sig_rat   = thesis.get("recommendation_rationale", "") if isinstance(thesis, dict) else ""
    meta      = ro.get("_meta", {}) or {}

    buf = BytesIO()
    doc = create_netz_document(buf, title=f"IC Memorandum — {deal_name}")

    def _hf(canvas, d):
        netz_header_footer(canvas, d,
            report_title=f"Pipeline Intelligence — {deal_name}",
            confidentiality="CONFIDENTIAL — FOR INTERNAL USE ONLY")

    story = []
    story.extend(build_ic_cover_story(
        report_type="Pipeline Intelligence Memorandum",
        deal_name=deal_name, sponsor=sponsor, signal=signal,
        signal_rationale=sig_rat, generated_at=as_of,
        model_version=meta.get("modelVersion", "gpt-4.1"),
        critic_score=ro.get("confidence_score"),
        version_tag=meta.get("versionTag", ""),
        styles=styles))
    story.append(PageBreak())

    # Memo sections
    sections = _parse_memo_sections(ro.get("investment_memo", ""))
    if sections:
        for sec in sections:
            story.append(Paragraph(safe_text(sec["heading"]), styles["section_heading"]))
            for p in re.split(r"\n{2,}", sec["body"]):
                if p.strip():
                    story.append(Paragraph(safe_text(p.strip()), styles["body"]))
    else:
        story.append(Paragraph("Investment Memorandum", styles["section_heading"]))
        for p in ro.get("investment_memo", "").split("\n\n"):
            if p.strip():
                story.append(Paragraph(safe_text(p.strip()), styles["body"]))

    # Risk table
    key_risks = (ro.get("risk_map") or {}).get("key_risks", [])
    if key_risks:
        story.append(Paragraph("Risk Assessment Detail", styles["section_heading"]))
        rows = [["Risk Factor", "Severity", "Detail", "Mitigation"]]
        for r in key_risks:
            rows.append([safe_text(r.get("risk","")), safe_text(r.get("severity","")),
                         safe_text(r.get("detail","")), safe_text(r.get("mitigation",""))])
        story.append(build_institutional_table(rows, col_widths=[45*mm,20*mm,55*mm,55*mm], styles=styles))
        story.append(Spacer(1, 4*mm))

    # Data room gaps
    missing = ro.get("missing_documents", [])
    if missing:
        story.append(Paragraph("Data Room Gaps", styles["section_heading"]))
        rows = [["Document Type", "Priority", "Impact"]]
        for d in missing:
            rows.append([safe_text(d.get("document_type","")), safe_text(d.get("priority","")), safe_text(d.get("reason",""))])
        story.append(build_institutional_table(rows, col_widths=[55*mm,25*mm,95*mm], styles=styles))
        story.append(Spacer(1, 4*mm))

    # Citations
    citations = ro.get("citations", [])
    if citations:
        story.append(Paragraph("Source Citations", styles["section_heading"]))
        rows = [["#", "Source Document", "Pages", "Rationale"]]
        for i, c in enumerate(citations, 1):
            pages = f"{c.get('page_start','')}–{c.get('page_end','')}" if c.get("page_start") else "—"
            rows.append([str(i), safe_text(c.get("doc","")), pages, safe_text(c.get("rationale",""))])
        story.append(build_institutional_table(rows, col_widths=[8*mm,50*mm,18*mm,99*mm], styles=styles))
        story.append(Spacer(1, 4*mm))

    # Issuer summary
    issuer_summary = ro.get("issuer_summary", {})
    if issuer_summary:
        story.append(Paragraph("Institutional Sources Detected", styles["section_heading"]))
        cat_labels = {"audit":"Audit / Advisory","rating_agency":"Rating Agency","legal":"Legal Counsel",
                      "administrator":"Fund Administrator","regulator":"Regulator","valuation":"Valuation Agent"}
        rows = [["Category", "Issuers"]]
        for cat, names in sorted(issuer_summary.items()):
            category_key = str(cat)
            category_label = cat_labels.get(category_key, category_key.replace("_"," ").title())
            issuer_names = [str(name) for name in names if name]
            rows.append([category_label, ", ".join(issuer_names)])
        story.append(build_institutional_table(rows, col_widths=[45*mm,130*mm], styles=styles))
        story.append(Spacer(1, 4*mm))

    # Disclaimer
    story.append(HRFlowable(width="100%", thickness=0.3, color=MED_GREY, spaceAfter=3*mm))
    story.append(Paragraph(
        "DISCLAIMER: This memorandum was prepared by Netz Private Credit OS, an AI-assisted "
        "investment analysis platform. The analysis is based on documents available in the deal "
        "data room at the time of generation and must be reviewed by qualified investment "
        "professionals before any investment decision is made. AI-generated content may contain "
        "errors or omissions. This document is confidential and intended exclusively for "
        "authorised members of the Investment Committee of Netz Private Credit Fund.",
        styles["disclaimer"]))

    doc.build(story, onFirstPage=_hf, onLaterPages=_hf)
    if output_path:
        with open(output_path, "wb") as f:
            f.write(buf.getvalue())
        return output_path
    return buf.getvalue()


def main():
    parser = argparse.ArgumentParser(description="Generate Pipeline Intelligence PDF")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--deal", type=str)
    group.add_argument("--deal-id", type=str)
    parser.add_argument("--output", "-o", type=str)
    args = parser.parse_args()
    data = _load_pipeline_data(deal_name=args.deal, deal_id=args.deal_id)
    out = args.output or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"_pipeline_memo_{data['deal_name'].replace(' ','_').lower()}.pdf")
    generate_pipeline_memo_pdf(data, output_path=out)
    print(f"PDF written: {out}  ({os.path.getsize(out)/1024:.1f} KB)")

if __name__ == "__main__":
    main()
