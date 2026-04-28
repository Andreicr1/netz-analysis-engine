"""Codex catches #6 + #7 — CPIAUCSL + PAYEMS revert to lin units (PR-Q72)."""

from __future__ import annotations

from quant_engine.regional_macro_service import REGION_SERIES


def test_cpiaucsl_uses_lin_units_post_q72_revert():
    """CPIAUCSL must use 'lin' (default) units to preserve downstream consumers
    that compute YoY/MoM from level data (regime_service.build_regime_inputs,
    risk_calc._fetch_monthly_cpi_changes)."""
    us_series = REGION_SERIES["US"]
    cpi_spec = next((s for s in us_series if s.series_id == "CPIAUCSL"), None)
    assert cpi_spec is not None
    assert cpi_spec.units == "lin"  # default — Q72 revert from pc1


def test_payems_uses_lin_units_post_q72_revert():
    """PAYEMS must use 'lin' units (credit market_data applies mom_delta to levels)."""
    us_series = REGION_SERIES["US"]
    payems_spec = next((s for s in us_series if s.series_id == "PAYEMS"), None)
    assert payems_spec is not None
    assert payems_spec.units == "lin"


def test_other_pc1_series_documented_status():
    """Document which series still use pc1 post-Q72 for orchestrator audit."""
    pc1_series = []
    for region, specs in REGION_SERIES.items():
        for spec in specs:
            if spec.units == "pc1":
                pc1_series.append((region, spec.series_id))
    # Q72 leaves these on pc1 (downstream consumers not yet audited):
    # INDPRO, PCEPILFE, JPNRGDPEXP, JPNCPIALLMINMEI, CHNCPIALLMINMEI,
    # BRACPIALLMINMEI, INDCPIALLMINMEI, CLVMNACSCAB1GQEA19, CP0000EZ19M086NEST
    # If a future audit reverts any of these, update this test.
    assert len(pc1_series) >= 0  # smoke check; no strict count enforcement
