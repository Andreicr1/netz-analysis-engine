"""Macro Committee Review → PDF via content_report template.

Converts ``MacroReview.report_json`` into readable markdown, then renders
through the shared content-report HTML template and Playwright PDF pipeline.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from vertical_engines.wealth.pdf.html_renderer import html_to_pdf
from vertical_engines.wealth.pdf.templates.content_report import render_content_report


def _report_json_to_markdown(report_json: dict[str, Any]) -> str:
    """Convert MacroReview.report_json into readable markdown."""
    lines: list[str] = []

    # ── Regime section ────────────────────────────────────────────────
    regime = report_json.get("regime")
    if regime:
        lines.append("# Regime Assessment\n")
        global_regime = regime.get("global", "\u2014")
        lines.append(f"**Global Regime:** {global_regime}\n")

        regional = regime.get("regional", {})
        if regional:
            lines.append("## Regional Regimes\n")
            for region, regime_val in regional.items():
                lines.append(f"- **{region}:** {regime_val}")
            lines.append("")

        reasons = regime.get("composition_reasons", {})
        if reasons:
            lines.append("## Composition Rationale\n")
            for _key, val in reasons.items():
                lines.append(f"> {val}\n")

    # ── Score deltas ──────────────────────────────────────────────────
    deltas = report_json.get("score_deltas", [])
    if deltas:
        lines.append("# Regional Score Changes\n")
        lines.append("| Region | Previous | Current | Delta | Flagged |")
        lines.append("| --- | --- | --- | --- | --- |")
        for d in deltas:
            flag = "\u26a0" if d.get("flagged") else ""
            prev = d.get("previous_score", 0)
            curr = d.get("current_score", 0)
            delta = d.get("delta", 0)
            lines.append(
                f"| {d.get('region', '?')} | {prev:.1f} | {curr:.1f} | {delta:+.1f} | {flag} |"
            )
        lines.append("")

    # ── Global indicators ─────────────────────────────────────────────
    gi = report_json.get("global_indicators_delta", {})
    if gi:
        lines.append("# Global Indicators\n")
        for key, val in gi.items():
            label = key.replace("_", " ").title()
            if isinstance(val, (int, float)):
                lines.append(f"- **{label}:** {val:+.2f}")
            else:
                lines.append(f"- **{label}:** {val}")
        lines.append("")

    # ── Staleness alerts ──────────────────────────────────────────────
    alerts = report_json.get("staleness_alerts", [])
    if alerts:
        lines.append("# Data Quality Alerts\n")
        lines.append(
            f"{len(alerts)} series with stale data: {', '.join(str(a) for a in alerts[:10])}"
        )
        if len(alerts) > 10:
            lines.append(f"  *(and {len(alerts) - 10} more)*")
        lines.append("")

    # ── Material changes flag ─────────────────────────────────────────
    if report_json.get("has_material_changes"):
        lines.append("---\n")
        lines.append("**Material changes detected** \u2014 committee review required.")

    return "\n".join(lines)


async def generate_macro_review_pdf(
    report_json: dict[str, Any],
    *,
    as_of_date: date,
    language: str = "pt",
) -> bytes:
    """Generate a PDF for a macro committee review.

    Parameters
    ----------
    report_json:
        The ``MacroReview.report_json`` JSONB payload.
    as_of_date:
        Review date (used in subtitle).
    language:
        ``"pt"`` or ``"en"`` for bilingual labels.

    Returns
    -------
    bytes
        Raw PDF bytes.
    """
    md = _report_json_to_markdown(report_json)
    html = render_content_report(
        md,
        title="Macro Committee Review",
        subtitle=as_of_date.isoformat(),
        language=language,  # type: ignore[arg-type]
    )
    return await html_to_pdf(html, format="A4", print_background=True, margin_mm=0)
