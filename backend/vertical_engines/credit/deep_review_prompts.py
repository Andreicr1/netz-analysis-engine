"""Deep review prompts — system prompts, pre-classification, and prompt construction."""

from __future__ import annotations

from typing import Any

from ai_engine.prompts import prompt_registry
from vertical_engines.credit.deep_review_helpers import _call_openai, _trunc  # noqa: F401

# ---------------------------------------------------------------------------
# GPT structured extraction
# ---------------------------------------------------------------------------

# Legacy static prompt — retained for backward compat; new code should use
# _build_deal_review_prompt(instrument_type) below.
_DEAL_REVIEW_SYSTEM_LEGACY = prompt_registry.render("intelligence/structured_legacy.j2")

# Keep backward compat alias
_DEAL_REVIEW_SYSTEM = _DEAL_REVIEW_SYSTEM_LEGACY


def _deal_review_template_context(
    instrument_type: str,
    deal_role_map: dict[str, Any] | None = None,
    third_party_counterparties: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build shared template context for deal review prompts."""
    from vertical_engines.credit.ic_critic_engine import INSTRUMENT_TYPE_PROFILES

    profile = INSTRUMENT_TYPE_PROFILES.get(
        instrument_type,
        INSTRUMENT_TYPE_PROFILES["UNKNOWN"],
    )
    deal_role_map = deal_role_map or {}

    return {
        "instrument_type": instrument_type,
        "expected_absent": profile.get("expected_absent", []),
        "key_risk_dimensions": profile.get("key_risk_dimensions", []),
        "deal_structure": deal_role_map.get("deal_structure"),
        "borrower": deal_role_map.get("borrower", "unknown"),
        "lender": deal_role_map.get("lender", "unknown"),
        "manager": deal_role_map.get("manager", "unknown"),
        "third_party_counterparties": third_party_counterparties or [],
    }


def _pre_classify_from_corpus(
    corpus: str,
    deal_fields: dict[str, Any] | None = None,
) -> str:
    """Lightweight instrument pre-classification from raw corpus text.

    Runs BEFORE the structured analysis LLM call so the extraction prompt
    can be instrument-aware.  Uses keyword scanning — no LLM call.

    Returns a key from INSTRUMENT_TYPE_PROFILES.
    """
    text = corpus[:20_000].lower()  # scan first ~20k chars
    deal_name = ((deal_fields or {}).get("deal_name") or "").lower()
    strategy = ((deal_fields or {}).get("strategy_type") or "").lower()
    combined = f"{deal_name} {strategy} {text}"

    # ── 1. Open-ended fund ────────────────────────────────────────
    open_signals = sum(
        [
            any(x in combined for x in ["open-ended", "open ended", "evergreen"]),
            "fund" in deal_name and "closed" not in deal_name,
            any(
                x in combined
                for x in [
                    "monthly redemption",
                    "quarterly redemption",
                    "weekly redemption",
                    "daily redemption",
                ]
            ),
            any(
                x in combined
                for x in [
                    "nav per unit",
                    "nav per share",
                    "net asset value",
                ]
            ),
            any(
                x in combined
                for x in [
                    "private credit fund",
                    "debt fund",
                    "credit fund",
                    "lending fund",
                    "income fund",
                ]
            )
            and "closed" not in combined[:500],
        ],
    )
    if open_signals >= 2:
        return "OPEN_ENDED_FUND"

    # ── 2. Closed-end fund ────────────────────────────────────────
    closed_signals = sum(
        [
            any(x in combined for x in ["closed-end", "closed end", "vintage"]),
            any(
                x in combined
                for x in [
                    "capital call",
                    "drawdown",
                    "j-curve",
                    "j curve",
                ]
            ),
            any(
                x in combined
                for x in [
                    "private equity",
                    "pe fund",
                    "buyout",
                    "growth equity",
                ]
            ),
        ],
    )
    if closed_signals >= 1:
        return "CLOSED_END_FUND"

    # ── 3. Revolving credit / ABL ─────────────────────────────────
    revolving_signals = sum(
        [
            any(
                x in combined
                for x in [
                    "revolving",
                    "revolver",
                    "abl",
                    "asset-based",
                    "asset based",
                    "factoring",
                    "borrowing base",
                    "receivables",
                    "lender finance",
                    "specialty finance",
                ]
            ),
        ],
    )
    if revolving_signals >= 1:
        return "REVOLVING_CREDIT"

    # ── 4. Note or bond ───────────────────────────────────────────
    note_signals = sum(
        [
            any(
                x in combined
                for x in [
                    "debenture",
                    "structured note",
                    "certificate",
                ]
            ),
            any(x in deal_name for x in ["note", "bond"]),
        ],
    )
    if note_signals >= 1:
        return "NOTE_OR_BOND"

    # ── 5. Equity co-invest ───────────────────────────────────────
    equity_signals = sum(
        [
            any(
                x in combined
                for x in [
                    "equity co-invest",
                    "co-investment",
                    "equity participation",
                ]
            ),
        ],
    )
    if equity_signals >= 1:
        return "EQUITY_CO_INVEST"

    # ── 6. Term loan ─────────────────────────────────────────────
    term_signals = sum(
        [
            any(
                x in combined
                for x in [
                    "term loan",
                    "senior secured loan",
                    "bilateral loan",
                ]
            ),
            "maturity" in combined and ("coupon" in combined or "interest" in combined),
        ],
    )
    if term_signals >= 1:
        return "TERM_LOAN"

    return "UNKNOWN"


def _build_deal_review_prompt(
    instrument_type: str,
    deal_role_map: dict[str, Any] | None = None,
    third_party_counterparties: list[dict[str, Any]] | None = None,
) -> str:
    """Build instrument-aware structured extraction prompt."""
    return prompt_registry.render(
        "intelligence/deal_review_system_v1.j2",
        **_deal_review_template_context(
            instrument_type,
            deal_role_map=deal_role_map,
            third_party_counterparties=third_party_counterparties,
        ),
    )


# ══════════════════════════════════════════════════════════════════════
#  structured_analysis_v2 — rigorous extraction prompt
# ══════════════════════════════════════════════════════════════════════


def _build_deal_review_prompt_v2(
    instrument_type: str,
    deal_role_map: dict[str, Any] | None = None,
    third_party_counterparties: list[dict[str, Any]] | None = None,
) -> str:
    """Build v2 structured extraction prompt."""
    return prompt_registry.render(
        "intelligence/deal_review_system_v2.j2",
        **_deal_review_template_context(
            instrument_type,
            deal_role_map=deal_role_map,
            third_party_counterparties=third_party_counterparties,
        ),
    )


_PORTFOLIO_REVIEW_SYSTEM = """\
You are a portfolio monitoring analyst for a Cayman Islands private credit
fund.  Given the documentation for an active investment, produce a periodic
review as a JSON object.

═══ KPI EXTRACTION FRAMEWORK ═══

Extract and compute the following KPIs from the financial package.
For each KPI, compare to the budget / underwriting case and prior period:

  Financial KPIs:
    • Revenue vs. budget (actual, budget, variance %)
    • EBITDA / EBITDA margin (actual, budget, variance %)
    • Cash balance / liquidity position
    • Leverage ratio (Net Debt / EBITDA)
    • Interest coverage ratio (EBITDA / Interest Expense)
    • Free cash flow (FCF) and FCF yield
    • Debt service coverage ratio (DSCR)

  Underwriting Case Comparison:
    For each financial KPI above, also compare to the ORIGINAL
    underwriting / entry assumptions at the time of investment.
    This captures drift from the investment thesis — not just
    short-term budget variance.

  Operational KPIs (where applicable):
    • Occupancy rate / utilisation (real estate / infrastructure)
    • Customer / borrower concentration (top 5 exposure %)
    • Default rate / delinquency rate (lending portfolios)
    • Weighted average LTV (collateralised portfolios)
    • NAV per share / unit (fund investments)

═══ RAG FLAGGING METHODOLOGY ═══

Apply variance-to-budget thresholds for each KPI:

  🟢 GREEN:  Variance ≤ 5% of budget/underwriting case
  🟡 AMBER:  Variance 5–15% of budget/underwriting case
  🔴 RED:    Variance > 15% of budget/underwriting case OR covenant breach

For ratios (leverage, coverage, DSCR), flag based on headroom to covenant:
  🟢 GREEN:  Headroom > 20% of covenant threshold
  🟡 AMBER:  Headroom 5–20% of covenant threshold
  🔴 RED:    Headroom < 5% OR covenant breached

═══ TREND ANALYSIS ═══

For each KPI, assess the trajectory over available periods:
  • IMPROVING: ≥ 2 consecutive periods of positive movement
  • STABLE:    Variance < 2% between periods
  • DETERIORATING: ≥ 2 consecutive periods of negative movement

Flag any KPI that is GREEN but DETERIORATING — early warning signal.

═══ OUTPUT SCHEMA ═══

Return ONLY valid JSON:

{
  "executiveSummary": "2-3 sentence board-ready summary with overall position.",
  "overallRating": "GREEN|AMBER|RED",
  "kpiDashboard": [
    {
      "kpi": "Revenue",
      "actual": "...",
      "budget": "...",
      "variancePct": 0.0,
      "priorPeriod": "...",
      "vsUnderwriting": "Value at entry / original underwriting assumption",
      "underwritingVariancePct": 0.0,
      "rag": "GREEN|AMBER|RED",
      "trend": "IMPROVING|STABLE|DETERIORATING",
      "note": "..."
    }
  ],
  "performanceAssessment": "Detailed narrative assessment of financial and operational performance.",
  "covenantCompliance": {
    "status": "COMPLIANT|WATCH|BREACH",
    "covenants": [
      {
        "covenant": "...",
        "threshold": "...",
        "actual": "...",
        "headroomPct": 0.0,
        "rag": "GREEN|AMBER|RED"
      }
    ]
  },
  "materialChanges": ["List of material changes since last review period."],
  "riskEvolution": {
    "newRisks": ["..."],
    "escalatedRisks": ["Risks that moved from GREEN/AMBER to RED."],
    "mitigatedRisks": ["Risks that improved."]
  },
  "liquidityAssessment": "Cash position, runway, and liquidity risk.",
  "valuationView": "Current valuation vs. entry; mark-to-market or fair value assessment.",
  "earlyWarningSignals": ["KPIs that are GREEN but DETERIORATING or other leading indicators."],
  "recommendedActions": ["Specific, prioritised actions for the IC."],
  "nextReviewDate": "Suggested date for next review based on risk profile."
}

RULES:
- Be specific and quantitative — cite actual numbers from the financial package.
- Every KPI must have a RAG flag and trend assessment.
- If data is unavailable for a KPI, set rag to "RED" and note "Data not provided".
- The executiveSummary must be suitable for a board presentation — concise,
  factual, and action-oriented.
- Flag any KPI where trend is DETERIORATING regardless of current RAG status.
"""
