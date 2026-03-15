"""Maturity, rate decomposition, liquidity hooks, and risk-adjusted return.

Merges: compute_maturity_years, compute_rate_decomposition,
_extract_liquidity_hooks, _compute_risk_adjusted_return_v2,
and related helpers.

Imports only models.py and parser.py.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

import structlog

from vertical_engines.credit.quant.models import (
    MAX_TOTAL_HAIRCUT_PP,
    NUM_RE,
    SEVERITY_HAIRCUT_PP,
)
from vertical_engines.credit.quant.parser import (
    _v2_int,
    _v2_num,
    _v2_str,
)

logger = structlog.get_logger()


# ── D: Maturity Parsing (v2 — from investmentTerms.maturity block) ────


def compute_maturity_years(
    maturity: dict[str, Any] | None,
    as_of_date: dt.date | None = None,
) -> tuple[float | None, str]:
    """Parse maturity from v2 ``investmentTerms.maturity`` block.

    Priority:
        1. maturityDateISO  →  delta from as_of_date  → confidence = EXACT
        2. tenorMonths      →  months / 12             → confidence = PARSED
        3. None             →  DATA_GAP

    Returns (years, confidence).
    """
    if not maturity or not isinstance(maturity, dict):
        return None, "MISSING"

    iso = _v2_str(maturity, "maturityDateISO")
    if iso:
        iso_match = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", iso)
        if iso_match:
            try:
                mat_date = dt.date(
                    int(iso_match.group(1)),
                    int(iso_match.group(2)),
                    int(iso_match.group(3)),
                )
                ref = as_of_date or dt.date.today()
                delta_days = (mat_date - ref).days
                return round(delta_days / 365.25, 2), "EXACT"
            except (ValueError, OverflowError):
                pass

    tenor = _v2_num(maturity, "tenorMonths")
    if tenor is not None and tenor > 0:
        return round(tenor / 12.0, 2), "PARSED"

    return None, "MISSING"


# ── A: Rate Decomposition (v2 — from rateStructure + fees) ────────────


def compute_rate_decomposition(
    rate_structure: dict[str, Any] | None,
    fees: list[dict[str, Any]] | None,
    maturity_years: float | None = None,
    macro_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Decompose rate structure and fees into gross/net components.

    Returns dict with:
        gross_coupon_pct, spread_bps, base_rate_short_pct, floor_bps,
        net_return_proxy_pct, fee_stack_annualized_pct, fee_notes
    """
    result: dict[str, Any] = {
        "gross_coupon_pct": None,
        "spread_bps": None,
        "base_rate_short_pct": None,
        "floor_bps": None,
        "net_return_proxy_pct": None,
        "fee_stack_annualized_pct": None,
        "fee_notes": [],
    }

    rs = rate_structure or {}

    coupon = _v2_num(rs, "couponRatePct")
    result["gross_coupon_pct"] = coupon

    spread = _v2_num(rs, "spreadBps")
    if spread is not None:
        result["spread_bps"] = int(spread)

    floor = _v2_num(rs, "floorBps")
    if floor is not None:
        result["floor_bps"] = int(floor)

    base_rate: float | None = None
    if macro_snapshot:
        base_rate = macro_snapshot.get("base_rate_short")
    result["base_rate_short_pct"] = base_rate

    if result["spread_bps"] is None and coupon is not None and base_rate is not None:
        computed_spread = coupon - base_rate
        if computed_spread > 0:
            result["spread_bps"] = int(computed_spread * 100)
            result["fee_notes"].append(
                f"Spread computed: coupon {coupon}% - base {base_rate}% = {int(computed_spread * 100)}bps",
            )

    fee_stack, fee_notes = _compute_fee_stack_v2(fees, maturity_years)
    result["fee_stack_annualized_pct"] = fee_stack
    result["fee_notes"].extend(fee_notes)

    if coupon is not None:
        if fee_stack is not None:
            result["net_return_proxy_pct"] = round(coupon - fee_stack, 4)
        else:
            result["net_return_proxy_pct"] = coupon
            result["fee_notes"].append("Net return = gross (no fees to deduct)")

    return result


def _compute_fee_stack_v2(
    fees: list[dict[str, Any]] | None,
    maturity_years: float | None,
) -> tuple[float | None, list[str]]:
    """Compute annualized fee stack from v2 ``fees`` array."""
    if not fees or not isinstance(fees, list):
        return None, ["No fees found in structured analysis"]

    notes: list[str] = []
    annual_total = 0.0
    found_any = False

    for fee in fees:
        if not isinstance(fee, dict):
            continue
        fee_type = fee.get("feeType", "UNKNOWN")
        val = _v2_num(fee, "valuePct")
        if val is None:
            continue
        found_any = True
        freq = (fee.get("frequency") or "ANNUAL").upper()

        if freq == "ONE_TIME":
            tenor = maturity_years if maturity_years and maturity_years > 0 else 3.0
            amortised = round(val / tenor, 4)
            suffix = "" if maturity_years and maturity_years > 0 else " (tenor unknown, using 3y)"
            notes.append(f"{fee_type}: {val}% one-time amortised over {tenor:.1f}y → {amortised}%/yr{suffix}")
            annual_total += amortised
        elif freq == "QUARTERLY":
            annual = val * 4
            notes.append(f"{fee_type}: {val}%/qtr → {annual}%/yr")
            annual_total += annual
        elif freq == "SEMI_ANNUAL":
            annual = val * 2
            notes.append(f"{fee_type}: {val}%/semi → {annual}%/yr")
            annual_total += annual
        else:  # ANNUAL or other
            notes.append(f"{fee_type}: {val}%/yr")
            annual_total += val

    if not found_any:
        return None, ["No parseable fees in fee schedule"]

    return round(annual_total, 4), notes


# ── G: Liquidity Quant Hooks ─────────────────────────────────────────


def _extract_liquidity_hooks(
    liquidity_terms: dict[str, Any] | None,
) -> dict[str, Any]:
    """Extract structured liquidity fields from v2 liquidityTerms."""
    out: dict[str, Any] = {
        "notice_period_days": None,
        "gate_pct_per_period": None,
        "suspension_rights_flag": None,
        "lockup_months": None,
        "liquidity_flags": [],
    }
    if not liquidity_terms or not isinstance(liquidity_terms, dict):
        out["liquidity_flags"].append("DATA_GAP:liquidityTerms")
        return out

    out["notice_period_days"] = _v2_int(liquidity_terms, "noticePeriodDays")
    out["gate_pct_per_period"] = _v2_num(liquidity_terms, "gatePctPerPeriod")
    out["lockup_months"] = _v2_num(liquidity_terms, "lockupMonths")

    susp = liquidity_terms.get("suspensionRights")
    if isinstance(susp, dict):
        out["suspension_rights_flag"] = susp.get("canSuspend")
    elif isinstance(susp, bool):
        out["suspension_rights_flag"] = susp

    flags: list[str] = []
    if out["lockup_months"] and out["lockup_months"] >= 24:
        flags.append("LONG_LOCKUP")
    if out["gate_pct_per_period"] is not None and out["gate_pct_per_period"] < 25:
        flags.append("RESTRICTIVE_GATE")
    if out["suspension_rights_flag"] is True:
        flags.append("SUSPENSION_RIGHTS")
    if out["notice_period_days"] and out["notice_period_days"] > 90:
        flags.append("LONG_NOTICE_PERIOD")
    if not any(v is not None for k, v in out.items() if k != "liquidity_flags"):
        flags.append("DATA_GAP:liquidityTerms")

    out["liquidity_flags"] = flags
    return out


# ── E: Risk-Adjusted Return v2 ───────────────────────────────────────


def _compute_risk_adjusted_return_v2(
    base_return: float | None,
    risks: list[dict[str, Any]],
) -> tuple[float | None, list[str]]:
    """Compute risk-adjusted return using additive multi-risk haircut.

    Sums per-severity haircuts across ALL risk factors.
    Total haircut capped at 8pp.
    """
    if base_return is None:
        return None, ["No base return available for risk adjustment"]

    if not risks:
        return base_return, ["No risk factors — no haircut applied"]

    notes: list[str] = []
    total_haircut = 0.0
    risk_count = 0

    for r in risks:
        if not isinstance(r, dict):
            continue
        sev = (r.get("severity") or "LOW").upper()
        haircut = SEVERITY_HAIRCUT_PP.get(sev, 0.5)
        total_haircut += haircut
        risk_count += 1

    total_haircut = min(total_haircut, MAX_TOTAL_HAIRCUT_PP)
    adjusted = max(round(base_return - total_haircut, 4), 0.0)
    notes.append(
        f"{risk_count} risk factors → total haircut {total_haircut:.1f}pp "
        f"(cap {MAX_TOTAL_HAIRCUT_PP}pp) | {base_return:.2f}% → {adjusted:.2f}%",
    )
    return adjusted, notes


# ── Legacy maturity parser ────────────────────────────────────────────


def _parse_years(value: str | None, as_of_date: dt.date | None = None) -> tuple[float | None, str]:
    """Parse maturity from a legacy string value.

    .. deprecated:: v3
        Use ``compute_maturity_years`` with v2 maturity block.
    """
    if not value or not isinstance(value, str):
        return None, "MISSING"
    value_stripped = value.strip()

    iso_match = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", value_stripped)
    if iso_match:
        try:
            mat_date = dt.date(
                int(iso_match.group(1)),
                int(iso_match.group(2)),
                int(iso_match.group(3)),
            )
            ref = as_of_date or dt.date.today()
            delta_days = (mat_date - ref).days
            return round(delta_days / 365.25, 2), "EXACT"
        except (ValueError, OverflowError):
            pass

    lower = value_stripped.lower()
    if "year" in lower:
        m = NUM_RE.search(lower)
        if m:
            return float(m.group()), "PARSED"
    if "month" in lower:
        m = NUM_RE.search(lower)
        if m:
            return round(float(m.group()) / 12.0, 2), "PARSED"
    return None, "MISSING"


# ── Legacy 1D sensitivity (deprecated, kept for backward compat) ──────


def _build_sensitivity_matrix(
    base_irr: float | None,
    base_coupon: float | None,
) -> list[dict[str, Any]]:
    """Build ±200bps 1D sensitivity.

    .. deprecated:: v3
        Use sensitivity_2d + sensitivity_3d_summary.
    """
    base = base_irr if base_irr is not None else base_coupon
    if base is None:
        return []
    scenarios = []
    for label, delta_bps in [
        ("Stress -200bps", -2.0),
        ("Stress -100bps", -1.0),
        ("Base Case", 0.0),
        ("Upside +100bps", 1.0),
        ("Upside +200bps", 2.0),
    ]:
        scenarios.append({
            "scenario": label,
            "delta_bps": int(delta_bps * 100),
            "adjusted_irr_pct": round(base + delta_bps, 4),
        })
    return scenarios
