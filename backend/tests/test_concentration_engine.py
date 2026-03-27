"""Tests for pure-logic functions in ai_engine.portfolio.concentration_engine."""
from __future__ import annotations

from ai_engine.governance.policy_loader import PolicyThresholds, ThresholdEntry
from ai_engine.portfolio.concentration_engine import (
    ConcentrationBucket,
    ConcentrationProfile,
    _build_buckets,
    _check_board_override,
    _compute_hhi,
    _normalize_name,
)


# ───────────────────────────────────────────────────────────────────
#  _compute_hhi
# ───────────────────────────────────────────────────────────────────
class TestComputeHHI:
    def test_equal_weights_two(self) -> None:
        assert _compute_hhi([50.0, 50.0]) == 5000.0

    def test_single_manager(self) -> None:
        assert _compute_hhi([100.0]) == 10000.0

    def test_many_small_weights(self) -> None:
        weights = [10.0] * 10
        result = _compute_hhi(weights)
        assert result == 1000.0

    def test_empty_list(self) -> None:
        assert _compute_hhi([]) == 0.0

    def test_unequal_weights(self) -> None:
        # 70^2 + 20^2 + 10^2 = 4900 + 400 + 100 = 5400
        assert _compute_hhi([70.0, 20.0, 10.0]) == 5400.0

    def test_result_is_rounded(self) -> None:
        result = _compute_hhi([33.33, 33.33, 33.34])
        # 33.33^2 + 33.33^2 + 33.34^2 = 1110.8889 + 1110.8889 + 1111.5556 = 3333.33
        assert result == round(33.33**2 + 33.33**2 + 33.34**2, 2)


# ───────────────────────────────────────────────────────────────────
#  _normalize_name
# ───────────────────────────────────────────────────────────────────
class TestNormalizeName:
    def test_normal_name(self) -> None:
        assert _normalize_name("  Apollo Global ") == "apollo global"

    def test_empty_string(self) -> None:
        assert _normalize_name("") == "unknown"

    def test_none_returns_unknown(self) -> None:
        # The function signature says str, but the body uses `if name`
        # which handles None at runtime.
        assert _normalize_name(None) == "unknown"  # type: ignore[arg-type]

    def test_whitespace_only(self) -> None:
        # "   ".strip().lower() == "" which is falsy, but the guard
        # `if name` checks the original value before strip. "   " is truthy,
        # so it returns "".strip().lower() = "".
        # Actually: `name.strip().lower()` on "   " returns "".
        result = _normalize_name("   ")
        assert result == ""

    def test_already_lowercase(self) -> None:
        assert _normalize_name("blackrock") == "blackrock"

    def test_mixed_case(self) -> None:
        assert _normalize_name("KKR Capital") == "kkr capital"


# ───────────────────────────────────────────────────────────────────
#  _build_buckets
# ───────────────────────────────────────────────────────────────────
class TestBuildBuckets:
    def test_two_exposures_no_breach(self) -> None:
        exposures = {"mgr_a": 300_000.0, "mgr_b": 700_000.0}
        buckets, any_breach = _build_buckets(exposures, 1_000_000.0, 80.0, "DEFAULT")
        assert any_breach is False
        assert len(buckets) == 2
        # Sorted descending by exposure
        assert buckets[0].name == "mgr_b"
        assert buckets[0].weight_pct == 70.0
        assert buckets[1].name == "mgr_a"
        assert buckets[1].weight_pct == 30.0

    def test_one_exposure_exceeds_limit(self) -> None:
        exposures = {"mgr_a": 400_000.0, "mgr_b": 600_000.0}
        buckets, any_breach = _build_buckets(exposures, 1_000_000.0, 50.0, "IMA")
        assert any_breach is True
        # mgr_b has 60% > 50% limit
        assert buckets[0].name == "mgr_b"
        assert buckets[0].breaches_limit is True
        assert buckets[0].limit_pct == 50.0
        assert buckets[0].limit_source == "IMA"
        # mgr_a has 40% <= 50% limit
        assert buckets[1].breaches_limit is False

    def test_sorted_by_exposure_descending(self) -> None:
        exposures = {"small": 100.0, "large": 500.0, "medium": 300.0}
        buckets, _ = _build_buckets(exposures, 900.0, 99.0, "DEFAULT")
        assert [b.name for b in buckets] == ["large", "medium", "small"]

    def test_empty_exposures(self) -> None:
        buckets, any_breach = _build_buckets({}, 1_000_000.0, 35.0, "DEFAULT")
        assert buckets == []
        assert any_breach is False

    def test_zero_total_gives_zero_weights(self) -> None:
        exposures = {"mgr_a": 500.0, "mgr_b": 500.0}
        buckets, any_breach = _build_buckets(exposures, 0.0, 35.0, "DEFAULT")
        assert len(buckets) == 2
        assert all(b.weight_pct == 0.0 for b in buckets)
        assert any_breach is False

    def test_exposure_usd_is_rounded(self) -> None:
        exposures = {"mgr_a": 333.339}
        buckets, _ = _build_buckets(exposures, 1000.0, 99.0, "DEFAULT")
        assert buckets[0].exposure_usd == 333.34

    def test_breach_at_boundary(self) -> None:
        # Exactly at limit should NOT breach (breach is strictly >)
        exposures = {"mgr_a": 350_000.0}
        buckets, any_breach = _build_buckets(exposures, 1_000_000.0, 35.0, "DEFAULT")
        assert any_breach is False
        assert buckets[0].breaches_limit is False


# ───────────────────────────────────────────────────────────────────
#  _check_board_override
# ───────────────────────────────────────────────────────────────────
class TestCheckBoardOverride:
    @staticmethod
    def _make_policy(**overrides: object) -> PolicyThresholds:
        return PolicyThresholds(**overrides)  # type: ignore[arg-type]

    def test_no_breaches(self) -> None:
        profile = ConcentrationProfile()
        policy = self._make_policy()
        _check_board_override(profile, policy)
        assert profile.requires_board_override is False
        assert profile.board_override_reasons == []

    def test_manager_breach_triggers_override(self) -> None:
        profile = ConcentrationProfile(manager_limit_breached=True)
        policy = self._make_policy()
        _check_board_override(profile, policy)
        assert profile.requires_board_override is True
        assert any("single_manager" in r for r in profile.board_override_reasons)

    def test_multiple_breaches_multiple_reasons(self) -> None:
        profile = ConcentrationProfile(
            manager_limit_breached=True,
            hard_lockup_breached=True,
        )
        policy = self._make_policy()
        _check_board_override(profile, policy)
        assert profile.requires_board_override is True
        assert len(profile.board_override_reasons) >= 2
        reasons_text = " ".join(profile.board_override_reasons)
        assert "single_manager" in reasons_text
        assert "hard_lockup" in reasons_text

    def test_safety_net_manager_breach_without_trigger_config(self) -> None:
        """Even if board_override_triggers does not list single_manager,
        the safety net should still fire for manager breach.
        """
        profile = ConcentrationProfile(manager_limit_breached=True)
        policy = self._make_policy(
            board_override_triggers=ThresholdEntry(
                value=["hard_lockup"],  # deliberately omits single_manager
                source="test",
            ),
        )
        _check_board_override(profile, policy)
        assert profile.requires_board_override is True
        assert any("single_manager" in r for r in profile.board_override_reasons)

    def test_sector_breach_with_trigger(self) -> None:
        profile = ConcentrationProfile(sector_limit_breached=True)
        policy = self._make_policy(
            board_override_triggers=ThresholdEntry(
                value=["single_sector"],
                source="risk-policy-index",
            ),
        )
        _check_board_override(profile, policy)
        assert profile.requires_board_override is True
        assert any("single_sector" in r for r in profile.board_override_reasons)

    def test_geography_breach_not_in_triggers(self) -> None:
        """Geography breach should NOT trigger override if not in trigger list
        and it is not the safety-net case (manager).
        """
        profile = ConcentrationProfile(geography_limit_breached=True)
        policy = self._make_policy(
            board_override_triggers=ThresholdEntry(
                value=["single_manager"],
                source="test",
            ),
        )
        _check_board_override(profile, policy)
        assert profile.requires_board_override is False

    def test_modifies_profile_in_place(self) -> None:
        profile = ConcentrationProfile(manager_limit_breached=True)
        policy = self._make_policy()
        _check_board_override(profile, policy)
        # Verify modification happened on the same object
        assert profile.requires_board_override is True
        assert len(profile.board_override_reasons) > 0


# ───────────────────────────────────────────────────────────────────
#  ConcentrationProfile
# ───────────────────────────────────────────────────────────────────
class TestConcentrationProfile:
    def test_total_nav_usd_equals_total_exposure(self) -> None:
        profile = ConcentrationProfile(total_exposure_usd=5_000_000.0)
        assert profile.total_nav_usd == 5_000_000.0

    def test_to_dict_has_all_expected_keys(self) -> None:
        profile = ConcentrationProfile()
        d = profile.to_dict()
        expected_keys = {
            "total_exposure_usd",
            "total_nav_usd",
            "investment_count",
            "excluded_count",
            "metrics_status",
            "manager_buckets",
            "manager_hhi",
            "manager_limit_breached",
            "sector_buckets",
            "sector_hhi",
            "sector_limit_breached",
            "geography_buckets",
            "geography_hhi",
            "geography_limit_breached",
            "top3_weight_pct",
            "top3_limit_breached",
            "non_usd_unhedged_pct",
            "non_usd_unhedged_breached",
            "hard_lockup_pct",
            "hard_lockup_breached",
            "any_limit_breached",
            "requires_board_override",
            "board_override_reasons",
            "policy_summary",
        }
        assert set(d.keys()) == expected_keys

    def test_default_values(self) -> None:
        profile = ConcentrationProfile()
        assert profile.total_exposure_usd == 0.0
        assert profile.investment_count == 0
        assert profile.excluded_count == 0
        assert profile.metrics_status == "COMPLETE"
        assert profile.manager_buckets == []
        assert profile.manager_hhi == 0.0
        assert profile.manager_limit_breached is False
        assert profile.sector_buckets == []
        assert profile.sector_limit_breached is False
        assert profile.geography_buckets == []
        assert profile.geography_limit_breached is False
        assert profile.top3_weight_pct == 0.0
        assert profile.top3_limit_breached is False
        assert profile.non_usd_unhedged_pct is None
        assert profile.non_usd_unhedged_breached is False
        assert profile.hard_lockup_pct is None
        assert profile.hard_lockup_breached is False
        assert profile.any_limit_breached is False
        assert profile.requires_board_override is False
        assert profile.board_override_reasons == []
        assert profile.policy_summary == {}

    def test_to_dict_serializes_buckets(self) -> None:
        bucket = ConcentrationBucket(
            name="apollo",
            exposure_usd=1_000_000.0,
            weight_pct=50.0,
            breaches_limit=True,
            limit_pct=35.0,
            limit_source="IMA",
        )
        profile = ConcentrationProfile(manager_buckets=[bucket])
        d = profile.to_dict()
        assert len(d["manager_buckets"]) == 1
        b = d["manager_buckets"][0]
        assert b["name"] == "apollo"
        assert b["exposure_usd"] == 1_000_000.0
        assert b["weight_pct"] == 50.0
        assert b["breaches_limit"] is True
        assert b["limit_pct"] == 35.0
        assert b["limit_source"] == "IMA"

    def test_to_dict_total_nav_usd_mirrors_exposure(self) -> None:
        profile = ConcentrationProfile(total_exposure_usd=42.0)
        d = profile.to_dict()
        assert d["total_nav_usd"] == 42.0
        assert d["total_exposure_usd"] == 42.0


# ───────────────────────────────────────────────────────────────────
#  ConcentrationBucket
# ───────────────────────────────────────────────────────────────────
class TestConcentrationBucket:
    def test_defaults(self) -> None:
        bucket = ConcentrationBucket(
            name="test", exposure_usd=100.0, weight_pct=10.0,
        )
        assert bucket.breaches_limit is False
        assert bucket.limit_pct == 0.0
        assert bucket.limit_source == "DEFAULT"

    def test_all_fields(self) -> None:
        bucket = ConcentrationBucket(
            name="kkr",
            exposure_usd=500_000.0,
            weight_pct=40.0,
            breaches_limit=True,
            limit_pct=35.0,
            limit_source="fund-constitution-index",
        )
        assert bucket.name == "kkr"
        assert bucket.exposure_usd == 500_000.0
        assert bucket.weight_pct == 40.0
        assert bucket.breaches_limit is True
        assert bucket.limit_pct == 35.0
        assert bucket.limit_source == "fund-constitution-index"
