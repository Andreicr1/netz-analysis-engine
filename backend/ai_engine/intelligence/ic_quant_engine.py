"""IC Quant Engine — deterministic quantitative profile for deal analysis.

Consumes **structured_analysis_v2** exclusively.  Legacy v1 payloads are
migrated transparently via ``_migrate_v1_to_v2`` before any computation.

All calculations are pure arithmetic on extracted fields — no LLM calls,
no synthetic defaults, no tone dependency.

Architecture (v3 — structured_analysis_v2):
    A. Rate Decomposition    (rateStructure → gross_coupon, spread, floor,
                              base_rate, net_return_proxy, fee_stack)
    B. Scenario Engine       (Base / Downside / Severe — deterministic)
    C. Sensitivity 2D + 3D   (default_rate × recovery_rate grid + rate shocks)
    D. Maturity / Tenor      (ISO date → EXACT, tenorMonths → PARSED, bucket)
    E. Risk-Adjusted Return  (additive multi-risk haircut, capped at -8pp)
    F. Status / Proxy flags  (COMPLETE | PARTIAL | INSUFFICIENT_DATA | PROXY_MODE)
    G. Liquidity Quant Hooks (notice_period_days, gate_pct, lockup_months,
                              suspension_rights — for stress modelling)

Inputs consumed (all deterministic / pre-LLM):
    structured_analysis   — v2 schema (schemaVersion="2.0")
    deal_fields           — optional ORM deal fields
    macro_snapshot        — optional macro data (base_rate_short, etc.)
    concentration_profile — optional concentration engine output

PROXY POLICY:
    When data is unavailable, the engine may use explicitly labelled proxies
    (e.g. "PROXY_FROM_SEVERITY").  Proxies NEVER inflate confidence; they
    exist to produce stress outputs.  Every proxy sets ``proxy_flags``
    and ``metrics_status = "PROXY_MODE"``.

TONE NORMALIZER RULE:
    This engine runs BEFORE the Tone Normalizer.  Quant outputs depend ONLY
    on structured_analysis, macro_snapshot, deal_fields, and
    concentration_profile.  Narrative text cannot influence any number here.
"""
from __future__ import annotations

import copy
import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
#  Data types
# ══════════════════════════════════════════════════════════════════════


@dataclass
class QuantProfile:
    """Deterministic quantitative profile for an investment opportunity."""

    # ── Schema tracking ──────────────────────────────────────────
    schema_version_used: str = "2.0"

    # Core yield metrics
    coupon_rate_pct: float | None = None
    all_in_yield_pct: float | None = None
    spread_bps: int | None = None

    # Fee metrics (deprecated — kept for backward compat)
    origination_fee_pct: float | None = None
    exit_fee_pct: float | None = None

    # ── A: Rate Decomposition ────────────────────────────────────
    gross_coupon_pct: float | None = None
    base_rate_short_pct: float | None = None
    floor_bps: int | None = None
    fee_stack_annualized_pct: float | None = None
    net_return_proxy_pct: float | None = None
    fee_notes: list[str] = field(default_factory=list)

    # Return metrics
    target_irr_pct: float | None = None
    target_multiple: float | None = None
    yield_to_maturity_pct: float | None = None

    # Sizing
    principal_amount: float | None = None
    currency: str | None = None

    # ── D: Duration / maturity ───────────────────────────────────
    maturity_years: float | None = None
    maturity_years_confidence: str | None = None  # EXACT | PARSED | MISSING
    tenor_bucket: str | None = None               # <1y | 1-3y | 3-5y | >5y

    # ── G: Liquidity quant hooks ─────────────────────────────────
    notice_period_days: int | None = None
    gate_pct_per_period: float | None = None
    suspension_rights_flag: bool | None = None
    lockup_months: float | None = None
    liquidity_flags: list[str] = field(default_factory=list)

    # ── H: Credit Coverage Ratios ────────────────────────────────
    dscr: float | None = None
    interest_coverage_ratio: float | None = None
    leverage_ratio: float | None = None
    ltv_pct: float | None = None
    credit_metrics_confidence: str | None = None
    credit_metrics_source: str | None = None
    credit_coverage_flags: list[str] = field(default_factory=list)

    # ── E: Risk-adjusted ─────────────────────────────────────────
    risk_adjusted_return_pct: float | None = None
    risk_adjusted_notes: list[str] = field(default_factory=list)

    # ── Legacy sensitivity (deprecated — kept for backward compat) ─
    sensitivity_matrix: list[dict[str, Any]] = field(default_factory=list)

    # ── C: Sensitivity 2D / 3D ───────────────────────────────────
    sensitivity_2d: list[dict[str, Any]] = field(default_factory=list)
    sensitivity_3d_summary: dict[str, Any] = field(default_factory=dict)

    # ── B: Scenario results ──────────────────────────────────────
    scenario_results: list[dict[str, Any]] = field(default_factory=list)

    # ── F: Status / Proxy flags ──────────────────────────────────
    metrics_status: str = "COMPLETE"
    missing_fields: list[str] = field(default_factory=list)
    proxy_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            # Schema
            "schema_version_used": self.schema_version_used,
            # Core yield
            "coupon_rate_pct": self.coupon_rate_pct,
            "all_in_yield_pct": self.all_in_yield_pct,
            "spread_bps": self.spread_bps,
            # Deprecated fee fields (backward compat)
            "origination_fee_pct": self.origination_fee_pct,
            "exit_fee_pct": self.exit_fee_pct,
            # Rate decomposition
            "gross_coupon_pct": self.gross_coupon_pct,
            "base_rate_short_pct": self.base_rate_short_pct,
            "floor_bps": self.floor_bps,
            "fee_stack_annualized_pct": self.fee_stack_annualized_pct,
            "net_return_proxy_pct": self.net_return_proxy_pct,
            "fee_notes": self.fee_notes,
            # Returns
            "target_irr_pct": self.target_irr_pct,
            "target_multiple": self.target_multiple,
            "yield_to_maturity_pct": self.yield_to_maturity_pct,
            # Sizing
            "principal_amount": self.principal_amount,
            "currency": self.currency,
            # Maturity / tenor
            "maturity_years": self.maturity_years,
            "maturity_years_confidence": self.maturity_years_confidence,
            "tenor_bucket": self.tenor_bucket,
            # Liquidity quant hooks
            "notice_period_days": self.notice_period_days,
            "gate_pct_per_period": self.gate_pct_per_period,
            "suspension_rights_flag": self.suspension_rights_flag,
            "lockup_months": self.lockup_months,
            "liquidity_flags": self.liquidity_flags,
            # Credit coverage
            "dscr": self.dscr,
            "interest_coverage_ratio": self.interest_coverage_ratio,
            "leverage_ratio": self.leverage_ratio,
            "ltv_pct": self.ltv_pct,
            "credit_metrics_confidence": self.credit_metrics_confidence,
            "credit_metrics_source": self.credit_metrics_source,
            "credit_coverage_flags": self.credit_coverage_flags,
            # Risk
            "risk_adjusted_return_pct": self.risk_adjusted_return_pct,
            "risk_adjusted_notes": self.risk_adjusted_notes,
            # Sensitivity
            "sensitivity_matrix": self.sensitivity_matrix,
            "sensitivity_2d": self.sensitivity_2d,
            "sensitivity_3d_summary": self.sensitivity_3d_summary,
            # Scenarios
            "scenario_results": self.scenario_results,
            # Status
            "metrics_status": self.metrics_status,
            "missing_fields": self.missing_fields,
            "proxy_flags": self.proxy_flags,
        }


# ══════════════════════════════════════════════════════════════════════
#  V1 → V2 Migration Shim
# ══════════════════════════════════════════════════════════════════════

def _migrate_v1_to_v2(analysis: dict[str, Any]) -> dict[str, Any]:
    """Translate a legacy v1 structured_analysis into v2 shape.

    The shim maps:
      - investmentTerms.interestRate (string) → rateStructure.couponRatePct
      - investmentTerms.maturityDate (string) → investmentTerms.maturity block
      - expectedReturns.couponRate (string)   → rateStructure.couponRatePct
      - investmentTerms.lockupPeriod/redemptionFrequency →
            liquidityTerms.lockupMonths / redemptionFrequency
      - fees aggregated from old locations → fees block

    Logs ``legacy_schema_detected: true`` on every invocation.
    """
    logger.warning(
        "LEGACY_SCHEMA_MIGRATION",
        extra={"legacy_schema_detected": True, "schemaVersion": analysis.get("schemaVersion")},
    )
    out = copy.deepcopy(analysis)
    out["schemaVersion"] = "2.0"
    out["_migrated_from_v1"] = True

    old_terms = out.get("investmentTerms") or {}
    old_returns = out.get("expectedReturns") or {}

    # ── rateStructure ────────────────────────────────────────────
    if "rateStructure" not in old_terms:
        rs: dict[str, Any] = {}
        # Determine coupon from best available source
        coupon_raw = old_returns.get("couponRate") or old_terms.get("interestRate")
        coupon_parsed = _parse_pct(coupon_raw) if coupon_raw else None
        if coupon_parsed is not None:
            rs["couponRatePct"] = coupon_parsed
            rs["_source"] = "migrated_from_v1"
            rs["_confidence"] = "LOW"
        # Infer rateType from text clues
        rate_text = str(coupon_raw or "").lower()
        if any(kw in rate_text for kw in ("libor", "sofr", "euribor", "float")):
            rs["rateType"] = "FLOATING"
        elif coupon_parsed is not None:
            rs["rateType"] = "FIXED"
        if rs:
            old_terms["rateStructure"] = rs

    # ── maturity block ───────────────────────────────────────────
    if "maturity" not in old_terms:
        mat_block: dict[str, Any] = {}
        raw_mat = old_terms.get("maturityDate")
        if raw_mat and isinstance(raw_mat, str):
            stripped = raw_mat.strip()
            # Check if it looks like an ISO date
            if re.match(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", stripped):
                mat_block["maturityDateISO"] = stripped
            else:
                # Try to parse months from text
                lower = stripped.lower()
                m = _NUM_RE.search(lower)
                if m:
                    val = float(m.group())
                    if "month" in lower:
                        mat_block["tenorMonths"] = val
                    elif "year" in lower:
                        mat_block["tenorMonths"] = val * 12
        if mat_block:
            mat_block["_confidence"] = "LOW"
            mat_block["_source"] = "migrated_from_v1"
            old_terms["maturity"] = mat_block

    # ── fees block ───────────────────────────────────────────────
    if "fees" not in out:
        fees: list[dict[str, Any]] = []
        fee_map = {
            "managementFee": "MANAGEMENT", "performanceFee": "PERFORMANCE",
            "servicingFee": "SERVICING", "adminFee": "ADMIN",
            "originationFee": "ORIGINATION", "exitFee": "EXIT",
        }
        for key, ftype in fee_map.items():
            raw = old_terms.get(key) or old_returns.get(key)
            parsed = _parse_pct(raw) if raw else None
            if parsed is not None:
                entry: dict[str, Any] = {
                    "feeType": ftype,
                    "valuePct": parsed,
                    "frequency": "ONE_TIME" if ftype in ("ORIGINATION", "EXIT") else "ANNUAL",
                    "_confidence": "LOW",
                    "_source": "migrated_from_v1",
                }
                fees.append(entry)
        if fees:
            out["fees"] = fees

    # ── liquidityTerms ───────────────────────────────────────────
    if "liquidityTerms" not in out:
        liq: dict[str, Any] = {}
        fund_liq = out.get("fundLiquidityTerms") or {}
        # lockup
        raw_lockup = (fund_liq.get("investorLockupYears")
                      or old_terms.get("lockupPeriod"))
        if raw_lockup and isinstance(raw_lockup, str):
            lower = raw_lockup.lower()
            m = _NUM_RE.search(lower)
            if m:
                val = float(m.group())
                if "year" in lower:
                    liq["lockupMonths"] = val * 12
                elif "month" in lower:
                    liq["lockupMonths"] = val
                elif "day" in lower:
                    liq["noticePeriodDays"] = int(val)
        # redemptionFrequency
        raw_freq = fund_liq.get("redemptionFrequency")
        if raw_freq and isinstance(raw_freq, str):
            upper = raw_freq.strip().upper()
            for freq in ("QUARTERLY", "MONTHLY", "SEMI_ANNUAL", "ANNUAL", "DAILY"):
                if freq in upper.replace("-", "_").replace(" ", "_"):
                    liq["redemptionFrequency"] = freq
                    break
        if liq:
            liq["_confidence"] = "LOW"
            liq["_source"] = "migrated_from_v1"
            out["liquidityTerms"] = liq

    # ── creditMetrics (empty stub) ───────────────────────────────
    if "creditMetrics" not in out:
        out["creditMetrics"] = {}

    # ── governance (empty stub) ──────────────────────────────────
    if "governance" not in out:
        out["governance"] = {}

    # ── instrument block ─────────────────────────────────────────
    if "instrument" not in out:
        inst: dict[str, Any] = {}
        itype = out.get("instrumentType") or old_terms.get("instrumentType")
        if itype:
            inst["type"] = itype
        princ_raw = old_terms.get("principalAmount")
        if princ_raw:
            parsed_amt = _parse_amount(princ_raw) if isinstance(princ_raw, str) else princ_raw
            if parsed_amt is not None:
                inst["principalAmount"] = {"value": parsed_amt}
                cur = _extract_currency(princ_raw) if isinstance(princ_raw, str) else None
                if cur:
                    inst["principalAmount"]["currency"] = cur
        ccy = old_terms.get("currency")
        if ccy and isinstance(ccy, str) and len(ccy) <= 4:
            inst.setdefault("principalAmount", {})["currency"] = ccy.strip().upper()
        if inst:
            out["instrument"] = inst

    # ── expectedReturns passthrough ──────────────────────────────
    # v2 expects numeric fields; attempt migration
    if old_returns:
        er: dict[str, Any] = {}
        for key in ("targetIRR", "targetMultiple", "yieldToMaturity"):
            raw = old_returns.get(key)
            if raw is not None:
                parsed = _parse_pct(raw) if isinstance(raw, str) else raw
                if parsed is not None:
                    er[key.replace("IRR", "Irr").replace("YTM", "Ytm") if False else key] = parsed
        if er:
            out["expectedReturns"] = {**old_returns, **er}

    out["investmentTerms"] = old_terms
    return out


def _ensure_v2(analysis: dict[str, Any]) -> dict[str, Any]:
    """Return a v2-schema analysis, migrating if necessary."""
    version = analysis.get("schemaVersion")
    if version == "2.0":
        return analysis
    return _migrate_v1_to_v2(analysis)


# ══════════════════════════════════════════════════════════════════════
#  v2 field accessors (typed, null-safe)
# ══════════════════════════════════════════════════════════════════════

def _v2_num(block: dict[str, Any] | None, key: str) -> float | None:
    """Extract a numeric field from a v2 block.  Accepts float/int/str."""
    if not block:
        return None
    val = block.get(key)
    if val is None:
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    if isinstance(val, str):
        return _parse_pct(val)
    return None


def _v2_int(block: dict[str, Any] | None, key: str) -> int | None:
    """Extract an integer field from a v2 block."""
    if not block:
        return None
    val = block.get(key)
    if val is None:
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return int(val)
    if isinstance(val, str):
        m = _NUM_RE.search(val)
        return int(float(m.group())) if m else None
    return None


def _v2_str(block: dict[str, Any] | None, key: str) -> str | None:
    """Extract a string field from a v2 block."""
    if not block:
        return None
    val = block.get(key)
    if val is None or not isinstance(val, str) or not val.strip():
        return None
    return val.strip()


def _v2_bool(block: dict[str, Any] | None, key: str) -> bool | None:
    """Extract a boolean field from a v2 block."""
    if not block:
        return None
    val = block.get(key)
    if isinstance(val, bool):
        return val
    return None


# ══════════════════════════════════════════════════════════════════════
#  Numeric parsing helpers (kept for migration shim + edge cases)
# ══════════════════════════════════════════════════════════════════════

_NUM_RE = re.compile(r"[\d]+(?:\.[\d]+)?")


def _parse_pct(value: str | None) -> float | None:
    """Parse a percentage string like '8.5%' or 'LIBOR + 450bps' into float."""
    if not value or not isinstance(value, str):
        return None
    value = value.strip().replace(",", "")
    if "%" in value:
        m = _NUM_RE.search(value.replace("%", ""))
        return float(m.group()) if m else None
    if "bps" in value.lower():
        m = _NUM_RE.search(value)
        return float(m.group()) / 100.0 if m else None
    m = _NUM_RE.search(value)
    if m:
        v = float(m.group())
        if v > 30:
            return v / 100.0
        return v
    return None


def _parse_amount(value: str | None) -> float | None:
    """Parse a currency amount like '$50,000,000' or '50M' into float."""
    if not value or not isinstance(value, str):
        return None
    value = value.strip().replace(",", "").replace("$", "").replace("€", "").replace("£", "")
    multiplier = 1.0
    if value.upper().endswith("M"):
        multiplier = 1_000_000
        value = value[:-1]
    elif value.upper().endswith("B"):
        multiplier = 1_000_000_000
        value = value[:-1]
    elif value.upper().endswith("K"):
        multiplier = 1_000
        value = value[:-1]
    m = _NUM_RE.search(value)
    return float(m.group()) * multiplier if m else None


def _parse_multiple(value: str | None) -> float | None:
    """Parse a multiple like '1.5x' or '2.0' into float."""
    if not value or not isinstance(value, str):
        return None
    value = value.strip().lower().replace("x", "")
    m = _NUM_RE.search(value)
    return float(m.group()) if m else None


def _extract_currency(value: str | None) -> str | None:
    """Extract currency code from strings like 'USD', '$50M', 'EUR 10M'."""
    if not value or not isinstance(value, str):
        return None
    value = value.strip().upper()
    for code in ("USD", "EUR", "GBP", "CHF", "CAD", "AUD"):
        if code in value:
            return code
    if "$" in value:
        return "USD"
    if "€" in value:
        return "EUR"
    if "£" in value:
        return "GBP"
    return None


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


# ══════════════════════════════════════════════════════════════════════
#  D: Maturity Parsing (v2 — from investmentTerms.maturity block)
# ══════════════════════════════════════════════════════════════════════

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

    # 1. ISO date
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

    # 2. tenorMonths
    tenor = _v2_num(maturity, "tenorMonths")
    if tenor is not None and tenor > 0:
        return round(tenor / 12.0, 2), "PARSED"

    return None, "MISSING"


# Legacy compat — still used by some tests
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
        m = _NUM_RE.search(lower)
        if m:
            return float(m.group()), "PARSED"
    if "month" in lower:
        m = _NUM_RE.search(lower)
        if m:
            return round(float(m.group()) / 12.0, 2), "PARSED"
    return None, "MISSING"


# ══════════════════════════════════════════════════════════════════════
#  A: Rate Decomposition (v2 — from rateStructure + fees)
# ══════════════════════════════════════════════════════════════════════

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

    # ── Gross coupon ─────────────────────────────────────────────
    coupon = _v2_num(rs, "couponRatePct")
    result["gross_coupon_pct"] = coupon

    # ── Spread ───────────────────────────────────────────────────
    spread = _v2_num(rs, "spreadBps")
    if spread is not None:
        result["spread_bps"] = int(spread)

    # ── Floor ────────────────────────────────────────────────────
    floor = _v2_num(rs, "floorBps")
    if floor is not None:
        result["floor_bps"] = int(floor)

    # ── Base rate from macro ─────────────────────────────────────
    base_rate: float | None = None
    if macro_snapshot:
        base_rate = macro_snapshot.get("base_rate_short")
    result["base_rate_short_pct"] = base_rate

    # If no explicit spread but we have coupon + base rate, compute spread
    if result["spread_bps"] is None and coupon is not None and base_rate is not None:
        computed_spread = coupon - base_rate
        if computed_spread > 0:
            result["spread_bps"] = int(computed_spread * 100)
            result["fee_notes"].append(
                f"Spread computed: coupon {coupon}% - base {base_rate}% = {int(computed_spread * 100)}bps",
            )

    # ── Fee stack ────────────────────────────────────────────────
    fee_stack, fee_notes = _compute_fee_stack_v2(fees, maturity_years)
    result["fee_stack_annualized_pct"] = fee_stack
    result["fee_notes"].extend(fee_notes)

    # ── Net return proxy ─────────────────────────────────────────
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
    """Compute annualized fee stack from v2 ``fees`` array.

    Each fee entry: { feeType, valuePct, frequency }
    frequency: ANNUAL | ONE_TIME | QUARTERLY | SEMI_ANNUAL
    """
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


# Legacy fee stack (for migration shim paths)
_FEE_MAP: dict[str, str] = {
    "managementFee": "Mgmt Fee", "performanceFee": "Perf Fee",
    "servicingFee": "Servicing Fee", "adminFee": "Admin Fee",
    "originationFee": "Origination Fee", "exitFee": "Exit Fee",
}


# ══════════════════════════════════════════════════════════════════════
#  G: Liquidity Quant Hooks
# ══════════════════════════════════════════════════════════════════════

def _extract_liquidity_hooks(
    liquidity_terms: dict[str, Any] | None,
) -> dict[str, Any]:
    """Extract structured liquidity fields from v2 liquidityTerms.

    Returns dict with:
        notice_period_days, gate_pct_per_period, suspension_rights_flag,
        lockup_months, liquidity_flags
    """
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

    # Suspension rights
    susp = liquidity_terms.get("suspensionRights")
    if isinstance(susp, dict):
        out["suspension_rights_flag"] = susp.get("canSuspend")
    elif isinstance(susp, bool):
        out["suspension_rights_flag"] = susp

    # Flags
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


# ══════════════════════════════════════════════════════════════════════
#  E: Risk-Adjusted Return v2 — additive multi-risk haircut
# ══════════════════════════════════════════════════════════════════════

_SEVERITY_HAIRCUT_PP: dict[str, float] = {
    "HIGH":   2.5,
    "MEDIUM": 1.2,
    "LOW":    0.5,
}
_MAX_TOTAL_HAIRCUT_PP = 8.0


def _compute_risk_adjusted_return_v2(
    base_return: float | None,
    risks: list[dict],
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
        haircut = _SEVERITY_HAIRCUT_PP.get(sev, 0.5)
        total_haircut += haircut
        risk_count += 1

    total_haircut = min(total_haircut, _MAX_TOTAL_HAIRCUT_PP)
    adjusted = max(round(base_return - total_haircut, 4), 0.0)
    notes.append(
        f"{risk_count} risk factors → total haircut {total_haircut:.1f}pp "
        f"(cap {_MAX_TOTAL_HAIRCUT_PP}pp) | {base_return:.2f}% → {adjusted:.2f}%",
    )
    return adjusted, notes


# ══════════════════════════════════════════════════════════════════════
#  B: Scenario Engine — deterministic (v2 — uses creditMetrics)
# ══════════════════════════════════════════════════════════════════════

_SCENARIO_PROXY: dict[str, dict[str, float]] = {
    "Base":     {"loss_rate": 1.0, "recovery_rate": 70.0},
    "Downside": {"loss_rate": 3.0, "recovery_rate": 55.0},
    "Severe":   {"loss_rate": 7.0, "recovery_rate": 40.0},
}
_CONCENTRATION_LOSS_ADJ_PP = 2.0


def _build_deterministic_scenarios(
    base_return_pct: float | None,
    risks: list[dict],
    credit_metrics: dict[str, Any] | None = None,
    concentration_profile: dict[str, Any] | None = None,
    liquidity_hooks: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Build Base / Downside / Severe scenarios.

    Uses creditMetrics.defaultRatePct / recoveryRatePct when available,
    otherwise proxy values labelled PROXY_FROM_SEVERITY.
    """
    proxy_flags: list[str] = []
    _cm = credit_metrics or {}
    _conc = concentration_profile or {}
    _liq = liquidity_hooks or {}

    if base_return_pct is None:
        return [], ["SCENARIO_SKIPPED_NO_BASE_RETURN"]

    # ── Credit metrics → actual default/recovery ─────────────────
    cm_default = _v2_num(_cm, "defaultRatePct")
    cm_recovery = _v2_num(_cm, "recoveryRatePct")

    # ── Concentration adjustment ─────────────────────────────────
    conc_adj = 0.0
    conc_note = ""
    top_exposure = _conc.get("top_single_exposure_pct") or 0.0
    if top_exposure >= 80.0 or _conc.get("single_name_100_pct"):
        conc_adj = _CONCENTRATION_LOSS_ADJ_PP
        conc_note = f"CONCENTRATION_ADJ +{conc_adj}pp loss (single-name ≥80%)"

    # ── Liquidity delay from hooks ───────────────────────────────
    lockup_months = _liq.get("lockup_months")

    scenarios: list[dict[str, Any]] = []
    for name, proxy in _SCENARIO_PROXY.items():
        notes: list[str] = []
        inputs_used: dict[str, Any] = {}

        # Loss rate
        if cm_default is not None and name == "Base":
            loss = cm_default
            inputs_used["loss_rate_source"] = "CREDIT_METRICS"
        else:
            loss = proxy["loss_rate"]
            inputs_used["loss_rate_source"] = "PROXY_FROM_SEVERITY"
            if name == "Base":
                proxy_flags.append(f"PROXY_FROM_SEVERITY:loss_rate:{name}")
                notes.append("Loss rate is a proxy from severity scale")

        # Recovery rate
        if cm_recovery is not None and name == "Base":
            recovery = cm_recovery
            inputs_used["recovery_rate_source"] = "CREDIT_METRICS"
        else:
            recovery = proxy["recovery_rate"]
            inputs_used["recovery_rate_source"] = "PROXY_FROM_SEVERITY"
            if name == "Base":
                proxy_flags.append(f"PROXY_FROM_SEVERITY:recovery_rate:{name}")
                notes.append("Recovery rate is a proxy from severity scale")

        # Concentration adjustment
        if conc_adj > 0:
            loss += conc_adj
            notes.append(conc_note)
            if f"CONCENTRATION_ADJ:{name}" not in proxy_flags:
                proxy_flags.append(f"CONCENTRATION_ADJ:{name}")

        loss_impact = loss * (1.0 - recovery / 100.0)
        expected_net = round(base_return_pct - loss_impact, 4)
        nav_drawdown = round(loss * (1.0 - recovery / 100.0), 4)

        inputs_used.update({
            "base_return_pct": base_return_pct,
            "loss_rate_pct": loss,
            "recovery_rate_pct": recovery,
            "concentration_adj_pp": conc_adj,
        })

        scenarios.append({
            "scenario_name": name,
            "inputs_used": inputs_used,
            "expected_net_return_pct": expected_net,
            "nav_drawdown_proxy_pct": nav_drawdown if nav_drawdown > 0 else None,
            "loss_rate_pct": loss,
            "recovery_rate_pct": recovery,
            "liquidity_delay_months": lockup_months,
            "notes": notes,
        })

    return scenarios, proxy_flags


# ══════════════════════════════════════════════════════════════════════
#  C: Sensitivity — 2D grid + 3D summary (legacy 1D deprecated)
# ══════════════════════════════════════════════════════════════════════

_DEFAULT_RATES_GRID = [1.0, 3.0, 5.0, 8.0]
_RECOVERY_RATES_GRID = [80.0, 65.0, 50.0, 35.0]


def _build_sensitivity_2d(
    base_return_pct: float | None,
    proxy_flags: list[str],
) -> list[dict[str, Any]]:
    """Build 2D sensitivity grid: default_rate × recovery_rate."""
    if base_return_pct is None:
        return []

    grid: list[dict[str, Any]] = []
    for dr in _DEFAULT_RATES_GRID:
        for rr in _RECOVERY_RATES_GRID:
            loss_impact = dr * (1.0 - rr / 100.0)
            net = round(base_return_pct - loss_impact, 4)
            grid.append({
                "default_rate_pct": dr,
                "recovery_rate_pct": rr,
                "loss_impact_pct": round(loss_impact, 4),
                "net_return_pct": net,
            })
    return grid


_RATE_SHOCKS_BPS = [0, 100, 200]


def _build_sensitivity_3d_summary(
    base_return_pct: float | None,
    sensitivity_2d: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build 3D summary: default × recovery × rate shocks."""
    if base_return_pct is None or not sensitivity_2d:
        return {}

    all_cells: list[dict[str, Any]] = []
    for shock in _RATE_SHOCKS_BPS:
        shock_pct = shock / 100.0
        for cell in sensitivity_2d:
            shocked_return = round(cell["net_return_pct"] - shock_pct, 4)
            all_cells.append({
                "rate_shock_bps": shock,
                "default_rate_pct": cell["default_rate_pct"],
                "recovery_rate_pct": cell["recovery_rate_pct"],
                "shocked_net_return_pct": shocked_return,
            })

    all_cells.sort(key=lambda c: c["shocked_net_return_pct"])
    top_fragile = all_cells[:5]

    break_even: dict[str, Any] = {}
    for cell in all_cells:
        if cell["shocked_net_return_pct"] <= 0.0:
            break_even = {
                "rate_shock_bps": cell["rate_shock_bps"],
                "default_rate_pct": cell["default_rate_pct"],
                "recovery_rate_pct": cell["recovery_rate_pct"],
                "note": "First combination where net return ≤ 0%",
            }
            break

    shock0 = [c for c in all_cells if c["rate_shock_bps"] == 0]
    dominant = "unknown"
    if shock0:
        dr_groups: dict[float, list[float]] = {}
        rr_groups: dict[float, list[float]] = {}
        for c in shock0:
            dr_groups.setdefault(c["default_rate_pct"], []).append(c["shocked_net_return_pct"])
            rr_groups.setdefault(c["recovery_rate_pct"], []).append(c["shocked_net_return_pct"])
        dr_means = [sum(v) / len(v) for v in dr_groups.values()]
        rr_means = [sum(v) / len(v) for v in rr_groups.values()]
        dr_range = max(dr_means) - min(dr_means) if dr_means else 0
        rr_range = max(rr_means) - min(rr_means) if rr_means else 0
        if dr_range > rr_range * 1.5:
            dominant = "default_rate"
        elif rr_range > dr_range * 1.5:
            dominant = "recovery_rate"
        else:
            dominant = "balanced"

    return {
        "top_fragile_combinations": top_fragile,
        "break_even_thresholds": break_even,
        "dominant_driver": dominant,
        "rate_shocks_bps": _RATE_SHOCKS_BPS,
        "note": "3D summary: default_rate × recovery_rate × rate_shock",
    }


# Legacy 1D sensitivity (deprecated, kept for backward compat)
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
        ("Stress -200bps", -2.0), ("Stress -100bps", -1.0),
        ("Base Case", 0.0), ("Upside +100bps", 1.0), ("Upside +200bps", 2.0),
    ]:
        scenarios.append({
            "scenario": label, "delta_bps": int(delta_bps * 100),
            "adjusted_irr_pct": round(base + delta_bps, 4),
        })
    return scenarios


# ══════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════


def compute_quant_profile(
    structured_analysis: dict[str, Any],
    *,
    deal_fields: dict[str, Any] | None = None,
    macro_snapshot: dict[str, Any] | None = None,
    concentration_profile: dict[str, Any] | None = None,
) -> QuantProfile:
    """Compute deterministic quant profile from structured_analysis_v2.

    If schemaVersion != "2.0", the input is migrated via the v1→v2 shim.

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
        rate_structure, fees if isinstance(fees, list) else [],
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
        # Fallback to legacy investmentTerms.principalAmount
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
    scenarios, scenario_proxy_flags = _build_deterministic_scenarios(
        _scenario_base,
        risks,
        credit_metrics=credit_metrics,
        concentration_profile=concentration_profile,
        liquidity_hooks=liq_hooks,
    )
    profile.scenario_results = scenarios
    proxy_flags.extend(scenario_proxy_flags)

    # ── C: Sensitivity 2D & 3D ───────────────────────────────────
    profile.sensitivity_2d = _build_sensitivity_2d(_scenario_base, proxy_flags)
    profile.sensitivity_3d_summary = _build_sensitivity_3d_summary(
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
        "QUANT_PROFILE_COMPUTED",
        extra={
            "schema_version": profile.schema_version_used,
            "migrated": analysis.get("_migrated_from_v1", False),
            "metrics_status": profile.metrics_status,
            "missing_fields": missing,
            "proxy_flags": proxy_flags,
            "coupon": profile.gross_coupon_pct,
            "irr": profile.target_irr_pct,
            "scenario_count": len(scenarios),
            "sensitivity_2d_cells": len(profile.sensitivity_2d),
            "tenor_bucket": profile.tenor_bucket,
            "liquidity_flags": profile.liquidity_flags,
        },
    )

    return profile
