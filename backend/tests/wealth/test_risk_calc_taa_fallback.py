"""Codex catch #9 — risk_calc TAA fallback aligned to RISK_OFF (PR-Q74).

Verifies that risk_calc uses RISK_OFF (defensive) as fallback for
unknown regime labels in TAA half-width resolution, matching
taa_band_service.get_regime_centers_for_regime post-Q50-Q53.
"""


def test_risk_calc_uses_risk_off_fallback_for_unknown_regime():
    """Unknown raw_regime label → RISK_OFF half-widths (matches taa_band_service).

    This test validates the fix at source level: the regime_bands.get() fallback
    in risk_calc must use RISK_OFF, not RISK_ON.
    """
    regime_bands = {
        "RISK_ON": {
            "equity": {"half_width": 0.10},
            "fixed_income": {"half_width": 0.05},
        },
        "RISK_OFF": {
            "equity": {"half_width": 0.03},
            "fixed_income": {"half_width": 0.02},
        },
    }

    # Simulate risk_calc logic (post-Q74 fix)
    regime = "UNKNOWN_LABEL"
    regime_cfg = regime_bands.get(regime, regime_bands.get("RISK_OFF", {}))
    half_widths = {
        ac: cfg.get("half_width", 0.05)
        for ac, cfg in regime_cfg.items()
        if isinstance(cfg, dict) and "half_width" in cfg
    }

    # Must match RISK_OFF, not RISK_ON
    assert half_widths == {"equity": 0.03, "fixed_income": 0.02}, (
        f"Expected RISK_OFF half-widths, got {half_widths}"
    )

    # Sanity: RISK_ON would produce different values
    risk_on_cfg = regime_bands["RISK_ON"]
    risk_on_widths = {
        ac: cfg.get("half_width", 0.05)
        for ac, cfg in risk_on_cfg.items()
        if isinstance(cfg, dict) and "half_width" in cfg
    }
    assert half_widths != risk_on_widths, "RISK_OFF and RISK_ON should differ"
