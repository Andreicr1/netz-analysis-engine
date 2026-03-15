"""V1→V2 migration shim and field accessor helpers.

Merges: _migrate_v1_to_v2, _ensure_v2, all _v2_* helpers, _parse_* helpers.
Imports only models.py (leaf).
"""
from __future__ import annotations

import copy
import re
from typing import Any

import structlog

from vertical_engines.credit.quant.models import NUM_RE

logger = structlog.get_logger()


# ── v2 field accessors (typed, null-safe) ─────────────────────────────


def _v2_num(block: dict[str, Any] | None, key: str) -> float | None:
    """Extract a numeric field from a v2 block. Accepts float/int/str."""
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
        m = NUM_RE.search(val)
        return int(float(m.group())) if m else None
    return None


def _v2_str(block: dict[str, Any] | None, key: str) -> str | None:
    """Extract a string field from a v2 block."""
    if not block:
        return None
    val = block.get(key)
    if val is None or not isinstance(val, str) or not val.strip():
        return None
    result: str = val.strip()
    return result


def _v2_bool(block: dict[str, Any] | None, key: str) -> bool | None:
    """Extract a boolean field from a v2 block."""
    if not block:
        return None
    val = block.get(key)
    if isinstance(val, bool):
        return val
    return None


# ── Numeric parsing helpers ───────────────────────────────────────────


def _parse_pct(value: str | None) -> float | None:
    """Parse a percentage string like '8.5%' or 'LIBOR + 450bps' into float."""
    if not value or not isinstance(value, str):
        return None
    value = value.strip().replace(",", "")
    if "%" in value:
        m = NUM_RE.search(value.replace("%", ""))
        return float(m.group()) if m else None
    if "bps" in value.lower():
        m = NUM_RE.search(value)
        return float(m.group()) / 100.0 if m else None
    m = NUM_RE.search(value)
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
    m = NUM_RE.search(value)
    return float(m.group()) * multiplier if m else None


def _parse_multiple(value: str | None) -> float | None:
    """Parse a multiple like '1.5x' or '2.0' into float."""
    if not value or not isinstance(value, str):
        return None
    value = value.strip().lower().replace("x", "")
    m = NUM_RE.search(value)
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


# ── V1 → V2 Migration Shim ───────────────────────────────────────────


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
        "legacy_schema_migration",
        legacy_schema_detected=True,
        schema_version=analysis.get("schemaVersion"),
    )
    out = copy.deepcopy(analysis)
    out["schemaVersion"] = "2.0"
    out["_migrated_from_v1"] = True

    old_terms = out.get("investmentTerms") or {}
    old_returns = out.get("expectedReturns") or {}

    # ── rateStructure ────────────────────────────────────────────
    if "rateStructure" not in old_terms:
        rs: dict[str, Any] = {}
        coupon_raw = old_returns.get("couponRate") or old_terms.get("interestRate")
        coupon_parsed = _parse_pct(coupon_raw) if coupon_raw else None
        if coupon_parsed is not None:
            rs["couponRatePct"] = coupon_parsed
            rs["_source"] = "migrated_from_v1"
            rs["_confidence"] = "LOW"
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
            if re.match(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", stripped):
                mat_block["maturityDateISO"] = stripped
            else:
                lower = stripped.lower()
                m = NUM_RE.search(lower)
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
            "managementFee": "MANAGEMENT",
            "performanceFee": "PERFORMANCE",
            "servicingFee": "SERVICING",
            "adminFee": "ADMIN",
            "originationFee": "ORIGINATION",
            "exitFee": "EXIT",
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
        raw_lockup = fund_liq.get("investorLockupYears") or old_terms.get("lockupPeriod")
        if raw_lockup and isinstance(raw_lockup, str):
            lower = raw_lockup.lower()
            m = NUM_RE.search(lower)
            if m:
                val = float(m.group())
                if "year" in lower:
                    liq["lockupMonths"] = val * 12
                elif "month" in lower:
                    liq["lockupMonths"] = val
                elif "day" in lower:
                    liq["noticePeriodDays"] = int(val)
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
