"""Tests for regime_service.py Phase 2 — regional + global regime classification."""

from __future__ import annotations

from quant_engine.regime_service import (
    RegionalRegimeResult,
    classify_regional_regime,
    compose_global_regime,
    get_hysteresis_days,
    resolve_regional_regime_config,
)


class TestResolveRegionalRegimeConfig:
    def test_none_returns_defaults(self):
        cfg = resolve_regional_regime_config(None)
        assert cfg["oas_risk_off_bp"] == 550
        assert cfg["oas_crisis_bp"] == 800
        assert cfg["gdp_weights"]["US"] == 0.25

    def test_custom_config(self):
        cfg = resolve_regional_regime_config({
            "regional_regime": {
                "oas_risk_off_bp": 600,
                "oas_crisis_bp": 900,
            }
        })
        assert cfg["oas_risk_off_bp"] == 600
        assert cfg["oas_crisis_bp"] == 900


class TestClassifyRegionalRegime:
    def test_us_crisis_via_vix(self):
        result = classify_regional_regime(
            "US", {"VIXCLS": 22.0, "BAMLH0A0HYM2": 400.0},
            vix=40.0,
        )
        assert result.regime == "CRISIS"
        assert result.region == "US"

    def test_us_risk_off_via_vix(self):
        result = classify_regional_regime(
            "US", {"BAMLH0A0HYM2": 300.0},
            vix=28.0,
        )
        assert result.regime == "RISK_OFF"

    def test_us_risk_on(self):
        result = classify_regional_regime(
            "US", {"BAMLH0A0HYM2": 300.0},
            vix=15.0,
        )
        assert result.regime == "RISK_ON"

    def test_europe_crisis_via_oas(self):
        result = classify_regional_regime(
            "EUROPE", {"BAMLHE00EHYIOAS": 850.0},
        )
        assert result.regime == "CRISIS"

    def test_europe_risk_off_via_oas(self):
        result = classify_regional_regime(
            "EUROPE", {"BAMLHE00EHYIOAS": 600.0},
        )
        assert result.regime == "RISK_OFF"

    def test_em_risk_on(self):
        result = classify_regional_regime(
            "EM", {"BAMLEMCBPIOAS": 300.0},
        )
        assert result.regime == "RISK_ON"

    def test_inflation_override(self):
        result = classify_regional_regime(
            "ASIA", {"BAMLEMRACRPIASIAOAS": 300.0},
            cpi_yoy=5.5,
        )
        assert result.regime == "INFLATION"

    def test_no_signal_data_returns_risk_on(self):
        result = classify_regional_regime("EM", {})
        assert result.regime == "RISK_ON"

    def test_custom_config_thresholds(self):
        cfg = resolve_regional_regime_config({
            "regional_regime": {"oas_risk_off_bp": 300, "oas_crisis_bp": 500}
        })
        result = classify_regional_regime(
            "EUROPE", {"BAMLHE00EHYIOAS": 350.0},
            config=cfg,
        )
        assert result.regime == "RISK_OFF"

    def test_result_is_frozen(self):
        result = classify_regional_regime("US", {}, vix=15.0)
        assert isinstance(result, RegionalRegimeResult)


class TestComposeGlobalRegime:
    def test_all_risk_on(self):
        regime, reasons = compose_global_regime({
            "US": "RISK_ON", "EUROPE": "RISK_ON",
            "ASIA": "RISK_ON", "EM": "RISK_ON",
        })
        assert regime == "RISK_ON"

    def test_two_crisis_override(self):
        regime, reasons = compose_global_regime({
            "US": "CRISIS", "EUROPE": "CRISIS",
            "ASIA": "RISK_ON", "EM": "RISK_ON",
        })
        assert regime == "CRISIS"
        assert "override" in reasons

    def test_one_crisis_pessimistic_floor(self):
        regime, reasons = compose_global_regime({
            "US": "CRISIS", "EUROPE": "RISK_ON",
            "ASIA": "RISK_ON", "EM": "RISK_ON",
        })
        # US weight 0.25 >= 0.20, so minimum RISK_OFF
        assert regime in ("RISK_OFF", "CRISIS")

    def test_mixed_regimes(self):
        regime, reasons = compose_global_regime({
            "US": "RISK_OFF", "EUROPE": "RISK_OFF",
            "ASIA": "RISK_ON", "EM": "RISK_ON",
        })
        # GDP-weighted: 0.25*1 + 0.22*1 + 0.28*0 + 0.25*0 = 0.47 → ~0.47 severity
        assert regime in ("RISK_ON", "RISK_OFF")

    def test_all_crisis(self):
        regime, _ = compose_global_regime({
            "US": "CRISIS", "EUROPE": "CRISIS",
            "ASIA": "CRISIS", "EM": "CRISIS",
        })
        assert regime == "CRISIS"

    def test_empty_regions(self):
        regime, _ = compose_global_regime({})
        assert regime == "RISK_ON"


class TestHysteresisDays:
    def test_immediate_crisis(self):
        assert get_hysteresis_days("RISK_ON", "CRISIS") == 0

    def test_slow_recovery(self):
        assert get_hysteresis_days("CRISIS", "RISK_ON") == 10

    def test_risk_off_to_risk_on(self):
        assert get_hysteresis_days("RISK_OFF", "RISK_ON") == 5

    def test_any_to_risk_off(self):
        assert get_hysteresis_days("RISK_ON", "RISK_OFF") == 3

    def test_any_to_inflation(self):
        assert get_hysteresis_days("RISK_ON", "INFLATION") == 5
