"""IC Critic Engine — adversarial review of deal intelligence and memos.

Performs an independent, devil's-advocate analysis of the full deal context
to surface fatal flaws, material gaps, optimism bias, portfolio conflicts,
and citation issues that the primary analysis may have missed.

Uses a single LLM call with a specialised adversarial prompt.

This engine is consumed by Deep Review v3 Stage 7 (critic loop).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
#  Instrument type profiles — context-aware fatal flaw criteria
# ──────────────────────────────────────────────────────────────────────

INSTRUMENT_TYPE_PROFILES: dict[str, dict] = {
    "OPEN_ENDED_FUND": {
        "expected_absent": [
            "tenor", "maturity_date", "fixed_coupon", "principal_amount",
            "bullet_repayment", "call_protection", "scheduled_amortisation",
        ],
        "key_risk_dimensions": [
            "liquidity_mismatch", "redemption_gates", "nav_valuation_policy",
            "manager_governance", "concentration_limits", "fee_transparency",
            "sponsor_entity_perimeter", "fund_level_leverage",
        ],
        "fatal_flaw_criteria": (
            "Fatal flaws for open-ended funds: (1) redemption mechanics absent or "
            "inconsistent with underlying asset liquidity; (2) no gating, suspension, "
            "or side-pocket framework confirmed; (3) fee schedule (management, "
            "incentive, structuring) not disclosed; (4) valuation policy absent or "
            "unaudited; (5) sponsor/manager legal entity perimeter unclear; "
            "(6) fund-level leverage undisclosed when material. "
            "DO NOT flag missing tenor, maturity date, fixed coupon, or principal "
            "amount — these are structurally absent for open-ended funds."
        ),
    },
    "CLOSED_END_FUND": {
        "expected_absent": [
            "daily_liquidity", "redemption_on_demand", "open_ended_nav",
        ],
        "key_risk_dimensions": [
            "j_curve", "capital_call_mechanics", "gp_commitment",
            "distribution_waterfall", "key_person", "fund_term_extension",
            "recycling_provisions",
        ],
        "fatal_flaw_criteria": (
            "Fatal flaws for closed-end funds: (1) distribution waterfall mechanics "
            "absent or ambiguous; (2) committed capital sizing not confirmed; "
            "(3) GP co-investment not evidenced; (4) key-person provisions unclear; "
            "(5) fund term and extension rights not documented; "
            "(6) recycling / reinvestment provisions absent."
        ),
    },
    "TERM_LOAN": {
        "expected_absent": [],
        "key_risk_dimensions": [
            "coupon_and_coverage", "maturity_refinancing_risk", "covenant_package",
            "collateral_enforceability", "intercreditor_dynamics",
            "amortisation_schedule",
        ],
        "fatal_flaw_criteria": (
            "Fatal flaws for term loans: (1) principal amount not confirmed; "
            "(2) tenor / maturity date absent; (3) interest rate / coupon absent; "
            "(4) covenant package (maintenance or incurrence) not evidenced; "
            "(5) security package and lien position not confirmed; "
            "(6) intercreditor arrangements absent when multiple lenders exist."
        ),
    },
    "REVOLVING_CREDIT": {
        "expected_absent": [
            "fixed_maturity_bullet", "scheduled_amortisation", "call_protection",
        ],
        "key_risk_dimensions": [
            "borrowing_base_mechanics", "advance_rates", "dominion_of_funds",
            "availability_block", "field_exam_cadence", "eligible_collateral_definition",
            "springing_cash_dominion",
        ],
        "fatal_flaw_criteria": (
            "Fatal flaws for revolving credit / ABL: (1) borrowing base mechanics "
            "not defined; (2) advance rate caps absent or uncapped; "
            "(3) dominion-of-funds / cash control framework absent; "
            "(4) eligible collateral definition missing; "
            "(5) field exam / collateral audit cadence not specified. "
            "DO NOT flag missing bullet maturity or fixed amortisation schedule — "
            "these are structurally absent for revolving facilities."
        ),
    },
    "NOTE_OR_BOND": {
        "expected_absent": [],
        "key_risk_dimensions": [
            "coupon_structure", "maturity_and_call", "indenture_covenants",
            "trustee_mechanics", "cross_default_cross_acceleration",
            "change_of_control_put",
        ],
        "fatal_flaw_criteria": (
            "Fatal flaws for notes / bonds: (1) coupon rate or structure absent; "
            "(2) maturity date not confirmed; (3) indenture / trust deed terms absent; "
            "(4) trustee identity not confirmed; (5) cross-default provisions absent."
        ),
    },
    "EQUITY_CO_INVEST": {
        "expected_absent": [
            "fixed_coupon", "maturity_date", "principal_amount",
            "interest_coverage", "debt_service",
        ],
        "key_risk_dimensions": [
            "entry_valuation_and_methodology", "exit_path_and_timing",
            "drag_tag_rights", "information_rights", "anti_dilution_protection",
            "board_representation", "lead_sponsor_alignment",
        ],
        "fatal_flaw_criteria": (
            "Fatal flaws for equity co-investments: (1) entry valuation methodology "
            "not evidenced or independently validated; (2) no credible exit path "
            "identified; (3) drag-along / tag-along rights absent; "
            "(4) information rights and reporting obligations not confirmed; "
            "(5) lead sponsor alignment and co-investment track record absent. "
            "DO NOT flag missing coupon, maturity, or principal amount — "
            "these are structurally absent for equity instruments."
        ),
    },
    "UNKNOWN": {
        "expected_absent": [],
        "key_risk_dimensions": [],
        "fatal_flaw_criteria": (
            "Instrument type could not be classified from available data. "
            "Apply conservative standards: flag absence of any economic term "
            "(coupon, maturity, principal, fee schedule) as a material gap. "
            "Classify instrument type as a material gap if it cannot be determined."
        ),
    },
}


# ──────────────────────────────────────────────────────────────────────
#  Data types
# ──────────────────────────────────────────────────────────────────────


@dataclass
class CriticVerdict:
    """Result of adversarial IC review."""

    fatal_flaws: list[dict[str, str]] = field(default_factory=list)
    material_gaps: list[dict[str, str]] = field(default_factory=list)
    optimism_bias: list[dict[str, str]] = field(default_factory=list)
    portfolio_conflicts: list[dict[str, str]] = field(default_factory=list)
    citation_issues: list[dict[str, str]] = field(default_factory=list)
    macro_consistency_flags: list[dict[str, Any]] = field(default_factory=list)
    confidence_score: float = 0.0
    overall_assessment: str = ""
    rewrite_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "fatal_flaws": self.fatal_flaws,
            "material_gaps": self.material_gaps,
            "optimism_bias": self.optimism_bias,
            "portfolio_conflicts": self.portfolio_conflicts,
            "citation_issues": self.citation_issues,
            "macro_consistency_flags": self.macro_consistency_flags,
            "confidence_score": self.confidence_score,
            "overall_assessment": self.overall_assessment,
            "rewrite_required": self.rewrite_required,
        }

    @property
    def total_issues(self) -> int:
        return (
            len(self.fatal_flaws)
            + len(self.material_gaps)
            + len(self.optimism_bias)
            + len(self.portfolio_conflicts)
            + len(self.citation_issues)
            + len(self.macro_consistency_flags)
        )


# ──────────────────────────────────────────────────────────────────────
#  Prompt
# ──────────────────────────────────────────────────────────────────────

# Legacy static prompt — retained for backward compat reference.
_CRITIC_SYSTEM_LEGACY = """\
You are a senior IC Risk Critic at a Cayman Islands institutional private credit fund.
Your role is ADVERSARIAL: you are looking for reasons to REJECT this deal, not approve it.
You represent the fund's fiduciary obligation to LPs.

Given the deal context payload below — which includes the structured analysis, IC brief,
long-form investment memorandum, quantitative profile, concentration profile, and policy
compliance data — perform a rigorous independent critique.

Produce a JSON object with EXACTLY the following structure:

{
  "fatal_flaws": [
    {"issue": "...", "evidence": "citation or reasoning", "recommendation": "REJECT|ESCALATE"}
  ],
  "material_gaps": [
    {"gap": "...", "impact": "What could go wrong if this gap persists", "severity": "HIGH|MEDIUM"}
  ],
  "optimism_bias": [
    {"claim": "The original analysis states...", "counter": "However...", "severity": "HIGH|MEDIUM|LOW"}
  ],
  "portfolio_conflicts": [
    {"conflict": "...", "affected_investments": "...", "severity": "HIGH|MEDIUM|LOW"}
  ],
  "citation_issues": [
    {"claim": "...", "problem": "UNSUPPORTED|CONTRADICTED|VAGUE", "severity": "HIGH|MEDIUM|LOW"}
  ],
  "confidence_score": 0.0,
  "overall_assessment": "2-3 sentence summary of the critic's position."
}

Rules:
1. confidence_score is 0.0 to 1.0 — YOUR confidence that this deal should proceed.
   0.0 = strong reject, 1.0 = no material concerns.
2. If there are ANY fatal_flaws, confidence_score MUST be ≤ 0.3.
3. Empty arrays are acceptable if no issues found in that category.
4. Do NOT fabricate issues — only flag genuine concerns with evidence.
5. Be specific: cite document sections, numbers, or analysis claims.
6. If concentration limits are breached, flag in portfolio_conflicts.
7. If quant data is INSUFFICIENT_DATA, flag in material_gaps.
8. severity_class for fatal_flaws: DEAL_BREAKER = blocks investment entirely;
   SIGNIFICANT = requires IC waiver or major structural amendment;
   MANAGEABLE = can be addressed through standard documentation negotiations.
9. diligence_dashboard: estimate completion % per workstream based on the
   information available vs what would be expected for a deal of this type.
   Count outstanding items (status != COMPLETE) and red flags (status == RED_FLAG)
   for each workstream.
8. INSTRUMENT TYPE: The first section of the context payload is "INSTRUMENT TYPE
   CONTEXT". Read it before evaluating anything else. Fields in
   expected_absent_fields for the identified instrument type are NEVER fatal
   flaws or material gaps — they are structural characteristics of the instrument.
   Calibrate your fatal_flaw_criteria exclusively to the criteria stated for
   this instrument type.

Return ONLY the JSON object.
"""

# Active prompt is dynamically built — see _build_critic_prompt() below.
_CRITIC_SYSTEM = _CRITIC_SYSTEM_LEGACY


def _build_critic_prompt(instrument_type: str) -> str:
    """Build instrument-calibrated adversarial critic prompt.

    Replaces the static _CRITIC_SYSTEM with a prompt that embeds the
    instrument profile directly into the system prompt, so the critic
    knows which fields are structurally absent and what constitutes a
    true fatal flaw vs a normal diligence gap.
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


# ──────────────────────────────────────────────────────────────────────
#  Internal helpers
# ──────────────────────────────────────────────────────────────────────


def _classify_instrument_type(structured_analysis: dict[str, Any]) -> str:
    """Classify deal instrument type deterministically from structured analysis.

    No LLM call — pure signal matching on extracted fields.
    Returns a key from INSTRUMENT_TYPE_PROFILES.

    Classification hierarchy (first match wins):
      1. Open-ended fund  — redemption signals + NAV + "fund" language
      2. Closed-end fund  — vintage / drawdown / capital call signals
      3. Revolving credit — ABL / factoring / borrowing base signals
      4. Note or bond     — note / bond / certificate language
      5. Equity co-invest — equity / co-invest in capital structure position
      6. Term loan        — maturity + coupon both present
      7. UNKNOWN          — no signals matched
    """
    strategy = (structured_analysis.get("strategyType") or "").lower()
    capital_pos = (structured_analysis.get("capitalStructurePosition") or "").lower()
    liquidity = (structured_analysis.get("liquidityProfile") or "").lower()
    terms = structured_analysis.get("investmentTerms") or {}

    # ── 1. Open-ended fund ────────────────────────────────────────
    open_signals = [
        any(x in strategy for x in ["open-ended", "open ended", "evergreen"]),
        "fund" in strategy and "closed" not in strategy and "hedge" not in strategy,
        any(x in liquidity for x in ["monthly redemption", "daily redemption",
                                      "weekly redemption", "quarterly redemption"]),
        "nav" in liquidity,
        bool(terms.get("redemptionFrequency")),
        any(x in strategy for x in ["private credit fund", "debt fund", "credit fund"])
        and "closed" not in strategy,
    ]
    if sum(open_signals) >= 2:
        return "OPEN_ENDED_FUND"

    # ── 2. Closed-end fund ────────────────────────────────────────
    closed_signals = [
        any(x in strategy for x in ["closed-end", "closed end", "vintage"]),
        any(x in liquidity for x in ["capital call", "drawdown", "j-curve", "j curve"]),
        any(x in strategy for x in ["private equity", "pe fund", "buyout", "growth equity"]),
    ]
    if sum(closed_signals) >= 1:
        return "CLOSED_END_FUND"

    # ── 3. Revolving credit / ABL ─────────────────────────────────
    revolving_signals = [
        any(x in strategy for x in [
            "revolving", "revolver", "abl", "asset-based", "asset based",
            "factoring", "borrowing base", "receivables", "lender finance",
            "specialty finance",
        ]),
        any(x in capital_pos for x in ["revolving", "abl", "senior secured revolving"]),
    ]
    if sum(revolving_signals) >= 1:
        return "REVOLVING_CREDIT"

    # ── 4. Note or bond ───────────────────────────────────────────
    note_signals = [
        any(x in strategy for x in [
            "note", "bond", "debenture", "etn",
            "certificate", "structured note", "amc",
        ]),
        any(x in capital_pos for x in ["note", "bond", "senior note", "subordinated note"]),
    ]
    if sum(note_signals) >= 1:
        return "NOTE_OR_BOND"

    # ── 5. Equity co-invest ───────────────────────────────────────
    equity_signals = [
        any(x in capital_pos for x in ["equity", "co-invest", "co invest", "common", "preferred"]),
        any(x in strategy for x in ["equity", "co-investment", "co-invest"]),
    ]
    if sum(equity_signals) >= 1:
        return "EQUITY_CO_INVEST"

    # ── 6. Term loan (fallback for debt with explicit terms) ──────
    has_maturity = bool(terms.get("maturityDate"))
    has_coupon = bool(terms.get("interestRate") or terms.get("couponRate"))
    if has_maturity and has_coupon:
        return "TERM_LOAN"

    return "UNKNOWN"


def _build_critic_input(context: dict[str, Any]) -> str:
    """Assemble the critic input from the deep review context payload."""
    sections: list[str] = []

    # ── Instrument type context (MUST be first section) ──────────
    # This section instructs the critic which fields are structurally
    # absent for this instrument type and what constitutes a fatal flaw.
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


def _parse_critic_response(data: dict[str, Any]) -> CriticVerdict:
    """Parse LLM JSON response into a CriticVerdict dataclass."""
    verdict = CriticVerdict(
        fatal_flaws=data.get("fatal_flaws", []),
        material_gaps=data.get("material_gaps", []),
        optimism_bias=data.get("optimism_bias", []),
        portfolio_conflicts=data.get("portfolio_conflicts", []),
        citation_issues=data.get("citation_issues", []),
        confidence_score=_clamp(float(data.get("confidence_score", 0.0)), 0.0, 1.0),
        overall_assessment=data.get("overall_assessment", ""),
    )

    # Enforce consistency: fatal flaws → confidence ≤ 0.3
    if verdict.fatal_flaws and verdict.confidence_score > 0.3:
        verdict.confidence_score = 0.3

    # Rewrite required if fatal flaws or confidence < 0.4
    verdict.rewrite_required = (
        len(verdict.fatal_flaws) > 0
        or verdict.confidence_score < 0.4
    )

    return verdict


def _clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, value))


# ──────────────────────────────────────────────────────────────────────
#  Deterministic macro-consistency checks (no GPT)
# ──────────────────────────────────────────────────────────────────────


def _run_macro_consistency_checks(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Rule-based macro sanity flags.  No LLM call.

    Examines macro_snapshot, macro_stress_flag, and deal intelligence
    to surface deterministic inconsistencies an IC reviewer must see.

    Returns a (possibly empty) list of issue dicts with keys:
        type, severity, detail.
    """
    flags: list[dict[str, Any]] = []

    macro = context.get("macro_snapshot") or {}
    stress = context.get("macro_stress_flag", False)

    # Recommendation from memo / IC brief
    memo_rec = ""
    ic_brief = context.get("ic_brief") or {}
    if isinstance(ic_brief, dict):
        memo_rec = (ic_brief.get("recommendation") or "").upper()
    # Fallback — look in structured_analysis
    if not memo_rec:
        analysis = context.get("structured_analysis") or {}
        memo_rec = (analysis.get("recommendation") or "").upper()

    # Target IRR from quant profile
    quant = context.get("quant_profile") or {}
    target_irr_pct: float | None = None
    raw_irr = quant.get("target_irr_pct") or quant.get("base_irr")
    if raw_irr is not None:
        try:
            target_irr_pct = float(raw_irr)
        except (ValueError, TypeError):
            pass

    # ── Rule 1 — Exit Optimism in Stress Regime ──────────────────
    if stress and memo_rec == "STRONG BUY":
        flags.append({
            "type": "MACRO_EXIT_OPTIMISM",
            "severity": "HIGH",
            "detail": (
                "Strong recommendation during macro stress regime requires "
                "explicit refinancing downside justification."
            ),
        })

    # ── Rule 2 — Spread Regime Mismatch ──────────────────────────
    risk_free_10y = macro.get("risk_free_10y")
    if risk_free_10y is not None and target_irr_pct is not None:
        try:
            if float(risk_free_10y) > 4.5 and target_irr_pct < 9.0:
                flags.append({
                    "type": "RETURN_INADEQUATE_FOR_RATE_REGIME",
                    "severity": "HIGH",
                    "detail": (
                        "Target IRR appears insufficient relative to "
                        "current risk-free rate regime."
                    ),
                })
        except (ValueError, TypeError):
            pass

    # ── Rule 3 — Yield Curve Inversion Warning ───────────────────
    yield_curve_2s10s = macro.get("yield_curve_2s10s")
    if yield_curve_2s10s is not None:
        try:
            if float(yield_curve_2s10s) < 0:
                flags.append({
                    "type": "INVERTED_CURVE_REFINANCING_RISK",
                    "severity": "MEDIUM",
                    "detail": (
                        "Yield curve inversion increases refinancing risk; "
                        "exit timing assumptions must be conservative."
                    ),
                })
        except (ValueError, TypeError):
            pass

    if flags:
        logger.info(
            "MACRO_CONSISTENCY_FLAGS_RAISED",
            extra={"count": len(flags), "types": [f["type"] for f in flags]},
        )

    return flags


# ──────────────────────────────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────────────────────────────


def critique_intelligence(
    context: dict[str, Any],
    *,
    call_openai_fn: Any = None,
) -> CriticVerdict:
    """Run adversarial IC critique on the deep review context payload.

    Args:
        context: Dict containing keys:
            - structured_analysis: dict from Stage 2
            - ic_brief: dict from Stage 5
            - full_memo: str from Stage 6
            - quant_profile: dict from ic_quant_engine
            - concentration_profile: dict from concentration_engine
            - policy_compliance: dict from policy analysis
            - deal_fields: dict with deal_name, sponsor_name, etc.
        call_openai_fn: Callable matching _call_openai(system, user, *, max_tokens)
            signature.  Injected from deep_review.py to reuse the centralised
            OpenAI provider.

    Returns:
        CriticVerdict dataclass.

    Raises:
        ValueError: If LLM call or JSON parsing fails.

    """
    if call_openai_fn is None:
        raise ValueError("call_openai_fn must be provided — critic engine requires LLM access.")

    user_content = _build_critic_input(context)

    if not user_content.strip():
        logger.warning("CRITIC_EMPTY_INPUT — no context to critique")
        return CriticVerdict(
            confidence_score=0.0,
            overall_assessment="No context provided for critique.",
            rewrite_required=True,
        )

    instrument_type = context.get("instrument_type", "UNKNOWN")
    critic_prompt = _build_critic_prompt(instrument_type)
    logger.info(
        "CRITIC_STAGE_START",
        extra={"input_chars": len(user_content), "instrument_type": instrument_type},
    )

    data = call_openai_fn(critic_prompt, user_content, max_tokens=8000)
    verdict = _parse_critic_response(data)

    # ── Deterministic macro-consistency checks (no GPT) ──────────
    macro_flags = _run_macro_consistency_checks(context)
    verdict.macro_consistency_flags = macro_flags

    logger.info(
        "CRITIC_STAGE_COMPLETE",
        extra={
            "fatal_flaws": len(verdict.fatal_flaws),
            "material_gaps": len(verdict.material_gaps),
            "optimism_bias": len(verdict.optimism_bias),
            "macro_consistency_flags": len(verdict.macro_consistency_flags),
            "confidence_score": verdict.confidence_score,
            "rewrite_required": verdict.rewrite_required,
            "total_issues": verdict.total_issues,
        },
    )

    return verdict


def build_critic_packet(structured: dict) -> dict:
    """Build a compressed IC packet for critic consumption.
    
    Critic must NEVER receive raw documents or full narratives.
    Only structured summaries enter the critic prompt.
    """
    overview = structured.get("deal_overview", {})
    if isinstance(overview, str):
        overview = {"summary": overview[:2000]}
    
    terms = structured.get("terms_and_covenants", {})
    if isinstance(terms, str):
        terms = {"summary": terms[:2000]}
    
    risk_map = structured.get("risk_map", {})
    if isinstance(risk_map, str):
        risk_map = {"summary": risk_map[:2000]}
    
    memo = structured.get("investment_memo", "")
    if isinstance(memo, str) and len(memo) > 2000:
        memo = memo[:2000]
    
    return {
        "overview": overview,
        "terms": terms,
        "risk_map": risk_map,
        "executive_summary": memo,
    }
