"""Tests for dynamic weight amplification in regime classification."""

from quant_engine.regime_service import _amplify_weights, classify_regime_multi_signal


class TestAmplifyWeights:
    def test_calm_signals_unchanged(self):
        """When all signals are calm, weights barely change."""
        signals = [
            ("a", 5.0, 0.25, ""),
            ("b", 3.0, 0.25, ""),
            ("c", 4.0, 0.25, ""),
            ("d", 2.0, 0.25, ""),
        ]
        result = _amplify_weights(signals)
        weights = {l: w for l, _, w, _ in result}
        # All calm -> nearly equal amplification -> weights ~unchanged
        for w in weights.values():
            assert abs(w - 0.25) < 0.02

    def test_extreme_signal_amplified(self):
        """A maxed-out signal gets amplified weight."""
        signals = [
            ("extreme", 100.0, 0.10, ""),
            ("calm1", 5.0, 0.30, ""),
            ("calm2", 5.0, 0.30, ""),
            ("calm3", 5.0, 0.30, ""),
        ]
        result = _amplify_weights(signals)
        w_extreme = next(w for l, _, w, _ in result if l == "extreme")
        # 0.10 * 3.0 = 0.30 before renorm; after renorm ~0.24
        assert w_extreme > 0.20  # significantly above base 0.10

    def test_w_max_cap_enforced(self):
        """When cap is feasible (n * w_max >= 1.0), no signal exceeds w_max."""
        signals = [
            ("a", 100.0, 0.20, ""),
            ("b", 50.0, 0.30, ""),
            ("c", 10.0, 0.25, ""),
            ("d", 0.0, 0.25, ""),
        ]
        result = _amplify_weights(signals, w_max=0.35)
        for _, _, w, _ in result:
            assert w <= 0.35 + 0.001

    def test_w_max_infeasible_uses_uniform(self):
        """When cap is infeasible (n * w_max < 1.0), fall back to uniform weights."""
        signals = [
            ("extreme", 100.0, 0.30, ""),  # 0.30 * 3.0 = 0.90 pre-norm
            ("calm", 5.0, 0.70, ""),
        ]
        result = _amplify_weights(signals, w_max=0.35)
        # n=2, w_max=0.35 → 2*0.35=0.70 < 1.0 → uniform = 0.5 each
        total = sum(w for _, _, w, _ in result)
        assert abs(total - 1.0) < 1e-6
        for _, _, w, _ in result:
            assert abs(w - 0.5) < 1e-6

    def test_weights_sum_to_one(self):
        """Weights always sum to ~1.0 after amplification."""
        signals = [
            ("a", 100.0, 0.20, ""),
            ("b", 50.0, 0.30, ""),
            ("c", 10.0, 0.25, ""),
            ("d", 0.0, 0.25, ""),
        ]
        result = _amplify_weights(signals)
        total = sum(w for _, _, w, _ in result)
        assert abs(total - 1.0) < 0.001

    def test_empty_signals(self):
        """Empty signal list returns empty."""
        assert _amplify_weights([]) == []

    def test_single_signal(self):
        """Single signal normalizes to 1.0, capped at w_max."""
        signals = [("only", 80.0, 0.15, "")]
        # With default w_max=0.35, single signal caps at 0.35
        result = _amplify_weights(signals, w_max=1.0)
        assert len(result) == 1
        assert abs(result[0][2] - 1.0) < 0.001


class TestProfileAWeights:
    def test_energy_shock_crosses_risk_off(self):
        """With Profile A weights + dynamic amplification,
        energy=100 and calm markets should produce RISK_OFF."""
        regime, reasons, _ = classify_regime_multi_signal(
            vix=19.5,
            yield_curve_spread=None,
            cpi_yoy=None,
            hy_oas=2.90,
            baa_spread=1.73,
            energy_shock=100.0,
            cfnai=-0.11,
            sahm_rule=0.20,
            fed_funds_delta_6m=-0.46,
            dxy_zscore=0.03,
        )
        # With dynamic weights, energy at 100/100 should push
        # composite above 25 -> RISK_OFF
        assert regime in ("RISK_OFF", "CRISIS")

    def test_all_calm_still_risk_on(self):
        """When all signals are calm, dynamic weights don't change regime."""
        regime, _, _ = classify_regime_multi_signal(
            vix=15.0,
            yield_curve_spread=None,
            cpi_yoy=None,
            hy_oas=2.0,
            baa_spread=1.0,
            energy_shock=5.0,
            cfnai=0.10,
            sahm_rule=0.05,
            fed_funds_delta_6m=0.0,
            dxy_zscore=0.0,
        )
        assert regime == "RISK_ON"

    def test_multi_extreme_produces_crisis(self):
        """Multiple extreme signals should produce CRISIS."""
        regime, _, _ = classify_regime_multi_signal(
            vix=45.0,
            yield_curve_spread=None,
            cpi_yoy=None,
            hy_oas=8.0,
            baa_spread=3.0,
            energy_shock=100.0,
            cfnai=-0.80,
            sahm_rule=0.60,
            fed_funds_delta_6m=2.0,
            dxy_zscore=2.5,
        )
        assert regime == "CRISIS"

    def test_audit_trail_in_reasons(self):
        """Dynamic weight changes appear in reasons dict."""
        _, reasons, _ = classify_regime_multi_signal(
            vix=19.5,
            yield_curve_spread=None,
            cpi_yoy=None,
            hy_oas=2.90,
            energy_shock=100.0,
            cfnai=-0.11,
        )
        # Should have amplification config recorded
        assert "amplification" in reasons
        assert "alpha=2.0" in reasons["amplification"]
        # Energy at 100 should get amplified -> w_dyn entry
        w_dyn_keys = [k for k in reasons if k.startswith("w_dyn_")]
        assert len(w_dyn_keys) > 0

    def test_missing_signals_still_work(self):
        """When only a few signals are present, renormalization + amplification work."""
        regime, reasons, _ = classify_regime_multi_signal(
            vix=20.0,
            yield_curve_spread=None,
            cpi_yoy=None,
            energy_shock=80.0,
        )
        assert regime in ("RISK_ON", "RISK_OFF", "CRISIS")
        assert "amplification" in reasons
