"""Quant engine orchestrator — compute_quant_profile.

Sole orchestrator that fans out to all domain modules.

Error contract: raises-on-failure (pure computation — math errors should propagate).
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import structlog

from vertical_engines.credit.quant.models import QuantProfile
from vertical_engines.credit.quant.parser import (
    _ensure_v2,
    _parse_amount,
    _v2_num,
    _v2_str,
)
from vertical_engines.credit.quant.profile import (
    _build_sensitivity_matrix,
    _compute_risk_adjusted_return_v2,
    _extract_liquidity_hooks,
    compute_maturity_years,
    compute_rate_decomposition,
)
from vertical_engines.credit.quant.scenarios import build_deterministic_scenarios
from vertical_engines.credit.quant.sensitivity import (
    build_sensitivity_2d,
    build_sensitivity_3d_summary,
)

logger = structlog.get_logger()


def _tenor_bucket(years: float | None) -> str | None:
    """Classify maturity into a tenor bucket."""
    if years is None:
        return None
    if years < 1.0:
        return "<1y"
    if years < 3.0:
        return "1-3y"
    if years < 5.0:
        return "3-5y"
    return ">5y"


def compute_quant_profile(
    structured_analysis: dict[str, Any],
    *,
    deal_fields: dict[str, Any] | None = None,
    macro_snapshot: dict[str, Any] | None = None,
    concentration_profile: dict[str, Any] | None = None,
) -> QuantProfile:
    """Compute deterministic quant profile from structured_analysis_v2.

    If schemaVersion != "2.0", the input is migrated via the v1->v2 shim.

    Args:
        structured_analysis: v2 schema (schemaVersion="2.0") or legacy v1.
        deal_fields: Optional ORM deal fields.
        macro_snapshot: Optional macro snapshot (base_rate_short, etc.).
        concentration_profile: Optional concentration engine output.

    Returns:
        QuantProfile with all metrics populated deterministically.
    """
    # ── Ensure v2 schema ─────────────────────────────────────────
    analysis = _ensure_v2(structured_analysis)

    # ── Extract v2 blocks ────────────────────────────────────────
    terms = analysis.get("investmentTerms") or {}
    rate_structure = terms.get("rateStructure") or {}
    maturity_block = terms.get("maturity") or {}
    fees = analysis.get("fees") or []
    liquidity_terms = analysis.get("liquidityTerms") or {}
    credit_metrics = analysis.get("creditMetrics") or {}
    expected_returns = analysis.get("expectedReturns") or {}
    instrument = analysis.get("instrument") or {}
    risks = analysis.get("riskFactors", [])
    if not isinstance(risks, list):
        risks = []

    profile = QuantProfile()
    missing: list[str] = []
    proxy_flags: list[str] = []

    # Track schema version
    profile.schema_version_used = analysis.get("schemaVersion", "2.0")
    if analysis.get("_migrated_from_v1"):
        proxy_flags.append("MIGRATED_FROM_V1")

    # ── Parse as_of_date ─────────────────────────────────────────
    as_of_date: dt.date | None = None
    if deal_fields and deal_fields.get("as_of_date"):
        try:
            raw = deal_fields["as_of_date"]
            if isinstance(raw, dt.date):
                as_of_date = raw
            elif isinstance(raw, dt.datetime):
                as_of_date = raw.date()
            elif isinstance(raw, str):
                as_of_date = dt.date.fromisoformat(raw[:10])
        except (ValueError, TypeError):
            pass
    if as_of_date is None and macro_snapshot and macro_snapshot.get("date"):
        try:
            raw = macro_snapshot["date"]
            if isinstance(raw, dt.date):
                as_of_date = raw
            elif isinstance(raw, str):
                as_of_date = dt.date.fromisoformat(raw[:10])
        except (ValueError, TypeError):
            pass

    # ── D: Maturity (v2 maturity block) ──────────────────────────
    mat_years, mat_confidence = compute_maturity_years(maturity_block, as_of_date)
    profile.maturity_years = mat_years
    profile.maturity_years_confidence = mat_confidence
    profile.tenor_bucket = _tenor_bucket(mat_years)
    if mat_years is None:
        missing.append("maturity")

    # ── A: Rate Decomposition (v2 — rateStructure + fees) ────────
    rate_decomp = compute_rate_decomposition(
        rate_structure,
        fees if isinstance(fees, list) else [],
        maturity_years=mat_years,
        macro_snapshot=macro_snapshot,
    )
    profile.gross_coupon_pct = rate_decomp["gross_coupon_pct"]
    profile.base_rate_short_pct = rate_decomp["base_rate_short_pct"]
    profile.spread_bps = rate_decomp["spread_bps"]
    profile.floor_bps = rate_decomp["floor_bps"]
    profile.fee_stack_annualized_pct = rate_decomp["fee_stack_annualized_pct"]
    profile.net_return_proxy_pct = rate_decomp["net_return_proxy_pct"]
    profile.fee_notes = rate_decomp["fee_notes"]

    if profile.gross_coupon_pct is None:
        missing.append("couponRatePct")

    # ── Backward compat: coupon_rate_pct / all_in_yield_pct ──────
    profile.coupon_rate_pct = profile.gross_coupon_pct
    if profile.gross_coupon_pct is not None:
        oid = profile.origination_fee_pct or 0.0
        ef = profile.exit_fee_pct or 0.0
        ef_amort = ef / mat_years if mat_years and mat_years > 0 and ef > 0 else ef
        profile.all_in_yield_pct = round(profile.gross_coupon_pct + oid + ef_amort, 4)
    else:
        profile.all_in_yield_pct = None

    # ── Parse IRR / multiple / YTM from expectedReturns ──────────
    profile.target_irr_pct = _v2_num(expected_returns, "targetIRR")
    if profile.target_irr_pct is None:
        missing.append("targetIRR")

    profile.target_multiple = _v2_num(expected_returns, "targetMultiple")
    profile.yield_to_maturity_pct = _v2_num(expected_returns, "yieldToMaturity")

    # ── Parse sizing from instrument block ───────────────────────
    princ_block = instrument.get("principalAmount") or {}
    if isinstance(princ_block, dict):
        profile.principal_amount = _v2_num(princ_block, "value")
        profile.currency = _v2_str(princ_block, "currency")
    elif isinstance(princ_block, (int, float)):
        profile.principal_amount = float(princ_block)

    if profile.principal_amount is None:
        raw_pa = terms.get("principalAmount")
        if isinstance(raw_pa, (int, float)):
            profile.principal_amount = float(raw_pa)
        elif isinstance(raw_pa, str):
            profile.principal_amount = _parse_amount(raw_pa)
    if profile.principal_amount is None:
        missing.append("principalAmount")

    if profile.currency is None:
        raw_ccy = terms.get("currency") or instrument.get("currency")
        if raw_ccy and isinstance(raw_ccy, str) and len(raw_ccy) <= 4:
            profile.currency = raw_ccy.strip().upper()
        elif deal_fields and deal_fields.get("currency"):
            profile.currency = deal_fields["currency"]
        else:
            missing.append("currency")

    # ── Deprecated fee fields (backward compat) ──────────────────
    for fee in (fees if isinstance(fees, list) else []):
        if not isinstance(fee, dict):
            continue
        ft = (fee.get("feeType") or "").upper()
        val = _v2_num(fee, "valuePct")
        if ft == "ORIGINATION" and val is not None:
            profile.origination_fee_pct = val
        elif ft == "EXIT" and val is not None:
            profile.exit_fee_pct = val

    # ── G: Liquidity quant hooks ─────────────────────────────────
    liq_hooks = _extract_liquidity_hooks(liquidity_terms)
    profile.notice_period_days = liq_hooks["notice_period_days"]
    profile.gate_pct_per_period = liq_hooks["gate_pct_per_period"]
    profile.suspension_rights_flag = liq_hooks["suspension_rights_flag"]
    profile.lockup_months = liq_hooks["lockup_months"]
    profile.liquidity_flags = liq_hooks["liquidity_flags"]

    # ── H: Credit Coverage Ratios ────────────────────────────────
    _cm = credit_metrics or {}
    coverage_flags: list[str] = []

    profile.dscr = _v2_num(_cm, "dscr") or _v2_num(_cm, "debtServiceCoverageRatio")
    profile.interest_coverage_ratio = _v2_num(_cm, "interestCoverageRatio")
    profile.leverage_ratio = _v2_num(_cm, "leverageRatio")
    profile.ltv_pct = _v2_num(_cm, "ltv")
    profile.credit_metrics_confidence = _v2_str(_cm, "confidence")
    profile.credit_metrics_source = _v2_str(_cm, "source")

    if profile.dscr is not None and profile.dscr < 1.2:
        coverage_flags.append("DSCR_BELOW_1_2X")
    if profile.interest_coverage_ratio is not None and profile.interest_coverage_ratio < 2.0:
        coverage_flags.append("ICR_BELOW_2_0X")
    if profile.leverage_ratio is not None and profile.leverage_ratio > 6.0:
        coverage_flags.append("LEVERAGE_ABOVE_6X")
    if profile.ltv_pct is not None and profile.ltv_pct > 80:
        coverage_flags.append("LTV_ABOVE_80PCT")

    has_any_coverage = any([
        profile.dscr, profile.interest_coverage_ratio,
        profile.leverage_ratio, profile.ltv_pct,
    ])
    if not has_any_coverage:
        coverage_flags.append("NO_CREDIT_COVERAGE_DATA")
        missing.append("creditCoverageRatios")

    profile.credit_coverage_flags = coverage_flags

    # ── E: Risk-adjusted return (additive multi-risk) ────────────
    _base_for_risk = profile.target_irr_pct or profile.gross_coupon_pct
    profile.risk_adjusted_return_pct, profile.risk_adjusted_notes = (
        _compute_risk_adjusted_return_v2(_base_for_risk, risks)
    )

    # ── Legacy sensitivity matrix (deprecated) ───────────────────
    profile.sensitivity_matrix = _build_sensitivity_matrix(
        profile.target_irr_pct, profile.coupon_rate_pct,
    )

    # ── B: Scenario Engine (v2 — uses creditMetrics) ─────────────
    _scenario_base = profile.target_irr_pct or profile.gross_coupon_pct
    scenarios, scenario_proxy_flags = build_deterministic_scenarios(
        _scenario_base,
        risks,
        credit_metrics=credit_metrics,
        concentration_profile=concentration_profile,
        liquidity_hooks=liq_hooks,
    )
    profile.scenario_results = scenarios
    proxy_flags.extend(scenario_proxy_flags)

    # ── C: Sensitivity 2D & 3D ───────────────────────────────────
    profile.sensitivity_2d = build_sensitivity_2d(_scenario_base, proxy_flags)
    profile.sensitivity_3d_summary = build_sensitivity_3d_summary(
        _scenario_base, profile.sensitivity_2d,
    )

    # ── F: Status determination ──────────────────────────────────
    profile.missing_fields = missing
    profile.proxy_flags = proxy_flags

    critical_fields = {"couponRatePct", "targetIRR"}
    critical_missing = critical_fields & set(missing)

    if len(critical_missing) >= 2:
        profile.metrics_status = "INSUFFICIENT_DATA"
    elif proxy_flags:
        profile.metrics_status = "PROXY_MODE"
    elif missing:
        profile.metrics_status = "PARTIAL"
    else:
        profile.metrics_status = "COMPLETE"

    logger.info(
        "quant_profile_computed",
        schema_version=profile.schema_version_used,
        migrated=analysis.get("_migrated_from_v1", False),
        metrics_status=profile.metrics_status,
        missing_fields=missing,
        proxy_flags=proxy_flags,
        coupon=profile.gross_coupon_pct,
        irr=profile.target_irr_pct,
        scenario_count=len(scenarios),
        sensitivity_2d_cells=len(profile.sensitivity_2d),
        tenor_bucket=profile.tenor_bucket,
        liquidity_flags=profile.liquidity_flags,
    )

    return profile
