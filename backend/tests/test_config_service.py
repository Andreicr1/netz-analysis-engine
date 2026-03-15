"""Tests for ConfigService — deep_merge, IP protection, resolve functions."""

from __future__ import annotations

from app.core.config.config_service import ConfigService

# ── deep_merge tests ─────────────────────────────────────────────────────────


class TestDeepMerge:
    def test_scalar_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 99}
        result = ConfigService.deep_merge(base, override)
        assert result == {"a": 1, "b": 99}

    def test_nested_dict_merge(self):
        base = {"outer": {"a": 1, "b": 2}}
        override = {"outer": {"b": 99}}
        result = ConfigService.deep_merge(base, override)
        assert result == {"outer": {"a": 1, "b": 99}}

    def test_deeply_nested_merge(self):
        base = {"l1": {"l2": {"l3": {"a": 1, "b": 2}}}}
        override = {"l1": {"l2": {"l3": {"b": 99}}}}
        result = ConfigService.deep_merge(base, override)
        assert result == {"l1": {"l2": {"l3": {"a": 1, "b": 99}}}}

    def test_list_replaced_not_appended(self):
        base = {"items": [1, 2, 3]}
        override = {"items": [99]}
        result = ConfigService.deep_merge(base, override)
        assert result == {"items": [99]}

    def test_new_key_added(self):
        base = {"a": 1}
        override = {"b": 2}
        result = ConfigService.deep_merge(base, override)
        assert result == {"a": 1, "b": 2}

    def test_empty_override(self):
        base = {"a": 1, "b": {"c": 3}}
        result = ConfigService.deep_merge(base, {})
        assert result == base

    def test_empty_base(self):
        override = {"a": 1}
        result = ConfigService.deep_merge({}, override)
        assert result == {"a": 1}

    def test_base_not_mutated(self):
        base = {"a": {"b": 1}}
        override = {"a": {"b": 2}}
        ConfigService.deep_merge(base, override)
        assert base == {"a": {"b": 1}}  # original unchanged

    def test_credit_ltv_override_example(self):
        """Real-world: client overrides LTV from 65% to 55%."""
        default = {
            "leverage_limits": {"senior_secured": {"max_total_leverage": 5.0, "warning": 4.5}},
            "ltv_limits": {"senior_secured_ltv": {"max_hard": 0.65, "warning": 0.60}},
        }
        override = {
            "ltv_limits": {"senior_secured_ltv": {"max_hard": 0.55}},
        }
        result = ConfigService.deep_merge(default, override)
        assert result["ltv_limits"]["senior_secured_ltv"]["max_hard"] == 0.55
        assert result["ltv_limits"]["senior_secured_ltv"]["warning"] == 0.60  # preserved
        assert result["leverage_limits"]["senior_secured"]["max_total_leverage"] == 5.0  # untouched


# ── CLIENT_VISIBLE_TYPES tests ──────────────────────────────────────────────


class TestIPProtection:
    def test_client_visible_types_excludes_prompts(self):
        assert "prompts" not in ConfigService.CLIENT_VISIBLE_TYPES

    def test_client_visible_types_excludes_model_routing(self):
        assert "model_routing" not in ConfigService.CLIENT_VISIBLE_TYPES

    def test_client_visible_types_excludes_chapters(self):
        """Chapters expose IC memo structure — analytical methodology IP."""
        assert "chapters" not in ConfigService.CLIENT_VISIBLE_TYPES

    def test_client_visible_types_excludes_tone(self):
        assert "tone" not in ConfigService.CLIENT_VISIBLE_TYPES

    def test_client_visible_types_excludes_evaluation(self):
        assert "evaluation" not in ConfigService.CLIENT_VISIBLE_TYPES

    def test_client_visible_types_includes_calibration(self):
        assert "calibration" in ConfigService.CLIENT_VISIBLE_TYPES

    def test_client_visible_types_includes_scoring(self):
        assert "scoring" in ConfigService.CLIENT_VISIBLE_TYPES

    def test_client_visible_types_includes_blocks(self):
        assert "blocks" in ConfigService.CLIENT_VISIBLE_TYPES

    def test_client_visible_types_includes_portfolio_profiles(self):
        assert "portfolio_profiles" in ConfigService.CLIENT_VISIBLE_TYPES

    def test_client_visible_types_is_frozen(self):
        assert isinstance(ConfigService.CLIENT_VISIBLE_TYPES, frozenset)


# ── Resolve functions tests ──────────────────────────────────────────────────


class TestResolveFunctions:
    def test_resolve_cvar_config_none_returns_defaults(self):
        from quant_engine.cvar_service import resolve_cvar_config

        result = resolve_cvar_config(None)
        assert "conservative" in result
        assert "moderate" in result
        assert "growth" in result
        assert result["conservative"]["limit"] == -0.08

    def test_resolve_cvar_config_from_db_format(self):
        from quant_engine.cvar_service import resolve_cvar_config

        config = {
            "profiles": {
                "conservative": {
                    "cvar": {
                        "window_months": 12,
                        "confidence": 0.95,
                        "limit": -0.05,
                        "warning_pct": 0.80,
                        "breach_days": 5,
                    },
                },
            },
        }
        result = resolve_cvar_config(config)
        assert result["conservative"]["limit"] == -0.05

    def test_resolve_regime_thresholds_none_returns_defaults(self):
        from quant_engine.regime_service import resolve_regime_thresholds

        result = resolve_regime_thresholds(None)
        assert result["vix_risk_off"] == 25
        assert result["default"] == "RISK_ON"

    def test_resolve_regime_thresholds_from_config(self):
        from quant_engine.regime_service import resolve_regime_thresholds

        config = {
            "regime_thresholds": {
                "vix_risk_off": 30,
                "vix_extreme": 40,
                "default": "RISK_ON",
            },
        }
        result = resolve_regime_thresholds(config)
        assert result["vix_risk_off"] == 30

    def test_resolve_scoring_weights_none_returns_defaults(self):
        from quant_engine.scoring_service import resolve_scoring_weights

        result = resolve_scoring_weights(None)
        assert abs(sum(result.values()) - 1.0) < 0.001

    def test_resolve_drift_thresholds_none_returns_defaults(self):
        from quant_engine.drift_service import resolve_drift_thresholds

        maint, urgent = resolve_drift_thresholds(None)
        assert maint == 0.05
        assert urgent == 0.10

    def test_resolve_drift_thresholds_from_config(self):
        from quant_engine.drift_service import resolve_drift_thresholds

        config = {"drift_bands": {"maintenance_trigger": 0.03, "urgent_trigger": 0.08}}
        maint, urgent = resolve_drift_thresholds(config)
        assert maint == 0.03
        assert urgent == 0.08


# ── Migration seed data tests ────────────────────────────────────────────────


class TestMigrationSeedFiles:
    """Verify seed YAML files exist and are loadable."""

    def test_credit_calibration_yaml_loadable(self):
        from pathlib import Path

        import yaml

        path = Path(__file__).resolve().parents[2] / "calibration" / "seeds" / "private_credit" / "calibration.yaml"
        assert path.exists(), f"Missing: {path}"
        with open(path) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert "leverage_limits" in data
        assert "coverage_ratios" in data

    def test_credit_scoring_yaml_loadable(self):
        from pathlib import Path

        import yaml

        path = Path(__file__).resolve().parents[2] / "calibration" / "seeds" / "private_credit" / "scoring.yaml"
        assert path.exists(), f"Missing: {path}"
        with open(path) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert "credit_scoring_weights" in data
        weights = data["credit_scoring_weights"]
        assert abs(sum(weights.values()) - 1.0) < 0.001

    def test_all_seed_yamls_exist(self):
        """All YAML files referenced in migration 0004 must exist."""
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        required = [
            "calibration/config/limits.yaml",
            "calibration/config/profiles.yaml",
            "calibration/config/scoring.yaml",
            "calibration/config/blocks.yaml",
            "profiles/private_credit/profile.yaml",
            "calibration/seeds/private_credit/calibration.yaml",
            "calibration/seeds/private_credit/scoring.yaml",
        ]
        for rel_path in required:
            full = root / rel_path
            assert full.exists(), f"Missing seed YAML: {rel_path}"
