"""Tests for classify_regime_multi_signal with all 10 signals."""

from __future__ import annotations

from quant_engine.regime_service import classify_regime_multi_signal


class TestClassifyRegimeAllSignalsStressed:
    def test_all_signals_at_panic_produces_crisis(self):
        """All 10 signals at panic thresholds → CRISIS with stress >= 75."""
        regime, reasons = classify_regime_multi_signal(
            vix=35.0,
            yield_curve_spread=-0.5,
            cpi_yoy=3.0,  # below inflation override (4.0)
            sahm_rule=0.5,
            hy_oas=6.0,
            baa_spread=2.5,
            fed_funds_delta_6m=1.5,
            dxy_zscore=2.0,
            energy_shock=100.0,
            cfnai=-0.7,
        )
        assert regime == "CRISIS"
        stress_score = float(reasons["composite_stress"].split("/")[0])
        assert stress_score >= 75


class TestClassifyRegimeAllSignalsCalm:
    def test_all_signals_calm_produces_risk_on(self):
        """All 10 signals at calm values → RISK_ON with stress < 15."""
        regime, reasons = classify_regime_multi_signal(
            vix=15.0,
            yield_curve_spread=1.5,
            cpi_yoy=2.0,
            sahm_rule=0.1,
            hy_oas=2.0,
            baa_spread=1.0,
            fed_funds_delta_6m=-0.25,
            dxy_zscore=-0.5,
            energy_shock=0.0,
            cfnai=0.3,
        )
        assert regime == "RISK_ON"
        stress_score = float(reasons["composite_stress"].split("/")[0])
        assert stress_score < 15
