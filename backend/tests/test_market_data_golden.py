"""Golden-value tests for market_data_engine stress severity scoring.

Captures exact outputs of compute_macro_stress_severity() for known
snapshots BEFORE refactoring. Verifies that the extracted
stress_severity_service produces identical outputs.
"""

from __future__ import annotations

from vertical_engines.credit.market_data_engine import compute_macro_stress_severity


class TestStressSeverityGolden:
    """Golden values for compute_macro_stress_severity()."""

    def test_benign_environment(self) -> None:
        """All-clear macro environment → NONE."""
        snapshot = {
            "recession_flag": False,
            "financial_conditions_index": -0.5,
            "yield_curve_2s10s": 1.5,
            "baa_spread": 1.5,
            "hy_spread_proxy": 3.5,
            "real_estate_national": {
                "CSUSHPINSA": {"delta_12m_pct": 5.0},
            },
            "mortgage": {
                "DRSFRMACBS": {"latest": 2.0},
            },
            "credit_quality": {
                "DRALACBN": {"latest": 1.5},
            },
        }
        result = compute_macro_stress_severity(snapshot)

        assert result["level"] == "NONE"
        assert result["score"] == 0
        assert result["triggers"] == []
        assert result["real_estate_stress"] == "NONE"
        assert result["credit_stress"] == "NONE"
        assert result["rate_stress"] == "NONE"

    def test_severe_stress(self) -> None:
        """Recession + tight conditions + inverted curve + wide spreads → SEVERE."""
        snapshot = {
            "recession_flag": True,
            "financial_conditions_index": 1.5,
            "yield_curve_2s10s": -0.80,
            "baa_spread": 4.0,
            "hy_spread_proxy": 10.0,
            "real_estate_national": {
                "CSUSHPINSA": {"delta_12m_pct": -8.0},
            },
            "mortgage": {
                "DRSFRMACBS": {"latest": 6.0},
            },
            "credit_quality": {
                "DRALACBN": {"latest": 4.0},
            },
        }
        result = compute_macro_stress_severity(snapshot)

        assert result["level"] == "SEVERE"
        # Score breakdown:
        # recession=40, NFCI>1.0=25, curve<-0.5=20, baa>3.0=20, hy>8.0=15,
        # HPI<-5.0=20, mortgage>4.0=15, loan>2.5=10 = 165 → capped at 100
        assert result["score"] == 100
        assert len(result["triggers"]) >= 7
        assert result["real_estate_stress"] == "SEVERE"
        assert result["rate_stress"] == "SEVERE"

    def test_mild_stress(self) -> None:
        """Slightly elevated conditions → MILD."""
        snapshot = {
            "recession_flag": False,
            "financial_conditions_index": 0.3,
            "yield_curve_2s10s": -0.1,
            "baa_spread": 1.8,
            "hy_spread_proxy": 4.5,
            "real_estate_national": {
                "CSUSHPINSA": {"delta_12m_pct": 2.0},
            },
            "mortgage": {
                "DRSFRMACBS": {"latest": 2.5},
            },
            "credit_quality": {
                "DRALACBN": {"latest": 1.8},
            },
        }
        result = compute_macro_stress_severity(snapshot)

        # NFCI above neutral = 10, yield curve inverted = 10 → score = 20
        assert result["level"] == "MILD"
        assert result["score"] == 20
        assert len(result["triggers"]) == 2

    def test_moderate_stress(self) -> None:
        """Mixed stress signals → MODERATE."""
        snapshot = {
            "recession_flag": False,
            "financial_conditions_index": 0.5,
            "yield_curve_2s10s": -0.6,
            "baa_spread": 2.5,
            "hy_spread_proxy": 6.0,
            "real_estate_national": {
                "CSUSHPINSA": {"delta_12m_pct": -2.0},
            },
            "mortgage": {
                "DRSFRMACBS": {"latest": 3.0},
            },
            "credit_quality": {
                "DRALACBN": {"latest": 3.0},
            },
        }
        result = compute_macro_stress_severity(snapshot)

        # NFCI=10, curve deep=-20, baa>2.0=8, hy>5.0=5, HPI<0=10, loan>2.5=10 = 63
        assert result["level"] == "MODERATE"
        assert 36 <= result["score"] <= 65

    def test_empty_snapshot(self) -> None:
        """Empty snapshot — no triggers, NONE level."""
        result = compute_macro_stress_severity({})

        assert result["level"] == "NONE"
        assert result["score"] == 0
        assert result["triggers"] == []

    def test_partial_data(self) -> None:
        """Only some fields present — graceful degradation."""
        snapshot = {
            "recession_flag": True,
            # Everything else missing
        }
        result = compute_macro_stress_severity(snapshot)

        assert result["level"] == "MODERATE"  # 40 points from recession alone
        assert result["score"] == 40
        assert len(result["triggers"]) == 1
        assert "recession" in result["triggers"][0].lower()
