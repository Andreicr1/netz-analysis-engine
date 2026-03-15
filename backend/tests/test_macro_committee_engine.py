"""Tests for vertical_engines/wealth/macro_committee_engine.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from vertical_engines.wealth.macro_committee_engine import (
    WeeklyReportData,
    build_report_json,
    check_emergency_cooldown,
    generate_weekly_report,
)


def _make_snapshot(
    as_of: str = "2026-03-15",
    us_score: float = 55.0,
    europe_score: float = 50.0,
) -> dict:
    return {
        "version": 1,
        "as_of_date": as_of,
        "regions": {
            "US": {
                "composite_score": us_score,
                "coverage": 0.85,
                "dimensions": {},
                "data_freshness": {
                    "VIXCLS": {"last_date": "2026-03-14", "days_stale": 1, "weight": 1.0, "status": "fresh"},
                },
            },
            "EUROPE": {
                "composite_score": europe_score,
                "coverage": 0.70,
                "dimensions": {},
                "data_freshness": {},
            },
            "ASIA": {
                "composite_score": 50.0,
                "coverage": 0.60,
                "dimensions": {},
                "data_freshness": {
                    "JPNRGDPEXP": {"last_date": "2025-12-01", "days_stale": 200, "weight": 0.0, "status": "stale"},
                },
            },
            "EM": {
                "composite_score": 45.0,
                "coverage": 0.55,
                "dimensions": {},
                "data_freshness": {},
            },
        },
        "global_indicators": {
            "geopolitical_risk_score": 60.0,
            "energy_stress": 55.0,
            "commodity_stress": 45.0,
            "usd_strength": 65.0,
        },
    }


class TestGenerateWeeklyReport:
    def test_first_run_no_previous(self):
        current = _make_snapshot()
        report = generate_weekly_report(current, None)
        assert isinstance(report, WeeklyReportData)
        assert not report.has_material_changes
        assert len(report.score_deltas) == 0
        assert "JPNRGDPEXP" in report.staleness_alerts

    def test_no_material_changes(self):
        current = _make_snapshot(us_score=55.0, europe_score=50.0)
        previous = _make_snapshot(us_score=54.0, europe_score=49.5)
        report = generate_weekly_report(current, previous)
        assert not report.has_material_changes
        assert len(report.score_deltas) == 4

    def test_flagged_score_delta(self):
        current = _make_snapshot(us_score=60.0)
        previous = _make_snapshot(us_score=50.0)  # delta = +10
        report = generate_weekly_report(current, previous)
        us_delta = next(sd for sd in report.score_deltas if sd.region == "US")
        assert us_delta.flagged
        assert us_delta.delta == 10.0
        assert report.has_material_changes

    def test_staleness_alerts_collected(self):
        current = _make_snapshot()
        previous = _make_snapshot()
        report = generate_weekly_report(current, previous)
        assert "JPNRGDPEXP" in report.staleness_alerts

    def test_global_indicators_delta(self):
        current = _make_snapshot()
        previous = _make_snapshot()
        # Same snapshots → zero deltas
        report = generate_weekly_report(current, previous)
        assert report.global_indicators_delta["geopolitical_risk_score"] == 0.0

    def test_custom_threshold(self):
        current = _make_snapshot(us_score=53.0)
        previous = _make_snapshot(us_score=50.0)
        # Default threshold 5.0 → not flagged
        report_default = generate_weekly_report(current, previous)
        us_default = next(sd for sd in report_default.score_deltas if sd.region == "US")
        assert not us_default.flagged

        # Custom threshold 2.0 → flagged
        report_custom = generate_weekly_report(current, previous, score_delta_threshold=2.0)
        us_custom = next(sd for sd in report_custom.score_deltas if sd.region == "US")
        assert us_custom.flagged


class TestBuildReportJson:
    def test_serializable(self):
        import json

        report = generate_weekly_report(_make_snapshot(), _make_snapshot())
        report_json = build_report_json(report)
        # Should not raise
        serialized = json.dumps(report_json)
        assert '"type": "weekly"' in serialized

    def test_emergency_type(self):
        report = generate_weekly_report(_make_snapshot(), None)
        report_json = build_report_json(report, regime_data={"global": "CRISIS"})
        assert report_json["type"] == "emergency"


class TestEmergencyCooldown:
    def test_no_previous_allows(self):
        assert check_emergency_cooldown(None) is True

    def test_within_cooldown_blocks(self):
        recent = datetime.now(timezone.utc) - timedelta(hours=12)
        assert check_emergency_cooldown(recent, cooldown_hours=24) is False

    def test_after_cooldown_allows(self):
        old = datetime.now(timezone.utc) - timedelta(hours=25)
        assert check_emergency_cooldown(old, cooldown_hours=24) is True

    def test_naive_datetime_handled(self):
        old = datetime.now() - timedelta(hours=25)  # naive
        assert check_emergency_cooldown(old, cooldown_hours=24) is True
