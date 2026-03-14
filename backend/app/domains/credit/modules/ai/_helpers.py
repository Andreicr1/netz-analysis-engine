"""Shared helpers for AI module sub-routers."""
from __future__ import annotations

import datetime as dt
import re as _re_mod

from fastapi import Query

from app.domains.credit.modules.documents.models import DocumentVersion


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _envelope_from_rows(rows: list) -> tuple[dt.datetime, int | None, str | None]:
    if not rows:
        return _utcnow(), None, "OK"
    as_of = max(getattr(r, "as_of", _utcnow()) for r in rows)
    data_latency_values = [getattr(r, "data_latency", None) for r in rows if getattr(r, "data_latency", None) is not None]
    data_latency = max(data_latency_values) if data_latency_values else None
    quality_values = [getattr(r, "data_quality", None) or "OK" for r in rows]
    quality = "OK" if all(v == "OK" for v in quality_values) else "DEGRADED"
    return as_of, data_latency, quality


def _limit(limit: int = Query(50, ge=1, le=200)) -> int:
    return limit


def _offset(offset: int = Query(0, ge=0, le=10_000)) -> int:
    return offset


# ─────────────────────────────────────────────────────────────────────
# CHAPTER CONTENT NORMALIZERS (shared by IC Brief + PDF generation)
# ─────────────────────────────────────────────────────────────────────

_CH01_SECTIONS = [
    "Executive Summary",
    "Deal Identity and Sponsor",
    "Transaction Rationale",
    "Key Terms (Tenor, Rate, Collateral)",
    "Key Terms",
    "Return Profile Summary",
    "Top Three Risks",
    "Recommendation Signal",
    "Fund Governance Highlights",
    "Regulatory Standing",
]


_FUND_GOVERNANCE_TEXT = (
    "The Netz Private Credit Fund is a Cayman Islands exempted company, "
    "governed by a formal Investment Committee (IC) and Board of Directors. "
    "The IC holds responsibility for investment decisions, subject to Board "
    "override. The fund\u2019s credit policy and investment policy permit "
    "documented exceptions and Board-approved overrides but require full "
    "credit memoranda, minimum analytical outputs, and explicit documentation "
    "of any guideline deviations. No hard-limit breaches or concentration "
    "overrides are triggered by this transaction; however, material "
    "soft-guideline exceptions\u2014specifically the sub-investment-grade "
    "credit profile and incomplete underwriting\u2014would require formal IC "
    "and Board acknowledgment and enhanced monitoring if the transaction were "
    "to proceed. The fund\u2019s administrator, Zedra Fund Administration "
    "(Cayman) Ltd., is regulated by the Cayman Islands Monetary Authority "
    "(CIMA) and is responsible for anti-money laundering (AML), "
    "know-your-customer (KYC) compliance, and net asset value (NAV) "
    "calculation."
)

_REGULATORY_STANDING_TEXT = (
    "The Netz Private Credit Fund is duly incorporated in the Cayman Islands, "
    "with CIMA-regulated service providers and compliance procedures in place "
    "for AML, reporting, and governance. The fund\u2019s ability to proceed "
    "with this investment is contingent upon resolution of the identified "
    "fatal flaws and diligence gaps to satisfy both regulatory requirements "
    "and internal policy standards."
)


def _replace_fund_governance_sections(md: str) -> str:
    """Replace Fund Governance / Regulatory Standing with fund-level text."""
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        stripped = lines[i].strip().rstrip("*").lstrip("*").strip()
        if stripped == "Fund Governance Highlights" or (
            lines[i].startswith("### ") and "Fund Governance Highlight" in lines[i]
        ):
            out.append("### Fund Governance Highlights")
            out.append("")
            out.append(_FUND_GOVERNANCE_TEXT)
            out.append("")
            i += 1
            while i < n and not lines[i].strip().startswith("#"):
                i += 1
            continue
        if stripped == "Regulatory Standing" or (
            lines[i].startswith("### ") and "Regulatory Standing" in lines[i]
        ):
            out.append("### Regulatory Standing")
            out.append("")
            out.append(_REGULATORY_STANDING_TEXT)
            out.append("")
            i += 1
            while i < n and not lines[i].strip().startswith("#"):
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def _normalize_ch01_headings(md: str) -> str:
    """Add ``##``/``###`` markers to known ch01 section headers."""
    lines = md.split("\n")
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            out.append(line)
            continue
        matched = False
        for sec in _CH01_SECTIONS:
            if stripped == sec:
                prefix = "## " if sec == "Executive Summary" else "### "
                out.append(prefix + sec)
                matched = True
                break
        if not matched:
            out.append(line)
    return "\n".join(out)


def _normalize_chapter_content(
    content_md: str, chapter_number: int, chapter_title: str,
) -> str:
    """Normalize a chapter's markdown for consistent heading hierarchy."""
    if not content_md:
        return content_md

    lines = content_md.split("\n")
    out: list[str] = []
    idx = 0
    n = len(lines)

    # 1. Strip chapter-title echo
    while idx < n and not lines[idx].strip():
        idx += 1
    if idx < n:
        first = lines[idx].strip()
        if not first.startswith("#"):
            _clean = lambda s: _re_mod.sub(
                r"\s+", " ",
                _re_mod.sub(r"[^a-z0-9\s]", "", s.lower().replace("&", " and ")),
            ).strip()
            if (_clean(first).startswith(_clean(chapter_title))
                    or _clean(chapter_title).startswith(_clean(first))):
                idx += 1
                if idx < n and not lines[idx].strip():
                    idx += 1

    # 2. ch01: curated known-headers
    if chapter_number == 1:
        remaining = "\n".join(lines[idx:])
        normalized = _normalize_ch01_headings(remaining)
        return _replace_fund_governance_sections(normalized)

    # 3. General sub-section heading detection
    while idx < n:
        line = lines[idx]
        stripped = line.strip()

        if stripped.startswith("#"):
            out.append(line)
            idx += 1
            continue

        if (not stripped or stripped.startswith("|") or
                stripped.startswith(">") or stripped.startswith("<") or
                _re_mod.match(r"^[-*]\s+", stripped) or
                _re_mod.match(r"^[-*_]{3,}\s*$", stripped)):
            out.append(line)
            idx += 1
            continue

        is_short = len(stripped) < 80
        no_end_punct = not _re_mod.search(r"[.!?,;:]$", stripped.rstrip())
        prev_blank = (not out) or (out and not out[-1].strip())
        next_blank = (idx + 1 >= n) or (idx + 1 < n and not lines[idx + 1].strip())
        has_soft_break = line.rstrip("\n").endswith("  ")

        if is_short and no_end_punct and prev_blank and (next_blank or has_soft_break):
            out.append(f"### {stripped.rstrip()}")
            idx += 1
            continue

        out.append(line)
        idx += 1

    return "\n".join(out)


def _blob_path_for_response(v: DocumentVersion) -> str | None:
    """Prefer container-relative blob path when possible."""
    if v.blob_path:
        if v.blob_path.startswith("dataroom/"):
            return v.blob_path
        return f"dataroom/{v.blob_path}"
    return None


_IC_MEMORANDA_CONTAINER = "investment-pipeline-intelligence"
