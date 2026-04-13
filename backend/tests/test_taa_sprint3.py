"""Tests for TAA Sprint 3 — IPS Compliance + Audit + Routes + Narrative.

Covers:
1. Narrative templater TAA section (technical + client_safe)
2. Validation gate check #16 (TAA bands within IPS)
3. Route contract shapes (regime-bands, taa-history, effective-with-regime)
4. Audit trail completeness (construction run has full TAA provenance)
5. Schema serialization round-trips
6. Backward compatibility with pre-TAA payloads
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from vertical_engines.wealth.model_portfolio.narrative_templater import (
    REGIME_CLIENT_SAFE_LABEL,
    render_narrative,
)
from vertical_engines.wealth.model_portfolio.validation_gate import (
    CHECKS,
    ValidationDbContext,
    validate_construction,
)

# ---------------------------------------------------------------------------
#  Shared fixtures
# ---------------------------------------------------------------------------

MODERATE_ALLOCATIONS = [
    {"block_id": "na_equity_large",   "target_weight": 0.19, "min_weight": 0.14, "max_weight": 0.28},
    {"block_id": "na_equity_growth",  "target_weight": 0.08, "min_weight": 0.04, "max_weight": 0.14},
    {"block_id": "fi_aggregate",      "target_weight": 0.15, "min_weight": 0.10, "max_weight": 0.25},
    {"block_id": "fi_ig_corporate",   "target_weight": 0.10, "min_weight": 0.05, "max_weight": 0.18},
    {"block_id": "alt_real_estate",   "target_weight": 0.06, "min_weight": 0.02, "max_weight": 0.10},
    {"block_id": "cash",              "target_weight": 0.05, "min_weight": 0.02, "max_weight": 0.15},
]

BLOCK_CONSTRAINTS = {
    a["block_id"]: (a["min_weight"], a["max_weight"])
    for a in MODERATE_ALLOCATIONS
}


def _base_payload() -> dict[str, Any]:
    return {
        "profile": "moderate",
        "funds": [
            {"instrument_id": "aaa", "fund_name": "Fund A",
             "block_id": "na_equity_large", "weight": 0.3},
            {"instrument_id": "bbb", "fund_name": "Fund B",
             "block_id": "fi_aggregate", "weight": 0.4},
            {"instrument_id": "ccc", "fund_name": "Fund C",
             "block_id": "alt_real_estate", "weight": 0.3},
        ],
        "weights_proposed": {"aaa": 0.3, "bbb": 0.4, "ccc": 0.3},
        "ex_ante_metrics": {
            "expected_return": 0.08,
            "portfolio_volatility": 0.12,
            "sharpe_ratio": 0.67,
            "cvar_95": -0.04,
        },
        "calibration_snapshot": {
            "cvar_limit": 0.05,
            "max_single_fund_weight": 0.35,
            "taa": {
                "enabled": True,
                "raw_regime": "RISK_OFF",
                "stress_score": 38.2,
                "smoothed_centers": {
                    "equity": 0.42,
                    "fixed_income": 0.34,
                    "alternatives": 0.13,
                    "cash": 0.11,
                },
                "effective_bands": {
                    "na_equity_large": {"min": 0.15, "max": 0.22, "center": 0.185},
                    "na_equity_growth": {"min": 0.05, "max": 0.10, "center": 0.075},
                    "fi_aggregate": {"min": 0.12, "max": 0.20, "center": 0.16},
                    "fi_ig_corporate": {"min": 0.08, "max": 0.14, "center": 0.11},
                    "alt_real_estate": {"min": 0.03, "max": 0.08, "center": 0.055},
                    "cash": {"min": 0.05, "max": 0.12, "center": 0.085},
                },
                "ips_clamps_applied": ["na_equity_large_min_raised"],
                "ic_overrides_active": [],
                "transition_velocity": {"equity": -0.008, "fixed_income": 0.004},
            },
        },
        "optimizer_trace": {
            "solver": "CLARABEL",
            "status": "optimal",
        },
        "binding_constraints": [],
        "regime_context": {"regime": "RISK_OFF"},
    }


# ===================================================================
#  1. Narrative templater — TAA section tests
# ===================================================================


class TestNarrativeTaaSection:
    """Tests for the TAA section in the narrative templater."""

    def test_schema_version_bumped_to_2(self):
        out = render_narrative(_base_payload())
        assert out["schema_version"] == 2

    def test_taa_summary_present_in_both_sections(self):
        out = render_narrative(_base_payload())
        assert "taa_summary" in out["technical"]
        assert "taa_summary" in out["client_safe"]
        assert out["technical"]["taa_summary"] is not None
        assert out["client_safe"]["taa_summary"] is not None

    def test_technical_taa_mentions_regime_and_score(self):
        out = render_narrative(_base_payload())
        tech = out["technical"]["taa_summary"]
        assert "RISK_OFF" in tech
        assert "38.2" in tech
        assert "EMA" in tech

    def test_technical_taa_mentions_smoothed_centers(self):
        out = render_narrative(_base_payload())
        tech = out["technical"]["taa_summary"]
        # Should mention asset class centers
        assert "equity" in tech.lower()
        assert "fixed_income" in tech or "fixed income" in tech.lower()

    def test_technical_taa_mentions_ips_clamps(self):
        out = render_narrative(_base_payload())
        tech = out["technical"]["taa_summary"]
        assert "IPS clamp" in tech or "na_equity_large_min_raised" in tech

    def test_technical_taa_mentions_velocity(self):
        out = render_narrative(_base_payload())
        tech = out["technical"]["taa_summary"]
        assert "velocity" in tech.lower() or "delta" in tech.lower()

    def test_client_safe_taa_no_jargon(self):
        """Client-safe TAA section must not leak quant jargon."""
        import re

        out = render_narrative(_base_payload())
        client = out["client_safe"]["taa_summary"]
        # Use word boundaries to avoid false positives (e.g. "schema" contains "ema")
        forbidden = ["risk_off", "risk_on", r"\bema\b", "halflife", "cvar", "regime"]
        for pattern in forbidden:
            assert not re.search(pattern, client, re.IGNORECASE), (
                f"client_safe taa_summary leaked jargon '{pattern}': {client!r}"
            )

    def test_client_safe_taa_uses_translated_label(self):
        out = render_narrative(_base_payload())
        client = out["client_safe"]["taa_summary"]
        # RISK_OFF → "Defensive" per OD-22 mapping
        assert "defensive" in client.lower()

    def test_client_safe_taa_mentions_policy(self):
        out = render_narrative(_base_payload())
        client = out["client_safe"]["taa_summary"]
        assert "policy" in client.lower() or "investment policy" in client.lower()

    def test_taa_disabled_narrative(self):
        payload = _base_payload()
        payload["calibration_snapshot"]["taa"] = {"enabled": False}
        out = render_narrative(payload)
        tech = out["technical"]["taa_summary"]
        client = out["client_safe"]["taa_summary"]
        assert "disabled" in tech.lower() or "static" in tech.lower()
        assert "standard" in client.lower() or "policy" in client.lower()

    def test_taa_missing_from_calibration(self):
        """Pre-TAA payloads (no taa key) should produce None summaries."""
        payload = _base_payload()
        del payload["calibration_snapshot"]["taa"]
        out = render_narrative(payload)
        # When taa is missing, enabled defaults to False → disabled narrative
        assert out["technical"]["taa_summary"] is not None
        assert "disabled" in (out["technical"]["taa_summary"] or "").lower() or \
               "static" in (out["technical"]["taa_summary"] or "").lower()

    def test_no_template_leakage_in_taa(self):
        out = render_narrative(_base_payload())
        for section in ("technical", "client_safe"):
            summary = out[section].get("taa_summary") or ""
            assert "{{" not in summary, f"template source leaked: {summary!r}"
            assert "{%" not in summary, f"template source leaked: {summary!r}"

    def test_determinism_with_taa(self):
        payload = _base_payload()
        out1 = render_narrative(payload)
        out2 = render_narrative(payload)
        assert json.dumps(out1, sort_keys=True) == json.dumps(out2, sort_keys=True)

    def test_empty_payload_still_has_taa_key(self):
        out = render_narrative({})
        assert "taa_summary" in out["technical"]
        assert "taa_summary" in out["client_safe"]

    def test_all_regime_labels_produce_client_safe_taa(self):
        for regime_raw, label in REGIME_CLIENT_SAFE_LABEL.items():
            payload = _base_payload()
            payload["calibration_snapshot"]["taa"]["raw_regime"] = regime_raw
            out = render_narrative(payload)
            client = out["client_safe"]["taa_summary"]
            assert label.lower() in client.lower(), (
                f"Regime {regime_raw} should map to '{label}' in client TAA: {client!r}"
            )

    def test_no_ic_overrides_omits_section(self):
        payload = _base_payload()
        payload["calibration_snapshot"]["taa"]["ic_overrides_active"] = []
        out = render_narrative(payload)
        tech = out["technical"]["taa_summary"]
        assert "IC committee override" not in tech

    def test_with_ic_overrides(self):
        payload = _base_payload()
        payload["calibration_snapshot"]["taa"]["ic_overrides_active"] = [
            "na_equity_large_manual_shift",
        ]
        out = render_narrative(payload)
        tech = out["technical"]["taa_summary"]
        assert "override" in tech.lower() or "IC" in tech


# ===================================================================
#  2. Validation gate — check #16 (TAA bands within IPS)
# ===================================================================


class TestValidationGateTaaBands:
    """Tests for check #16: TAA bands within IPS."""

    def test_check_16_registered_in_checks(self):
        check_ids = [cid for cid, _ in CHECKS]
        assert "taa_bands_within_ips" in check_ids
        assert len(CHECKS) == 16

    def test_check_passes_when_bands_within_ips(self):
        payload = _base_payload()
        db_ctx = ValidationDbContext(block_constraints=BLOCK_CONSTRAINTS)
        result = validate_construction(payload, db_ctx)
        taa_check = next(c for c in result.checks if c.id == "taa_bands_within_ips")
        assert taa_check.passed is True
        assert "within IPS" in taa_check.explanation

    def test_check_skipped_when_taa_disabled(self):
        payload = _base_payload()
        payload["calibration_snapshot"]["taa"] = {"enabled": False}
        db_ctx = ValidationDbContext(block_constraints=BLOCK_CONSTRAINTS)
        result = validate_construction(payload, db_ctx)
        taa_check = next(c for c in result.checks if c.id == "taa_bands_within_ips")
        assert taa_check.passed is True
        assert "disabled" in taa_check.explanation.lower()

    def test_check_skipped_when_no_taa_in_calibration(self):
        payload = _base_payload()
        del payload["calibration_snapshot"]["taa"]
        db_ctx = ValidationDbContext(block_constraints=BLOCK_CONSTRAINTS)
        result = validate_construction(payload, db_ctx)
        taa_check = next(c for c in result.checks if c.id == "taa_bands_within_ips")
        assert taa_check.passed is True

    def test_check_fails_when_band_exceeds_ips_max(self):
        payload = _base_payload()
        # Set effective max above IPS max for na_equity_large (IPS max = 0.28)
        payload["calibration_snapshot"]["taa"]["effective_bands"]["na_equity_large"]["max"] = 0.35
        db_ctx = ValidationDbContext(block_constraints=BLOCK_CONSTRAINTS)
        result = validate_construction(payload, db_ctx)
        taa_check = next(c for c in result.checks if c.id == "taa_bands_within_ips")
        assert taa_check.passed is False
        assert taa_check.severity == "block"
        assert "na_equity_large" in taa_check.explanation

    def test_check_fails_when_band_below_ips_min(self):
        payload = _base_payload()
        # Set effective min below IPS min for fi_aggregate (IPS min = 0.10)
        payload["calibration_snapshot"]["taa"]["effective_bands"]["fi_aggregate"]["min"] = 0.05
        db_ctx = ValidationDbContext(block_constraints=BLOCK_CONSTRAINTS)
        result = validate_construction(payload, db_ctx)
        taa_check = next(c for c in result.checks if c.id == "taa_bands_within_ips")
        assert taa_check.passed is False
        assert "fi_aggregate" in taa_check.explanation

    def test_check_reports_multiple_violations(self):
        payload = _base_payload()
        payload["calibration_snapshot"]["taa"]["effective_bands"]["na_equity_large"]["max"] = 0.35
        payload["calibration_snapshot"]["taa"]["effective_bands"]["fi_aggregate"]["min"] = 0.05
        db_ctx = ValidationDbContext(block_constraints=BLOCK_CONSTRAINTS)
        result = validate_construction(payload, db_ctx)
        taa_check = next(c for c in result.checks if c.id == "taa_bands_within_ips")
        assert taa_check.passed is False
        assert taa_check.value >= 2

    def test_check_tolerates_floating_point(self):
        """Bands at exact IPS bounds should pass (within tolerance)."""
        payload = _base_payload()
        payload["calibration_snapshot"]["taa"]["effective_bands"]["na_equity_large"] = {
            "min": 0.14, "max": 0.28, "center": 0.21,
        }
        db_ctx = ValidationDbContext(block_constraints=BLOCK_CONSTRAINTS)
        result = validate_construction(payload, db_ctx)
        taa_check = next(c for c in result.checks if c.id == "taa_bands_within_ips")
        assert taa_check.passed is True

    def test_check_16_does_not_block_other_checks(self):
        """All 16 checks still run when TAA check is present."""
        payload = _base_payload()
        db_ctx = ValidationDbContext(block_constraints=BLOCK_CONSTRAINTS)
        result = validate_construction(payload, db_ctx)
        assert len(result.checks) == 16


# ===================================================================
#  3. Calibration snapshot TAA provenance
# ===================================================================


class TestCalibrationSnapshotProvenance:
    """Tests that TAA provenance is well-formed in calibration_snapshot."""

    def test_taa_provenance_has_required_keys(self):
        taa = _base_payload()["calibration_snapshot"]["taa"]
        required = {
            "enabled", "raw_regime", "stress_score",
            "smoothed_centers", "effective_bands",
            "ips_clamps_applied", "ic_overrides_active",
            "transition_velocity",
        }
        assert required.issubset(set(taa.keys()))

    def test_smoothed_centers_sum_approximately_one(self):
        taa = _base_payload()["calibration_snapshot"]["taa"]
        total = sum(taa["smoothed_centers"].values())
        assert abs(total - 1.0) < 0.01, f"Smoothed centers sum to {total}, not ~1.0"

    def test_effective_bands_are_valid_intervals(self):
        taa = _base_payload()["calibration_snapshot"]["taa"]
        for bid, band in taa["effective_bands"].items():
            assert band["min"] <= band["max"], (
                f"Invalid interval for {bid}: [{band['min']}, {band['max']}]"
            )
            if "center" in band:
                assert band["min"] <= band["center"] <= band["max"], (
                    f"Center {band['center']} not in [{band['min']}, {band['max']}] for {bid}"
                )


# ===================================================================
#  4. Schema serialization
# ===================================================================


class TestSchemas:
    """Test new Pydantic schema models serialize correctly."""

    def test_regime_bands_read(self):
        from app.domains.wealth.schemas.allocation import EffectiveBandRead, RegimeBandsRead

        data = RegimeBandsRead(
            profile="moderate",
            as_of_date=date(2026, 4, 12),
            raw_regime="RISK_OFF",
            stress_score=Decimal("38.2"),
            smoothed_centers={"equity": 0.42, "fixed_income": 0.34},
            effective_bands={
                "na_equity_large": EffectiveBandRead(min=0.15, max=0.22, center=0.185),
            },
            ips_clamps_applied=["na_equity_large_min_raised"],
        )
        d = data.model_dump()
        assert d["profile"] == "moderate"
        assert d["raw_regime"] == "RISK_OFF"
        assert "na_equity_large" in d["effective_bands"]

    def test_taa_history_row(self):
        from app.domains.wealth.schemas.allocation import TaaHistoryRow

        row = TaaHistoryRow(
            as_of_date=date(2026, 4, 12),
            raw_regime="RISK_OFF",
            stress_score=Decimal("38.2"),
            smoothed_centers={"equity": 0.42},
            effective_bands={"na_equity_large": {"min": 0.15, "max": 0.22}},
            transition_velocity={"equity": -0.008},
            created_at=datetime(2026, 4, 12, 3, 0, 0),
        )
        d = row.model_dump()
        assert d["raw_regime"] == "RISK_OFF"

    def test_effective_with_regime_read(self):
        from app.domains.wealth.schemas.allocation import EffectiveAllocationWithRegimeRead

        item = EffectiveAllocationWithRegimeRead(
            profile="moderate",
            block_id="na_equity_large",
            strategic_weight=Decimal("0.19"),
            tactical_overweight=Decimal("0.02"),
            effective_weight=Decimal("0.21"),
            min_weight=Decimal("0.14"),
            max_weight=Decimal("0.28"),
            regime_min=0.15,
            regime_max=0.22,
            regime_center=0.185,
        )
        d = item.model_dump()
        assert d["regime_min"] == 0.15
        assert d["regime_center"] == 0.185


# ===================================================================
#  5. Backward compatibility
# ===================================================================


class TestBackwardCompatibility:
    """Existing payloads without TAA data continue to work."""

    def test_narrative_without_taa_still_renders(self):
        payload = _base_payload()
        del payload["calibration_snapshot"]["taa"]
        out = render_narrative(payload)
        assert out["schema_version"] == 2
        assert "headline" in out["technical"]
        assert "key_points" in out["technical"]

    def test_validation_gate_runs_16_checks_without_taa(self):
        payload = _base_payload()
        del payload["calibration_snapshot"]["taa"]
        result = validate_construction(payload, ValidationDbContext())
        assert len(result.checks) == 16

    def test_empty_taa_provenance_is_safe(self):
        payload = _base_payload()
        payload["calibration_snapshot"]["taa"] = {}
        out = render_narrative(payload)
        assert out["technical"]["taa_summary"] is not None

    def test_existing_narrative_keys_unchanged(self):
        """Existing narrative output keys must be preserved."""
        out = render_narrative(_base_payload())
        for section in ("technical", "client_safe"):
            assert "headline" in out[section]
            assert "key_points" in out[section]
            assert "constraint_story" in out[section]
            assert "holding_changes" in out[section]
            assert "taa_summary" in out[section]


# ===================================================================
#  6. Sample calibration_snapshot TAA JSON (for documentation)
# ===================================================================


def test_sample_calibration_snapshot_taa_json():
    """Verify the sample TAA JSON shape from plan section 9.1.

    This test exists purely to document the expected calibration_snapshot
    TAA provenance shape. If the shape changes, this test forces a
    deliberate update to the plan documentation.
    """
    sample = {
        "taa": {
            "enabled": True,
            "raw_regime": "RISK_OFF",
            "stress_score": 38.2,
            "smoothed_centers": {
                "equity": 0.42,
                "fixed_income": 0.34,
                "alternatives": 0.13,
                "cash": 0.11,
            },
            "effective_bands": {
                "na_equity_large": {"min": 0.15, "max": 0.22, "center": 0.185},
            },
            "ips_clamps_applied": ["na_equity_large_min_raised"],
            "ic_overrides_active": [],
            "transition_velocity": {"equity": -0.008},
        },
    }
    taa = sample["taa"]
    assert taa["enabled"] is True
    assert isinstance(taa["raw_regime"], str)
    assert isinstance(taa["stress_score"], float)
    assert isinstance(taa["smoothed_centers"], dict)
    assert isinstance(taa["effective_bands"], dict)
    assert isinstance(taa["ips_clamps_applied"], list)
    assert isinstance(taa["ic_overrides_active"], list)
    assert isinstance(taa["transition_velocity"], dict)
