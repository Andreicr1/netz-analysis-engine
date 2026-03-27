"""Credit-specific deterministic scenario analysis.

Builds Base / Downside / Severe scenarios using credit metrics
(default rate, recovery rate, concentration adjustment).

Sync service — pure computation, no I/O.

Imports only models.py (leaf).
"""
from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()

# Scenario proxy table — severity-scaled default assumptions
SCENARIO_PROXY: dict[str, dict[str, float]] = {
    "Base": {"loss_rate": 1.0, "recovery_rate": 70.0},
    "Downside": {"loss_rate": 3.0, "recovery_rate": 55.0},
    "Severe": {"loss_rate": 7.0, "recovery_rate": 40.0},
}
CONCENTRATION_LOSS_ADJ_PP = 2.0


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
        try:
            cleaned = val.replace("%", "").replace(",", "").strip()
            return float(cleaned) if cleaned else None
        except (ValueError, TypeError):
            return None
    return None


def build_deterministic_scenarios(
    base_return_pct: float | None,
    risks: list[dict[str, Any]],
    credit_metrics: dict[str, Any] | None = None,
    concentration_profile: dict[str, Any] | None = None,
    liquidity_hooks: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Build Base / Downside / Severe scenarios.

    Uses creditMetrics.defaultRatePct / recoveryRatePct when available,
    otherwise proxy values labelled PROXY_FROM_SEVERITY.

    Args:
        base_return_pct: Base return percentage. None → skip with flag.
        risks: Risk factors list (passed for interface compat).
        credit_metrics: Credit metrics dict with defaultRatePct/recoveryRatePct.
        concentration_profile: Concentration profile with top_single_exposure_pct.
        liquidity_hooks: Liquidity hooks with lockup_months.

    Returns:
        (scenarios, proxy_flags) tuple.

    """
    proxy_flags: list[str] = []
    _cm = credit_metrics or {}
    _conc = concentration_profile or {}
    _liq = liquidity_hooks or {}

    if base_return_pct is None:
        return [], ["SCENARIO_SKIPPED_NO_BASE_RETURN"]

    cm_default = _v2_num(_cm, "defaultRatePct")
    cm_recovery = _v2_num(_cm, "recoveryRatePct")

    conc_adj = 0.0
    conc_note = ""
    top_exposure = _conc.get("top_single_exposure_pct") or 0.0
    if top_exposure >= 80.0 or _conc.get("single_name_100_pct"):
        conc_adj = CONCENTRATION_LOSS_ADJ_PP
        conc_note = f"CONCENTRATION_ADJ +{conc_adj}pp loss (single-name ≥80%)"

    lockup_months = _liq.get("lockup_months")

    scenarios: list[dict[str, Any]] = []
    for name, proxy in SCENARIO_PROXY.items():
        notes: list[str] = []
        inputs_used: dict[str, Any] = {}

        if cm_default is not None and name == "Base":
            loss = cm_default
            inputs_used["loss_rate_source"] = "CREDIT_METRICS"
        else:
            loss = proxy["loss_rate"]
            inputs_used["loss_rate_source"] = "PROXY_FROM_SEVERITY"
            if name == "Base":
                proxy_flags.append(f"PROXY_FROM_SEVERITY:loss_rate:{name}")
                notes.append("Loss rate is a proxy from severity scale")

        if cm_recovery is not None and name == "Base":
            recovery = cm_recovery
            inputs_used["recovery_rate_source"] = "CREDIT_METRICS"
        else:
            recovery = proxy["recovery_rate"]
            inputs_used["recovery_rate_source"] = "PROXY_FROM_SEVERITY"
            if name == "Base":
                proxy_flags.append(f"PROXY_FROM_SEVERITY:recovery_rate:{name}")
                notes.append("Recovery rate is a proxy from severity scale")

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
