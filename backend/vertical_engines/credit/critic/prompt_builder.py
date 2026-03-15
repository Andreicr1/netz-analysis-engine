"""Critic prompt construction — system prompt + user input assembly.

Imports only from models.py (leaf dependency).
"""
from __future__ import annotations

import json
from typing import Any

from vertical_engines.credit.critic.models import INSTRUMENT_TYPE_PROFILES


def build_critic_prompt(instrument_type: str) -> str:
    """Build instrument-calibrated adversarial critic prompt.

    Replaces the static prompt with one that embeds the instrument profile
    directly into the system prompt, so the critic knows which fields are
    structurally absent and what constitutes a true fatal flaw vs a normal
    diligence gap.
    """
    profile = INSTRUMENT_TYPE_PROFILES.get(
        instrument_type, INSTRUMENT_TYPE_PROFILES["UNKNOWN"],
    )
    expected_absent = "\n".join(
        f"  - {f}" for f in profile["expected_absent"]
    ) or "  (none — all standard fields expected)"
    key_risk_dims = "\n".join(
        f"  - {d}" for d in profile["key_risk_dimensions"]
    ) or "  - Standard credit risk dimensions"
    fatal_criteria = profile["fatal_flaw_criteria"]

    return (
        "You are the IC Adversarial Critic for a diversified Cayman Islands private credit fund.\n"
        "\n"
        "Your role is NOT to reject deals because documentation is incomplete at screening stage.\n"
        "Your role is to identify TRUE structural blockers vs normal diligence gaps.\n"
        "\n"
        "Instrument type:\n"
        "\n"
        f"  INSTRUMENT_TYPE = {instrument_type}\n"
        "\n"
        "Instrument profile:\n"
        "\n"
        "Expected absent fields:\n"
        f"{expected_absent}\n"
        "\n"
        "Key risk dimensions:\n"
        f"{key_risk_dims}\n"
        "\n"
        "Fatal flaw criteria for this instrument:\n"
        f"  {fatal_criteria}\n"
        "\n"
        "CRITICAL RULES:\n"
        "\n"
        "1. Do NOT flag fatal flaws for missing fields listed in expected_absent.\n"
        '   Example: OPEN_ENDED_FUND missing "principalAmount" is NOT a flaw.\n'
        "\n"
        "2. Distinguish clearly between:\n"
        "   (A) Structural blocker = confirmed adverse term\n"
        "   (B) Diligence gap = missing information not yet provided\n"
        "\n"
        "3. Only mark a fatal flaw if:\n"
        "   - It is explicitly confirmed in documents, AND\n"
        "   - It meets the instrument-specific fatal_flaw_criteria above.\n"
        "\n"
        "4. Missing economics (coupon, IRR, fees) is NOT automatically fatal at screening stage.\n"
        "   It becomes fatal only if sponsor refuses disclosure or terms are clearly off-market.\n"
        "\n"
        "5. Liquidity policy breaches must only be triggered by explicit investor-level language:\n"
        '   "lock-up", "redemption restriction", "withdrawal prohibition", "gates".\n'
        "   Underlying loan maturity ranges must NEVER be interpreted as lock-up.\n"
        "\n"
        "Return ONLY valid JSON:\n"
        "\n"
        "{\n"
        '  "confidence_score": 0.0,\n'
        '  "fatal_flaws": [\n'
        "    {\n"
        '      "flaw": "...",\n'
        '      "instrument_relevance": "...",\n'
        '      "evidence_required": "...",\n'
        '      "confirmed": true,\n'
        '      "severity_class": "DEAL_BREAKER|SIGNIFICANT|MANAGEABLE",\n'
        '      "valuation_impact": "How this flaw affects deal valuation, pricing, or terms."\n'
        "    }\n"
        "  ],\n"
        '  "diligence_gaps": [\n'
        "    {\n"
        '      "item": "...",\n'
        '      "workstream": "FINANCIAL_DD|COMMERCIAL_DD|LEGAL_DD|OPERATIONAL_DD|REGULATORY_DD|ESG",\n'
        '      "why_it_matters": "...",\n'
        '      "priority": "HIGH|MEDIUM|LOW",\n'
        '      "status": "NOT_STARTED|REQUESTED|RECEIVED|IN_REVIEW|COMPLETE|RED_FLAG"\n'
        "    }\n"
        "  ],\n"
        '  "material_gaps": [\n'
        '    {"gap": "...", "impact": "...", "severity": "HIGH|MEDIUM"}\n'
        "  ],\n"
        '  "optimism_bias": [\n'
        '    {"claim": "...", "counter": "...", "severity": "HIGH|MEDIUM|LOW"}\n'
        "  ],\n"
        '  "portfolio_conflicts": [\n'
        '    {"conflict": "...", "affected_investments": "...", "severity": "HIGH|MEDIUM|LOW"}\n'
        "  ],\n"
        '  "citation_issues": [\n'
        '    {"claim": "...", "problem": "UNSUPPORTED|CONTRADICTED|VAGUE", "severity": "HIGH|MEDIUM|LOW"}\n'
        "  ],\n"
        '  "policy_blockers": [\n'
        "    {\n"
        '      "blocker": "...",\n'
        '      "confirmed": true,\n'
        '      "requires_board_override": true\n'
        "    }\n"
        "  ],\n"
        '  "diligence_dashboard": {\n'
        '    "financial_dd": {"completion_pct": 0, "outstanding_items": 0, "red_flags": 0},\n'
        '    "commercial_dd": {"completion_pct": 0, "outstanding_items": 0, "red_flags": 0},\n'
        '    "legal_dd": {"completion_pct": 0, "outstanding_items": 0, "red_flags": 0},\n'
        '    "operational_dd": {"completion_pct": 0, "outstanding_items": 0, "red_flags": 0},\n'
        '    "regulatory_dd": {"completion_pct": 0, "outstanding_items": 0, "red_flags": 0},\n'
        '    "esg": {"completion_pct": 0, "outstanding_items": 0, "red_flags": 0}\n'
        "  },\n"
        '  "rewrite_required": false,\n'
        '  "overall_assessment": "2-3 sentence summary of the critic position.",\n'
        '  "overall_recommendation": "INVEST|CONDITIONAL|PASS"\n'
        "}\n"
        "\n"
        "Rules:\n"
        "1. confidence_score is 0.0 to 1.0 — YOUR confidence that this deal should proceed.\n"
        "   0.0 = strong reject, 1.0 = no material concerns.\n"
        "2. If there are ANY confirmed fatal_flaws, confidence_score MUST be <= 0.3.\n"
        "3. Empty arrays are acceptable if no issues found in that category.\n"
        "4. Do NOT fabricate issues — only flag genuine concerns with evidence.\n"
        "5. Be specific: cite document sections, numbers, or analysis claims.\n"
        "6. If concentration limits are breached, flag in portfolio_conflicts.\n"
        "7. If quant data is INSUFFICIENT_DATA, flag in material_gaps.\n"
        "8. severity_class for fatal_flaws: DEAL_BREAKER = blocks investment entirely;\n"
        "   SIGNIFICANT = requires IC waiver or major structural amendment;\n"
        "   MANAGEABLE = can be addressed through standard documentation negotiations.\n"
        "9. diligence_dashboard: estimate completion % per workstream based on the\n"
        "   information available vs what would be expected for a deal of this type.\n"
        "   Count outstanding items (status != COMPLETE) and red flags (status == RED_FLAG)\n"
        "   for each workstream.\n"
    )


def build_critic_input(context: dict[str, Any]) -> str:
    """Assemble the critic input from the deep review context payload."""
    sections: list[str] = []

    # ── Instrument type context (MUST be first section) ──────────
    instrument_type = context.get("instrument_type", "UNKNOWN")
    instr_profile = INSTRUMENT_TYPE_PROFILES.get(
        instrument_type, INSTRUMENT_TYPE_PROFILES["UNKNOWN"],
    )
    sections.append("=== INSTRUMENT TYPE CONTEXT (READ FIRST) ===")
    sections.append(json.dumps({
        "instrument_type": instrument_type,
        "expected_absent_fields": instr_profile["expected_absent"],
        "key_risk_dimensions_for_this_type": instr_profile["key_risk_dimensions"],
        "fatal_flaw_criteria_for_this_type": instr_profile["fatal_flaw_criteria"],
        "instruction": (
            "The fields listed in expected_absent_fields are STRUCTURALLY ABSENT "
            "by design for this instrument type. Their absence is NOT a fatal flaw "
            "or material gap. Use fatal_flaw_criteria_for_this_type as your primary "
            "reference. Key risk dimensions listed are the areas where fatal flaws "
            "and material gaps are most likely for this instrument type."
        ),
    }, indent=2))

    # Structured analysis
    if context.get("structured_analysis"):
        sections.append("=== STRUCTURED DEAL ANALYSIS ===")
        sections.append(json.dumps(context["structured_analysis"], indent=2, default=str))

    # IC Brief
    if context.get("ic_brief"):
        sections.append("\n=== IC BRIEF ===")
        sections.append(json.dumps(context["ic_brief"], indent=2, default=str))

    # Full memo
    if context.get("full_memo"):
        memo = context["full_memo"]
        if len(memo) > 30_000:
            memo = memo[:30_000] + "\n... [TRUNCATED FOR CRITIC REVIEW]"
        sections.append("\n=== INVESTMENT MEMORANDUM ===")
        sections.append(memo)

    # Quant profile
    if context.get("quant_profile"):
        sections.append("\n=== QUANTITATIVE PROFILE ===")
        sections.append(json.dumps(context["quant_profile"], indent=2, default=str))

    # Concentration profile
    if context.get("concentration_profile"):
        sections.append("\n=== PORTFOLIO CONCENTRATION ===")
        sections.append(json.dumps(context["concentration_profile"], indent=2, default=str))

    # Policy compliance
    if context.get("policy_compliance"):
        sections.append("\n=== POLICY COMPLIANCE ===")
        sections.append(json.dumps(context["policy_compliance"], indent=2, default=str))

    # Deal fields (name, sponsor, amount)
    if context.get("deal_fields"):
        sections.append("\n=== DEAL METADATA ===")
        sections.append(json.dumps(context["deal_fields"], indent=2, default=str))

    return "\n".join(sections)
