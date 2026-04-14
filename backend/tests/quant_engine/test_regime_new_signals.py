"""Tests for new regime signals: ICSA z-score, credit impulse, building permits."""

from __future__ import annotations

from quant_engine.regime_service import classify_regime_multi_signal


class TestIcsaSignal:
    def test_calm_icsa_produces_low_stress(self):
        """ICSA z-score below calm threshold produces zero stress."""
        _, reasons = classify_regime_multi_signal(
            vix=20.0, yield_curve_spread=1.0, cpi_yoy=2.0,
            icsa_zscore=0.3,
        )
        assert any("ICSA" in v and "stress=0" in v for v in reasons.values())

    def test_extreme_icsa_produces_high_stress(self):
        """ICSA z-score at panic level produces high stress."""
        _, reasons = classify_regime_multi_signal(
            vix=20.0, yield_curve_spread=1.0, cpi_yoy=2.0,
            icsa_zscore=3.0,
        )
        assert any("ICSA" in v for v in reasons.values())

    def test_none_icsa_excluded(self):
        """When icsa_zscore is None, signal is excluded from composite."""
        _, reasons_without = classify_regime_multi_signal(
            vix=20.0, yield_curve_spread=1.0, cpi_yoy=2.0,
        )
        _, reasons_with = classify_regime_multi_signal(
            vix=20.0, yield_curve_spread=1.0, cpi_yoy=2.0,
            icsa_zscore=None,
        )
        # Both should have same number of signals (icsa excluded when None)
        assert "icsa" not in reasons_without
        assert "icsa" not in reasons_with


class TestCreditImpulseSignal:
    def test_positive_impulse_low_stress(self):
        """Positive credit growth produces low stress."""
        _, reasons = classify_regime_multi_signal(
            vix=20.0, yield_curve_spread=1.0, cpi_yoy=2.0,
            credit_impulse=2.0,
        )
        # Positive impulse -> inverted ramp -> low stress
        assert any("CreditImpulse" in v and "stress=0" in v for v in reasons.values())

    def test_negative_impulse_high_stress(self):
        """Credit contraction produces high stress."""
        _, reasons = classify_regime_multi_signal(
            vix=20.0, yield_curve_spread=1.0, cpi_yoy=2.0,
            credit_impulse=-3.0,
        )
        assert any("CreditImpulse" in v for v in reasons.values())

    def test_none_credit_impulse_excluded(self):
        """When credit_impulse is None, signal is excluded."""
        _, reasons = classify_regime_multi_signal(
            vix=20.0, yield_curve_spread=1.0, cpi_yoy=2.0,
            credit_impulse=None,
        )
        assert "credit_impulse" not in reasons


class TestPermitsSignal:
    def test_growing_permits_low_stress(self):
        """Rising building permits produce low stress."""
        _, reasons = classify_regime_multi_signal(
            vix=20.0, yield_curve_spread=1.0, cpi_yoy=2.0,
            permits_roc=10.0,
        )
        assert any("Permits" in v and "stress=0" in v for v in reasons.values())

    def test_falling_permits_high_stress(self):
        """Sharply falling permits produce high stress."""
        _, reasons = classify_regime_multi_signal(
            vix=20.0, yield_curve_spread=1.0, cpi_yoy=2.0,
            permits_roc=-25.0,
        )
        assert any("Permits" in v for v in reasons.values())

    def test_none_permits_excluded(self):
        """When permits_roc is None, signal is excluded."""
        _, reasons = classify_regime_multi_signal(
            vix=20.0, yield_curve_spread=1.0, cpi_yoy=2.0,
            permits_roc=None,
        )
        assert "permits" not in reasons


class TestNewSignalsIntegration:
    def test_all_13_signals_calm_still_risk_on(self):
        """All 13 signals at calm values -> RISK_ON."""
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
            icsa_zscore=0.0,
            credit_impulse=3.0,
            permits_roc=10.0,
        )
        assert regime == "RISK_ON"

    def test_all_13_signals_stressed_produces_crisis(self):
        """All 13 signals at panic -> CRISIS."""
        regime, reasons = classify_regime_multi_signal(
            vix=35.0,
            yield_curve_spread=-0.5,
            cpi_yoy=3.0,
            sahm_rule=0.5,
            hy_oas=6.0,
            baa_spread=2.5,
            fed_funds_delta_6m=1.5,
            dxy_zscore=2.0,
            energy_shock=100.0,
            cfnai=-0.7,
            icsa_zscore=3.0,
            credit_impulse=-3.0,
            permits_roc=-25.0,
        )
        assert regime == "CRISIS"
