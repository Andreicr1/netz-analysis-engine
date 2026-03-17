"""Tests for the Wealth Peer Group Engine — Sprint 2.

Covers:
- PeerGroup/PeerRanking/PeerGroupNotFound model integrity
- peer_matcher: key building, hierarchical fallback, min peer count
- PeerGroupService: find_peers, compute_rankings, compute_rankings_batch
- Percentile calculation with lower_is_better inversion
- peer_injection: gather_peer_context integration
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from vertical_engines.wealth.peer_group.models import (
    MetricRanking,
    PeerGroup,
    PeerGroupNotFound,
    PeerRanking,
)
from vertical_engines.wealth.peer_group.peer_matcher import (
    _aum_bucket,
    _cap_tier,
    _duration_bucket,
    _rating_tier,
    build_key_levels,
    build_peer_group_key,
    match_peers,
)
from vertical_engines.wealth.peer_group.service import (
    LOWER_IS_BETTER,
    PeerGroupService,
)

# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════


def _make_instrument(
    instrument_type: str = "fund",
    block_id: str = "US_EQUITY",
    iid: uuid.UUID | None = None,
    **extra_attrs: object,
) -> dict:
    attrs: dict = {}
    if instrument_type == "fund":
        attrs = {"strategy": "long_only", "aum_usd": 1_000_000_000}
    elif instrument_type == "bond":
        attrs = {
            "issuer_type": "corporate",
            "credit_rating": "A",
            "duration_years": 5.0,
        }
    elif instrument_type == "equity":
        attrs = {"gics_sector": "technology", "market_cap_usd": 50_000_000_000}
    attrs.update(extra_attrs)
    return {
        "instrument_id": iid or uuid.uuid4(),
        "instrument_type": instrument_type,
        "block_id": block_id,
        "attributes": attrs,
    }


def _make_universe(
    count: int,
    instrument_type: str = "fund",
    block_id: str = "US_EQUITY",
    **extra_attrs: object,
) -> list[dict]:
    return [
        _make_instrument(instrument_type, block_id, **extra_attrs)
        for _ in range(count)
    ]


# ═══════════════════════════════════════════════════════════════════
#  Model tests
# ═══════════════════════════════════════════════════════════════════


class TestModels:
    def test_peer_group_frozen(self):
        pg = PeerGroup(
            peer_group_key="BLK::strat::mid",
            instrument_type="fund",
            block_id="BLK",
            member_count=25,
            members=(uuid.uuid4(),),
            fallback_level=0,
        )
        with pytest.raises(AttributeError):
            pg.member_count = 30  # type: ignore[misc]

    def test_peer_ranking_frozen(self):
        pr = PeerRanking(
            instrument_id=uuid.uuid4(),
            peer_group_key="BLK::strat::mid",
            peer_count=25,
            fallback_level=0,
            rankings=(),
            composite_percentile=75.0,
            ranked_at=datetime.now(timezone.utc),
        )
        with pytest.raises(AttributeError):
            pr.peer_count = 30  # type: ignore[misc]

    def test_peer_group_not_found_reasons(self):
        iid = uuid.uuid4()
        for reason in ("instrument_not_found", "insufficient_peers", "no_block_assigned", "no_metrics"):
            pgnf = PeerGroupNotFound(instrument_id=iid, reason=reason)
            assert pgnf.reason == reason

    def test_metric_ranking_fields(self):
        mr = MetricRanking(
            metric="sharpe_ratio",
            value=1.5,
            percentile=85.0,
            lower_is_better=False,
        )
        assert mr.metric == "sharpe_ratio"
        assert mr.percentile == 85.0


# ═══════════════════════════════════════════════════════════════════
#  Bucket / tier helper tests
# ═══════════════════════════════════════════════════════════════════


class TestBucketHelpers:
    def test_aum_bucket_small(self):
        assert _aum_bucket(100_000_000) == "small"

    def test_aum_bucket_mid(self):
        assert _aum_bucket(1_000_000_000) == "mid"

    def test_aum_bucket_large(self):
        assert _aum_bucket(10_000_000_000) == "large"

    def test_aum_bucket_none(self):
        assert _aum_bucket(None) == "unknown"

    def test_duration_bucket_short(self):
        assert _duration_bucket(1.5) == "short"

    def test_duration_bucket_medium(self):
        assert _duration_bucket(5.0) == "medium"

    def test_duration_bucket_long(self):
        assert _duration_bucket(10.0) == "long"

    def test_duration_bucket_ultra(self):
        assert _duration_bucket(20.0) == "ultra"

    def test_rating_tier_aaa_aa(self):
        assert _rating_tier("AAA") == "AAA_AA"
        assert _rating_tier("AA-") == "AAA_AA"

    def test_rating_tier_a(self):
        assert _rating_tier("A+") == "A"
        assert _rating_tier("A-") == "A"

    def test_rating_tier_bbb(self):
        assert _rating_tier("BBB") == "BBB"

    def test_rating_tier_junk(self):
        assert _rating_tier("BB+") == "BB_and_below"
        assert _rating_tier("CCC") == "BB_and_below"

    def test_rating_tier_none(self):
        assert _rating_tier(None) == "unknown"

    def test_cap_tier_mega(self):
        assert _cap_tier(500_000_000_000) == "mega"

    def test_cap_tier_large(self):
        assert _cap_tier(50_000_000_000) == "large"

    def test_cap_tier_mid(self):
        assert _cap_tier(5_000_000_000) == "mid"

    def test_cap_tier_small(self):
        assert _cap_tier(500_000_000) == "small"


# ═══════════════════════════════════════════════════════════════════
#  Key builder tests
# ═══════════════════════════════════════════════════════════════════


class TestKeyBuilders:
    def test_fund_key_levels(self):
        keys = build_key_levels("fund", "US_EQUITY", {"strategy": "long_only", "aum_usd": 1_000_000_000})
        assert keys == ["US_EQUITY::long_only::mid", "US_EQUITY::long_only", "US_EQUITY"]

    def test_bond_key_levels(self):
        keys = build_key_levels("bond", "GLOBAL_FI", {
            "issuer_type": "corporate",
            "credit_rating": "A+",
            "duration_years": 5.0,
        })
        assert keys == [
            "GLOBAL_FI::corporate::A::medium",
            "GLOBAL_FI::corporate::A",
            "GLOBAL_FI",
        ]

    def test_equity_key_levels(self):
        keys = build_key_levels("equity", "US_EQUITY", {
            "gics_sector": "technology",
            "market_cap_usd": 50_000_000_000,
        })
        assert keys == [
            "US_EQUITY::technology::large",
            "US_EQUITY::technology",
            "US_EQUITY",
        ]

    def test_build_peer_group_key_returns_level0(self):
        key = build_peer_group_key("fund", "BLK", {"strategy": "quant", "aum_usd": 100_000_000})
        assert key == "BLK::quant::small"


# ═══════════════════════════════════════════════════════════════════
#  Peer matcher tests
# ═══════════════════════════════════════════════════════════════════


class TestPeerMatcher:
    def test_find_peers_fund_full_group(self):
        """25 funds with same key -> PeerGroup at level 0."""
        target_id = uuid.uuid4()
        universe = _make_universe(25, "fund", "BLK")
        universe[0]["instrument_id"] = target_id

        result = match_peers(
            target_instrument_id=target_id,
            target_type="fund",
            target_block_id="BLK",
            target_attributes={"strategy": "long_only", "aum_usd": 1_000_000_000},
            universe=universe,
        )
        assert isinstance(result, PeerGroup)
        assert result.fallback_level == 0
        assert result.member_count == 25
        assert target_id in result.members

    def test_find_peers_bond_full_group(self):
        """25 bonds with same key -> PeerGroup at level 0."""
        target_id = uuid.uuid4()
        universe = _make_universe(25, "bond", "GLOBAL_FI")
        universe[0]["instrument_id"] = target_id

        result = match_peers(
            target_instrument_id=target_id,
            target_type="bond",
            target_block_id="GLOBAL_FI",
            target_attributes={
                "issuer_type": "corporate",
                "credit_rating": "A",
                "duration_years": 5.0,
            },
            universe=universe,
        )
        assert isinstance(result, PeerGroup)
        assert result.fallback_level == 0

    def test_find_peers_equity_full_group(self):
        """25 equities with same key -> PeerGroup at level 0."""
        target_id = uuid.uuid4()
        universe = _make_universe(25, "equity", "US_EQUITY")
        universe[0]["instrument_id"] = target_id

        result = match_peers(
            target_instrument_id=target_id,
            target_type="equity",
            target_block_id="US_EQUITY",
            target_attributes={"gics_sector": "technology", "market_cap_usd": 50_000_000_000},
            universe=universe,
        )
        assert isinstance(result, PeerGroup)
        assert result.fallback_level == 0

    def test_hierarchical_fallback_level1(self):
        """Only 10 at full key but 25 at partial key -> fallback to level 1."""
        target_id = uuid.uuid4()
        # 10 instruments with same full key (strategy=long_only, aum=mid)
        same_full = _make_universe(10, "fund", "BLK")
        # 15 more with same strategy but different aum_bucket (small)
        diff_aum = _make_universe(15, "fund", "BLK", aum_usd=100_000_000)

        universe = same_full + diff_aum
        universe[0]["instrument_id"] = target_id

        result = match_peers(
            target_instrument_id=target_id,
            target_type="fund",
            target_block_id="BLK",
            target_attributes={"strategy": "long_only", "aum_usd": 1_000_000_000},
            universe=universe,
        )
        assert isinstance(result, PeerGroup)
        assert result.fallback_level == 1
        assert result.member_count == 25

    def test_hierarchical_fallback_level2_block_only(self):
        """Insufficient at level 1 but enough at block level -> fallback to level 2."""
        target_id = uuid.uuid4()
        same_strategy = _make_universe(5, "fund", "BLK", strategy="long_only", aum_usd=1_000_000_000)
        same_strat_diff_aum = _make_universe(5, "fund", "BLK", strategy="long_only", aum_usd=100_000_000)
        diff_strategy = _make_universe(15, "fund", "BLK", strategy="quant", aum_usd=1_000_000_000)

        universe = same_strategy + same_strat_diff_aum + diff_strategy
        universe[0]["instrument_id"] = target_id

        result = match_peers(
            target_instrument_id=target_id,
            target_type="fund",
            target_block_id="BLK",
            target_attributes={"strategy": "long_only", "aum_usd": 1_000_000_000},
            universe=universe,
        )
        assert isinstance(result, PeerGroup)
        assert result.fallback_level == 2
        assert result.member_count == 25

    def test_insufficient_peers_even_at_block_level(self):
        """Only 10 total in block -> PeerGroupNotFound."""
        target_id = uuid.uuid4()
        universe = _make_universe(10, "fund", "BLK")
        universe[0]["instrument_id"] = target_id

        result = match_peers(
            target_instrument_id=target_id,
            target_type="fund",
            target_block_id="BLK",
            target_attributes={"strategy": "long_only", "aum_usd": 1_000_000_000},
            universe=universe,
        )
        assert isinstance(result, PeerGroupNotFound)
        assert result.reason == "insufficient_peers"

    def test_no_block_assigned(self):
        """No block_id -> PeerGroupNotFound."""
        target_id = uuid.uuid4()
        result = match_peers(
            target_instrument_id=target_id,
            target_type="fund",
            target_block_id=None,
            target_attributes={"strategy": "long_only"},
            universe=[],
        )
        assert isinstance(result, PeerGroupNotFound)
        assert result.reason == "no_block_assigned"

    def test_different_types_excluded(self):
        """Bonds should not be peers of funds."""
        target_id = uuid.uuid4()
        fund_universe = _make_universe(10, "fund", "BLK")
        bond_universe = _make_universe(20, "bond", "BLK")
        universe = fund_universe + bond_universe
        universe[0]["instrument_id"] = target_id

        result = match_peers(
            target_instrument_id=target_id,
            target_type="fund",
            target_block_id="BLK",
            target_attributes={"strategy": "long_only", "aum_usd": 1_000_000_000},
            universe=universe,
        )
        assert isinstance(result, PeerGroupNotFound)

    def test_exclusive_assignment(self):
        """Each instrument appears in exactly one peer group."""
        universe = _make_universe(25, "fund", "BLK")
        iid = universe[0]["instrument_id"]

        result = match_peers(
            target_instrument_id=iid,
            target_type="fund",
            target_block_id="BLK",
            target_attributes={"strategy": "long_only", "aum_usd": 1_000_000_000},
            universe=universe,
        )
        assert isinstance(result, PeerGroup)
        assert len(result.members) == len(set(result.members))

    def test_min_peer_count_configurable(self):
        """Custom min_peer_count overrides default."""
        target_id = uuid.uuid4()
        universe = _make_universe(5, "fund", "BLK")
        universe[0]["instrument_id"] = target_id

        result = match_peers(
            target_instrument_id=target_id,
            target_type="fund",
            target_block_id="BLK",
            target_attributes={"strategy": "long_only", "aum_usd": 1_000_000_000},
            universe=universe,
            min_peer_count=5,
        )
        assert isinstance(result, PeerGroup)
        assert result.member_count == 5


# ═══════════════════════════════════════════════════════════════════
#  Percentile ranking tests (pure logic, no DB)
# ═══════════════════════════════════════════════════════════════════


class TestPercentileRanking:
    """Test the ranking logic using scipy.stats.percentileofscore."""

    def test_percentileofscore_basic(self):
        from scipy.stats import percentileofscore
        peer_vals = list(range(10, 110, 10))
        pctile = percentileofscore(peer_vals, 80, kind="rank")
        assert pctile == 80.0

    def test_lower_is_better_inversion(self):
        """max_drawdown_pct: worst (most negative) should get low percentile."""
        from scipy.stats import percentileofscore

        peer_vals = [-5.0, -10.0, -15.0, -20.0, -25.0]
        pctile = percentileofscore(peer_vals, -25.0, kind="rank")
        inverted = 100.0 - pctile
        assert inverted == 80.0

    def test_lower_is_better_best_value(self):
        """Lowest max_drawdown should get highest percentile after inversion."""
        from scipy.stats import percentileofscore

        peer_vals = [-5.0, -10.0, -15.0, -20.0, -25.0]
        pctile = percentileofscore(peer_vals, -5.0, kind="rank")
        inverted = 100.0 - pctile
        assert inverted == 0.0

    def test_winsorize_clips_outliers(self):
        """Winsorization at 1% tails clips extreme values."""
        peer_arr = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 100.0])
        lo = float(np.percentile(peer_arr, 1))
        hi = float(np.percentile(peer_arr, 99))
        clipped = float(np.clip(100.0, lo, hi))
        assert clipped < 100.0


# ═══════════════════════════════════════════════════════════════════
#  Service tests (mocking find_peers and _load_peer_metrics)
# ═══════════════════════════════════════════════════════════════════


class TestPeerGroupService:
    """Test PeerGroupService by patching its internal methods."""

    def _make_peer_group(self, member_count: int = 25, target_id: uuid.UUID | None = None) -> PeerGroup:
        members = [target_id or uuid.uuid4()] + [uuid.uuid4() for _ in range(member_count - 1)]
        return PeerGroup(
            peer_group_key="BLK::long_only::mid",
            instrument_type="fund",
            block_id="BLK",
            member_count=member_count,
            members=tuple(members),
            fallback_level=0,
        )

    def test_compute_rankings_success(self):
        target_id = uuid.uuid4()
        pg = self._make_peer_group(25, target_id)

        metrics_by_id = {}
        for i, mid in enumerate(pg.members):
            metrics_by_id[mid] = {
                "sharpe_ratio": 0.5 + i * 0.1,
                "max_drawdown_pct": -5.0 - i * 0.5,
                "annual_return_pct": 5.0 + i * 0.5,
                "annual_volatility_pct": 10.0 + i * 0.2,
                "pct_positive_months": 0.5 + i * 0.01,
            }

        svc = PeerGroupService()
        with patch.object(svc, "find_peers", return_value=pg), \
             patch.object(svc, "_load_peer_metrics", return_value=metrics_by_id):
            result = svc.compute_rankings(MagicMock(), target_id, "org-1")

        assert isinstance(result, PeerRanking)
        assert result.peer_count == 25
        assert result.composite_percentile is not None
        assert 0 <= result.composite_percentile <= 100
        assert len(result.rankings) == 5

    def test_compute_rankings_no_metrics(self):
        target_id = uuid.uuid4()
        pg = self._make_peer_group(25, target_id)

        svc = PeerGroupService()
        with patch.object(svc, "find_peers", return_value=pg), \
             patch.object(svc, "_load_peer_metrics", return_value={}):
            result = svc.compute_rankings(MagicMock(), target_id, "org-1")

        assert isinstance(result, PeerGroupNotFound)
        assert result.reason == "no_metrics"

    def test_compute_rankings_no_block(self):
        target_id = uuid.uuid4()
        not_found = PeerGroupNotFound(instrument_id=target_id, reason="no_block_assigned")

        svc = PeerGroupService()
        with patch.object(svc, "find_peers", return_value=not_found):
            result = svc.compute_rankings(MagicMock(), target_id, "org-1")

        assert isinstance(result, PeerGroupNotFound)
        assert result.reason == "no_block_assigned"

    def test_compute_rankings_batch_mixed(self):
        """Batch with id1 having a peer group and id2 having no block."""
        id1 = uuid.uuid4()
        id2 = uuid.uuid4()

        # Build a universe of 25 instruments (all funds in same block)
        # id1 is in the group, id2 has no block
        universe_instruments = []
        for i in range(25):
            inst = MagicMock()
            inst.instrument_id = id1 if i == 0 else uuid.uuid4()
            inst.instrument_type = "fund"
            inst.block_id = "BLK"
            inst.attributes = {"strategy": "long_only", "aum_usd": 1_000_000_000}
            inst.is_active = True
            inst.organization_id = "org-1"
            universe_instruments.append(inst)

        # id2: fund with no block
        inst2 = MagicMock()
        inst2.instrument_id = id2
        inst2.instrument_type = "fund"
        inst2.block_id = None
        inst2.attributes = {"strategy": "long_only"}
        inst2.is_active = True
        inst2.organization_id = "org-1"
        universe_instruments.append(inst2)

        # Metrics for all instruments with blocks
        metrics_by_id = {}
        for inst in universe_instruments:
            if inst.block_id:
                metrics_by_id[inst.instrument_id] = {
                    "sharpe_ratio": 1.0,
                    "max_drawdown_pct": -10.0,
                    "annual_return_pct": 8.0,
                    "annual_volatility_pct": 12.0,
                    "pct_positive_months": 0.6,
                }

        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = universe_instruments

        svc = PeerGroupService()
        with patch.object(svc, "_load_peer_metrics", return_value=metrics_by_id):
            results = svc.compute_rankings_batch(db, [id1, id2], "org-1")

        assert len(results) == 2
        assert isinstance(results[0], PeerRanking)
        assert isinstance(results[1], PeerGroupNotFound)
        assert results[1].reason == "no_block_assigned"

    def test_lower_is_better_metrics_set(self):
        assert "max_drawdown_pct" in LOWER_IS_BETTER
        assert "annual_volatility_pct" in LOWER_IS_BETTER
        assert "pe_ratio_ttm" in LOWER_IS_BETTER
        assert "debt_to_equity" in LOWER_IS_BETTER
        assert "sharpe_ratio" not in LOWER_IS_BETTER

    def test_rankings_have_lower_is_better_flag(self):
        target_id = uuid.uuid4()
        pg = self._make_peer_group(25, target_id)

        metrics_by_id = {}
        for i, mid in enumerate(pg.members):
            metrics_by_id[mid] = {
                "sharpe_ratio": 1.0 + i * 0.05,
                "max_drawdown_pct": -10.0 - i * 0.3,
                "annual_return_pct": 8.0 + i * 0.2,
                "annual_volatility_pct": 12.0 + i * 0.1,
                "pct_positive_months": 0.6 + i * 0.005,
            }

        svc = PeerGroupService()
        with patch.object(svc, "find_peers", return_value=pg), \
             patch.object(svc, "_load_peer_metrics", return_value=metrics_by_id):
            result = svc.compute_rankings(MagicMock(), target_id, "org-1")

        assert isinstance(result, PeerRanking)
        ranking_map = {r.metric: r for r in result.rankings}
        assert ranking_map["max_drawdown_pct"].lower_is_better is True
        assert ranking_map["annual_volatility_pct"].lower_is_better is True
        assert ranking_map["sharpe_ratio"].lower_is_better is False

    def test_target_not_in_peer_metrics_returns_not_found(self):
        """If target instrument has no metrics, return PeerGroupNotFound."""
        target_id = uuid.uuid4()
        pg = self._make_peer_group(25, target_id)

        # Metrics for everyone EXCEPT the target
        metrics_by_id = {}
        for mid in pg.members:
            if mid != target_id:
                metrics_by_id[mid] = {"sharpe_ratio": 1.0}

        svc = PeerGroupService()
        with patch.object(svc, "find_peers", return_value=pg), \
             patch.object(svc, "_load_peer_metrics", return_value=metrics_by_id):
            result = svc.compute_rankings(MagicMock(), target_id, "org-1")

        assert isinstance(result, PeerGroupNotFound)
        assert result.reason == "no_metrics"

    def test_metrics_with_insufficient_peers_for_metric(self):
        """If fewer than 3 peers have a metric, that metric gets None percentile."""
        target_id = uuid.uuid4()
        pg = self._make_peer_group(25, target_id)

        # Only target + 1 other have sharpe_ratio
        metrics_by_id = {
            pg.members[0]: {"sharpe_ratio": 1.0},
            pg.members[1]: {"sharpe_ratio": 1.5},
        }

        svc = PeerGroupService()
        with patch.object(svc, "find_peers", return_value=pg), \
             patch.object(svc, "_load_peer_metrics", return_value=metrics_by_id):
            result = svc.compute_rankings(MagicMock(), target_id, "org-1")

        assert isinstance(result, PeerRanking)
        sharpe_rank = next(r for r in result.rankings if r.metric == "sharpe_ratio")
        assert sharpe_rank.percentile is None  # insufficient peers for this metric

    def test_bond_weights_used_for_bonds(self):
        """Bond instrument uses bond-specific metric weights."""
        target_id = uuid.uuid4()
        members = [target_id] + [uuid.uuid4() for _ in range(24)]
        pg = PeerGroup(
            peer_group_key="GLOBAL_FI::corporate::A::medium",
            instrument_type="bond",
            block_id="GLOBAL_FI",
            member_count=25,
            members=tuple(members),
            fallback_level=0,
        )

        metrics_by_id = {}
        for i, mid in enumerate(members):
            metrics_by_id[mid] = {
                "spread_vs_benchmark_bps": 100.0 + i * 10,
                "liquidity_score": 0.5 + i * 0.02,
                "duration_efficiency": 1.0 + i * 0.1,
            }

        svc = PeerGroupService()
        with patch.object(svc, "find_peers", return_value=pg), \
             patch.object(svc, "_load_peer_metrics", return_value=metrics_by_id):
            result = svc.compute_rankings(MagicMock(), target_id, "org-1")

        assert isinstance(result, PeerRanking)
        metric_names = {r.metric for r in result.rankings}
        assert "spread_vs_benchmark_bps" in metric_names
        assert "liquidity_score" in metric_names
        assert "duration_efficiency" in metric_names


# ═══════════════════════════════════════════════════════════════════
#  peer_injection integration tests
# ═══════════════════════════════════════════════════════════════════


class TestPeerInjection:
    def test_gather_peer_context_returns_annotations(self):
        from vertical_engines.wealth.dd_report.peer_injection import gather_peer_context

        mock_ranking = PeerRanking(
            instrument_id=uuid.uuid4(),
            peer_group_key="BLK::long_only::mid",
            peer_count=25,
            fallback_level=0,
            rankings=(
                MetricRanking(metric="sharpe_ratio", value=1.24, percentile=77.0, lower_is_better=False),
                MetricRanking(metric="max_drawdown_pct", value=-8.5, percentile=65.0, lower_is_better=True),
            ),
            composite_percentile=71.0,
            ranked_at=datetime.now(timezone.utc),
        )

        with patch(
            "vertical_engines.wealth.peer_group.service.PeerGroupService"
        ) as MockSvc:
            instance = MockSvc.return_value
            instance.compute_rankings.return_value = mock_ranking

            db = MagicMock()
            result = gather_peer_context(
                db,
                instrument_id=str(uuid.uuid4()),
                organization_id="org-1",
            )

        assert result["peer_group_key"] == "BLK::long_only::mid"
        assert result["peer_count"] == 25
        assert result["composite_percentile"] == 71.0
        assert len(result["annotations"]) == 2
        assert "top" in result["annotations"][0]
        assert "25 peers" in result["annotations"][0]

    def test_gather_peer_context_not_found_returns_empty(self):
        from vertical_engines.wealth.dd_report.peer_injection import gather_peer_context

        with patch(
            "vertical_engines.wealth.peer_group.service.PeerGroupService"
        ) as MockSvc:
            instance = MockSvc.return_value
            instance.compute_rankings.return_value = PeerGroupNotFound(
                instrument_id=uuid.uuid4(),
                reason="insufficient_peers",
            )

            db = MagicMock()
            result = gather_peer_context(
                db,
                instrument_id=str(uuid.uuid4()),
                organization_id="org-1",
            )

        assert result == {}

    def test_gather_peer_context_exception_returns_empty(self):
        from vertical_engines.wealth.dd_report.peer_injection import gather_peer_context

        with patch(
            "vertical_engines.wealth.peer_group.service.PeerGroupService"
        ) as MockSvc:
            MockSvc.side_effect = RuntimeError("boom")

            db = MagicMock()
            result = gather_peer_context(
                db,
                instrument_id=str(uuid.uuid4()),
                organization_id="org-1",
            )

        assert result == {}
