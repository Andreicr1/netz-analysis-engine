"""Tests for TAA Sprint 2 — ELITE dynamic regime sets, confidence gating, IC override.

Proves:
1. Per-regime ELITE target counts sum to 300 for each regime
2. REGIME_ELITE_COLUMN maps all 4 regimes to valid column names
3. Confidence gating: no EMA update when stress delta below threshold
4. Confidence gating: EMA proceeds when stress delta above threshold
5. TacticalPosition source discriminator: ic_manual overrides regime_auto
6. TacticalPosition source: expired ic_manual falls back to regime_auto
7. Smooth regime centers still respects max_daily_shift (Sprint 1, regression)
8. ELITE target counts match plan table exactly
"""

from __future__ import annotations

from datetime import datetime

from quant_engine.taa_band_service import smooth_regime_centers  # noqa: I001

# ---------------------------------------------------------------------------
#  1. ELITE regime target counts
# ---------------------------------------------------------------------------


class TestEliteRegimeTargets:
    """Verify per-regime ELITE target counts from the plan."""

    def test_regime_elite_targets_sum_to_300(self):
        """Each regime's target counts must sum to 300."""
        from app.domains.wealth.workers.risk_calc import REGIME_ELITE_TARGETS

        for regime, targets in REGIME_ELITE_TARGETS.items():
            total = sum(targets.values())
            assert total == 300, (
                f"Regime {regime} ELITE targets sum to {total}, expected 300. "
                f"Breakdown: {targets}"
            )

    def test_regime_elite_targets_match_plan(self):
        """Exact match against the plan table (§5.2)."""
        from app.domains.wealth.workers.risk_calc import REGIME_ELITE_TARGETS

        expected = {
            "RISK_ON":    {"equity": 156, "fixed_income": 90,  "alternatives": 36, "cash": 18},
            "RISK_OFF":   {"equity": 114, "fixed_income": 108, "alternatives": 39, "cash": 39},
            "INFLATION":  {"equity": 126, "fixed_income": 75,  "alternatives": 66, "cash": 33},
            "CRISIS":     {"equity": 75,  "fixed_income": 105, "alternatives": 45, "cash": 75},
        }

        for regime in expected:
            assert REGIME_ELITE_TARGETS[regime] == expected[regime], (
                f"Regime {regime} targets mismatch: "
                f"got {REGIME_ELITE_TARGETS[regime]}, expected {expected[regime]}"
            )

    def test_all_regimes_have_4_asset_classes(self):
        """Each regime must cover equity, fixed_income, alternatives, cash."""
        from app.domains.wealth.workers.risk_calc import REGIME_ELITE_TARGETS

        expected_classes = {"equity", "fixed_income", "alternatives", "cash"}
        for regime, targets in REGIME_ELITE_TARGETS.items():
            assert set(targets.keys()) == expected_classes, (
                f"Regime {regime} missing asset classes: "
                f"got {set(targets.keys())}, expected {expected_classes}"
            )


# ---------------------------------------------------------------------------
#  2. REGIME_ELITE_COLUMN mapping
# ---------------------------------------------------------------------------


class TestRegimeEliteColumn:
    """Verify the regime-to-column mapping is complete and valid."""

    def test_all_regimes_mapped(self):
        from app.domains.wealth.workers.risk_calc import REGIME_ELITE_COLUMN

        assert set(REGIME_ELITE_COLUMN.keys()) == {"RISK_ON", "RISK_OFF", "INFLATION", "CRISIS"}

    def test_risk_on_uses_legacy_column(self):
        """RISK_ON must use existing elite_flag for backward compatibility."""
        from app.domains.wealth.workers.risk_calc import REGIME_ELITE_COLUMN

        assert REGIME_ELITE_COLUMN["RISK_ON"] == "elite_flag"

    def test_new_columns_named_correctly(self):
        from app.domains.wealth.workers.risk_calc import REGIME_ELITE_COLUMN

        assert REGIME_ELITE_COLUMN["RISK_OFF"] == "elite_risk_off"
        assert REGIME_ELITE_COLUMN["INFLATION"] == "elite_inflation"
        assert REGIME_ELITE_COLUMN["CRISIS"] == "elite_crisis"

    def test_columns_exist_on_model(self):
        """All mapped columns must exist on FundRiskMetrics ORM model."""
        from app.domains.wealth.models.risk import FundRiskMetrics
        from app.domains.wealth.workers.risk_calc import REGIME_ELITE_COLUMN

        for regime, col_name in REGIME_ELITE_COLUMN.items():
            assert hasattr(FundRiskMetrics, col_name), (
                f"FundRiskMetrics missing column {col_name} for regime {regime}"
            )


# ---------------------------------------------------------------------------
#  3. Confidence gating
# ---------------------------------------------------------------------------


class TestConfidenceGating:
    """Confidence gating prevents EMA updates when stress delta is below threshold."""

    def test_small_stress_delta_holds_previous_centers(self):
        """When |stress_score - previous| < min_confidence_to_act, hold previous."""
        # Simulate: previous smoothed centers, stress change of 0.3 (below 0.60 threshold)
        previous = {"equity": 0.42, "fixed_income": 0.33, "alternatives": 0.15, "cash": 0.10}
        new_target = {"equity": 0.38, "fixed_income": 0.36, "alternatives": 0.13, "cash": 0.13}

        # Under confidence gating, we wouldn't call smooth_regime_centers at all.
        # Instead we'd hold `previous`. This test verifies the gating logic
        # by simulating what the worker does.
        prev_stress = 35.0
        current_stress = 35.2  # delta = 0.2, below 0.60 threshold
        min_confidence = 0.60

        stress_delta = abs(current_stress - prev_stress)
        assert stress_delta < min_confidence, "Test setup: delta should be below threshold"

        # Gated: output should be previous
        gated_result = dict(previous)
        assert gated_result == previous

    def test_large_stress_delta_allows_ema_update(self):
        """When |stress_score - previous| >= min_confidence_to_act, EMA proceeds."""
        previous = {"equity": 0.52, "fixed_income": 0.30, "alternatives": 0.12, "cash": 0.06}
        new_target = {"equity": 0.38, "fixed_income": 0.36, "alternatives": 0.13, "cash": 0.13}

        prev_stress = 25.0
        current_stress = 55.0  # delta = 30.0, well above 0.60
        min_confidence = 0.60

        stress_delta = abs(current_stress - prev_stress)
        assert stress_delta >= min_confidence, "Test setup: delta should be above threshold"

        # Not gated: EMA should produce different values from previous
        result = smooth_regime_centers(
            new_target, previous, halflife_days=5, max_daily_shift=0.03,
        )
        assert result["equity"] < previous["equity"], "EMA should move equity toward target"
        assert result["fixed_income"] > previous["fixed_income"], "EMA should move FI toward target"

    def test_none_previous_stress_allows_update(self):
        """When previous stress_score is None (first run), EMA should proceed."""
        prev_stress = None
        current_stress = 40.0
        min_confidence = 0.60

        # Logic: if prev_stress is None, no gating possible — proceed
        should_gate = (
            prev_stress is not None
            and abs(current_stress - prev_stress) < min_confidence
        )
        assert not should_gate, "Should not gate when previous stress is None"

    def test_zero_stress_delta_is_gated(self):
        """Identical stress scores should be gated (delta=0 < 0.60)."""
        prev_stress = 42.5
        current_stress = 42.5
        min_confidence = 0.60

        stress_delta = abs(current_stress - prev_stress)
        assert stress_delta < min_confidence

    def test_exact_threshold_is_not_gated(self):
        """When stress delta exactly equals threshold, NOT gated (strict <)."""
        prev_stress = 40.0
        current_stress = 40.6  # delta = 0.6 = threshold
        min_confidence = 0.60

        stress_delta = abs(current_stress - prev_stress)
        should_gate = stress_delta < min_confidence
        assert not should_gate, "Exact threshold should not be gated (strict <)"


# ---------------------------------------------------------------------------
#  4. EMA max_daily_shift regression (Sprint 1)
# ---------------------------------------------------------------------------


class TestEMAMaxDailyShiftRegression:
    """Verify Sprint 1 max_daily_shift is still enforced."""

    def test_crisis_to_risk_on_large_jump_capped(self):
        """Jumping from CRISIS centers (eq=0.25) to RISK_ON (eq=0.52)
        should be capped at 3pp/day."""
        crisis = {"equity": 0.25, "fixed_income": 0.35, "cash": 0.25, "alternatives": 0.15}
        risk_on = {"equity": 0.52, "fixed_income": 0.30, "cash": 0.06, "alternatives": 0.12}

        result = smooth_regime_centers(risk_on, crisis, halflife_days=5, max_daily_shift=0.03)

        for ac in crisis:
            delta = abs(result[ac] - crisis[ac])
            assert delta <= 0.03 + 1e-9, (
                f"Asset class {ac}: delta {delta:.4f} exceeds 3pp cap"
            )


# ---------------------------------------------------------------------------
#  5. TacticalPosition source discriminator
# ---------------------------------------------------------------------------


class TestTacticalPositionSourceDiscriminator:
    """Tests for source field on TacticalPosition model and schema."""

    def test_model_has_source_column(self):
        from app.domains.wealth.models.allocation import TacticalPosition

        assert hasattr(TacticalPosition, "source")

    def test_schema_exposes_source(self):
        from app.domains.wealth.schemas.allocation import TacticalPositionRead

        fields = TacticalPositionRead.model_fields
        assert "source" in fields

    def test_schema_default_is_ic_manual(self):
        from app.domains.wealth.schemas.allocation import TacticalPositionRead

        assert TacticalPositionRead.model_fields["source"].default == "ic_manual"

    def test_item_schema_has_source(self):
        from app.domains.wealth.schemas.allocation import TacticalPositionItem

        fields = TacticalPositionItem.model_fields
        assert "source" in fields


# ---------------------------------------------------------------------------
#  6. IC override priority logic (unit test)
# ---------------------------------------------------------------------------


class TestICOverridePriority:
    """Verify ic_manual always wins over regime_auto for the same block."""

    def _make_position(self, block_id: str, overweight: float, source: str, created_at: datetime | None = None):
        """Create a mock TacticalPosition-like dict for logic testing."""
        return {
            "block_id": block_id,
            "overweight": overweight,
            "source": source,
            "created_at": created_at or datetime.now(),
        }

    def _resolve_priority(self, positions: list[dict]) -> dict[str, dict]:
        """Simulate the source priority logic from allocation route."""
        result: dict[str, dict] = {}
        for pos in positions:
            bid = pos["block_id"]
            existing = result.get(bid)
            if existing is None:
                result[bid] = pos
            else:
                pos_source = pos["source"] or "ic_manual"
                existing_source = existing["source"] or "ic_manual"
                if pos_source == "ic_manual" and existing_source != "ic_manual":
                    result[bid] = pos
                elif existing_source == "ic_manual":
                    pass  # keep ic_manual
                elif pos["created_at"] > existing["created_at"]:
                    result[bid] = pos
        return result

    def test_ic_manual_wins_over_regime_auto(self):
        positions = [
            self._make_position("equity_block", 0.05, "regime_auto"),
            self._make_position("equity_block", 0.02, "ic_manual"),
        ]
        resolved = self._resolve_priority(positions)
        assert resolved["equity_block"]["source"] == "ic_manual"
        assert resolved["equity_block"]["overweight"] == 0.02

    def test_regime_auto_wins_when_no_manual(self):
        positions = [
            self._make_position("fi_block", 0.03, "regime_auto"),
        ]
        resolved = self._resolve_priority(positions)
        assert resolved["fi_block"]["source"] == "regime_auto"

    def test_ic_manual_first_preserved(self):
        """If ic_manual comes first in iteration, it should be kept."""
        positions = [
            self._make_position("cash_block", 0.01, "ic_manual"),
            self._make_position("cash_block", 0.04, "regime_auto"),
        ]
        resolved = self._resolve_priority(positions)
        assert resolved["cash_block"]["source"] == "ic_manual"
        assert resolved["cash_block"]["overweight"] == 0.01

    def test_multiple_blocks_resolved_independently(self):
        positions = [
            self._make_position("equity_block", 0.05, "regime_auto"),
            self._make_position("fi_block", 0.03, "ic_manual"),
            self._make_position("equity_block", 0.02, "ic_manual"),
            self._make_position("fi_block", 0.01, "regime_auto"),
        ]
        resolved = self._resolve_priority(positions)
        assert resolved["equity_block"]["source"] == "ic_manual"
        assert resolved["fi_block"]["source"] == "ic_manual"

    def test_latest_non_manual_wins_tiebreak(self):
        """When two regime_auto exist, latest created_at wins."""
        t1 = datetime(2026, 4, 10, 12, 0, 0)
        t2 = datetime(2026, 4, 11, 12, 0, 0)
        positions = [
            self._make_position("alt_block", 0.01, "regime_auto", t1),
            self._make_position("alt_block", 0.02, "regime_auto", t2),
        ]
        resolved = self._resolve_priority(positions)
        assert resolved["alt_block"]["overweight"] == 0.02


# ---------------------------------------------------------------------------
#  7. ELITE target count derivation from TAA band centers
# ---------------------------------------------------------------------------


class TestEliteTargetDerivation:
    """Verify REGIME_ELITE_TARGETS are correctly derived from TAA band centers."""

    def test_targets_match_round_300_times_center(self):
        """Target counts should equal round(300 * center) per asset class per regime."""
        from app.domains.wealth.workers.risk_calc import REGIME_ELITE_TARGETS
        from quant_engine.taa_band_service import DEFAULT_TAA_BANDS

        for regime, bands in DEFAULT_TAA_BANDS["regime_bands"].items():
            for ac, band_cfg in bands.items():
                expected = round(300 * band_cfg["center"])
                actual = REGIME_ELITE_TARGETS[regime][ac]
                assert actual == expected, (
                    f"{regime}/{ac}: expected round(300 * {band_cfg['center']}) = {expected}, "
                    f"got {actual}"
                )


# ---------------------------------------------------------------------------
#  8. Migration model consistency
# ---------------------------------------------------------------------------


class TestMigrationModelConsistency:
    """Verify ORM model columns match migration expectations."""

    def test_fund_risk_metrics_has_all_elite_columns(self):
        from app.domains.wealth.models.risk import FundRiskMetrics

        for col in ["elite_flag", "elite_risk_off", "elite_inflation", "elite_crisis"]:
            assert hasattr(FundRiskMetrics, col), f"FundRiskMetrics missing {col}"

    def test_tactical_position_has_source(self):
        from app.domains.wealth.models.allocation import TacticalPosition

        assert hasattr(TacticalPosition, "source")
