"""Constraint evaluator — pure functions for mandate fit checks.

No DB access. Evaluates instrument attributes against client profile constraints.
"""

from __future__ import annotations

from typing import Any

from vertical_engines.wealth.mandate_fit.models import ClientProfile, ConstraintResult

# Risk bucket ordering (higher = more aggressive)
_RISK_LEVELS = {
    "conservative": 1,
    "moderate": 2,
    "aggressive": 3,
}

# Instrument risk classification by asset class
_ASSET_CLASS_RISK = {
    "money_market": "conservative",
    "fixed_income": "conservative",
    "investment_grade_bonds": "conservative",
    "high_yield_bonds": "moderate",
    "balanced": "moderate",
    "equity_large_cap": "moderate",
    "equity_mid_cap": "aggressive",
    "equity_small_cap": "aggressive",
    "alternatives": "aggressive",
    "commodities": "aggressive",
    "real_estate": "moderate",
    "crypto": "aggressive",
}


def evaluate_risk_bucket(
    asset_class: str,
    attributes: dict[str, Any],
    profile: ClientProfile,
) -> ConstraintResult:
    """Check if instrument risk level is compatible with client risk bucket.

    Severity: HARD — risk bucket mismatch is a regulatory/suitability constraint.
    A conservative client must not be exposed to aggressive instruments.
    """
    instrument_risk = attributes.get(
        "risk_level",
        _ASSET_CLASS_RISK.get(asset_class, "aggressive"),
    )
    instrument_level = _RISK_LEVELS.get(instrument_risk, 3)
    client_level = _RISK_LEVELS.get(profile.risk_bucket, 1)

    if instrument_level <= client_level:
        return ConstraintResult(
            constraint="risk_bucket",
            passed=True,
            reason=f"Instrument risk '{instrument_risk}' within client tolerance '{profile.risk_bucket}'",
            severity="hard",
        )
    return ConstraintResult(
        constraint="risk_bucket",
        passed=False,
        reason=f"Instrument risk '{instrument_risk}' exceeds client tolerance '{profile.risk_bucket}'",
        severity="hard",
    )


def evaluate_esg(
    attributes: dict[str, Any],
    profile: ClientProfile,
) -> ConstraintResult:
    """Check ESG compliance if required by client profile.

    Severity: SOFT — ESG is a client preference, not a regulatory mandate.
    A non-ESG instrument should surface a warning for IC review, not disqualify.
    """
    if not profile.esg_required:
        return ConstraintResult(
            constraint="esg",
            passed=True,
            reason="ESG not required by client profile",
            severity="soft",
        )

    esg_compliant = attributes.get("esg_compliant", False)
    if esg_compliant:
        return ConstraintResult(
            constraint="esg",
            passed=True,
            reason="Instrument is ESG compliant",
            severity="soft",
        )
    return ConstraintResult(
        constraint="esg",
        passed=False,
        reason="Instrument is not ESG compliant — required by client profile",
        severity="soft",
    )


def evaluate_domicile(
    geography: str,
    profile: ClientProfile,
) -> ConstraintResult:
    """Check if instrument domicile is restricted by client profile.

    Severity: SOFT — domicile is a descriptive tag, not an eliminatory gate.
    PR-Q79 removed domicile as a screener gate; mandate fit follows the same
    convention. A domicile mismatch surfaces a warning for IC review.
    """
    if not profile.domicile_restrictions:
        return ConstraintResult(
            constraint="domicile",
            passed=True,
            reason="No domicile restrictions",
            severity="soft",
        )

    geo_upper = geography.strip().upper()
    restricted = {r.strip().upper() for r in profile.domicile_restrictions}

    if geo_upper in restricted:
        return ConstraintResult(
            constraint="domicile",
            passed=False,
            reason=f"Geography '{geography}' is restricted by client profile",
            severity="soft",
        )
    return ConstraintResult(
        constraint="domicile",
        passed=True,
        reason=f"Geography '{geography}' is not restricted",
        severity="soft",
    )


def evaluate_liquidity(
    attributes: dict[str, Any],
    profile: ClientProfile,
) -> ConstraintResult:
    """Check if instrument liquidity meets client requirements.

    Severity: HARD — liquidity mismatch is a structural constraint.
    A client with a 30-day redemption requirement cannot hold a 90-day lock-up
    instrument without operational risk.
    """
    if profile.max_redemption_days is None:
        return ConstraintResult(
            constraint="liquidity",
            passed=True,
            reason="No liquidity requirement",
            severity="hard",
        )

    redemption_days = attributes.get("redemption_days")
    if redemption_days is None:
        return ConstraintResult(
            constraint="liquidity",
            passed=True,
            reason="No redemption data — assumed liquid",
            severity="hard",
        )

    try:
        days = int(redemption_days)
    except (TypeError, ValueError):
        return ConstraintResult(
            constraint="liquidity",
            passed=True,
            reason=f"Invalid redemption data '{redemption_days}' — assumed liquid",
            severity="hard",
        )

    if days <= profile.max_redemption_days:
        return ConstraintResult(
            constraint="liquidity",
            passed=True,
            reason=f"Redemption {days}d within {profile.max_redemption_days}d limit",
            severity="hard",
        )
    return ConstraintResult(
        constraint="liquidity",
        passed=False,
        reason=f"Redemption {redemption_days}d exceeds {profile.max_redemption_days}d limit",
        severity="hard",
    )


def evaluate_currency(
    currency: str,
    profile: ClientProfile,
) -> ConstraintResult:
    """Check if instrument currency is allowed by client profile.

    Severity: SOFT — currency tilt is a preference, not a structural gate.
    An FX-mismatched instrument may still be suitable if hedged or if the
    allocation is small. Surfaces a warning for IC review.
    """
    if not profile.currency_restrictions:
        return ConstraintResult(
            constraint="currency",
            passed=True,
            reason="No currency restrictions",
            severity="soft",
        )

    allowed = {c.strip().upper() for c in profile.currency_restrictions}
    if currency.strip().upper() in allowed:
        return ConstraintResult(
            constraint="currency",
            passed=True,
            reason=f"Currency '{currency}' is allowed",
            severity="soft",
        )
    return ConstraintResult(
        constraint="currency",
        passed=False,
        reason=f"Currency '{currency}' not in allowed currencies: {', '.join(sorted(allowed))}",
        severity="soft",
    )


def compute_suitability_score(constraint_results: list[ConstraintResult]) -> float:
    """Compute weighted suitability score from constraint results.

    Hard constraints carry 2x weight; soft constraints carry 1x.
    This ensures that a full hard-PASS always scores higher than a full
    soft-PASS-only result, satisfying institutional convention §3.2.

    Returns 1.0 if all constraints pass, 0.0 if all fail.
    """
    if not constraint_results:
        return 0.0
    total_weight = 0.0
    earned_weight = 0.0
    for r in constraint_results:
        w = 2.0 if r.severity == "hard" else 1.0
        total_weight += w
        if r.passed:
            earned_weight += w
    return earned_weight / total_weight if total_weight > 0.0 else 0.0
