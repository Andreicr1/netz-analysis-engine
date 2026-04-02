"""Critic engine data models and constants.

Leaf module — zero sibling imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
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


INSTRUMENT_TYPE_PROFILES: dict[str, dict[str, Any]] = {
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
