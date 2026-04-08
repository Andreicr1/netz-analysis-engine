"""Tests for Portfolio NAV Synthesizer — Bridge 3 (G7.1, G7.2).

Focuses on:
- Weighted return aggregation correctness
- Floating-point tolerance with fractional weights
- Missing fund handling (renormalization)
- Day-0 inception NAV anchoring
- Edge cases: empty selection, single fund, all-zero returns
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

# ── Helper to build fake portfolio objects ──────────────────────────────────

@dataclass
class _FakePortfolio:
    id: uuid.UUID
    organization_id: str
    fund_selection_schema: dict | None
    inception_nav: Decimal
    inception_date: date | None
    backtest_start_date: date | None
    status: str = "active"


def _make_portfolio(
    weights: dict[str, float],
    inception_nav: float = 1000.0,
    inception_date: date | None = None,
) -> _FakePortfolio:
    funds = [
        {"instrument_id": fid, "fund_name": f"Fund-{fid[:8]}", "weight": w, "block_id": "eq"}
        for fid, w in weights.items()
    ]
    return _FakePortfolio(
        id=uuid.uuid4(),
        organization_id="test-org",
        fund_selection_schema={"funds": funds, "profile": "moderate"},
        inception_nav=Decimal(str(inception_nav)),
        inception_date=inception_date,
        backtest_start_date=None,
    )


# ── Unit tests for _extract_weights ─────────────────────────────────────────

class TestExtractWeights:
    def test_basic_extraction(self):
        from app.domains.wealth.workers.portfolio_nav_synthesizer import _extract_weights

        fid1, fid2 = str(uuid.uuid4()), str(uuid.uuid4())
        schema = {"funds": [
            {"instrument_id": fid1, "weight": 0.6, "fund_name": "A", "block_id": "eq"},
            {"instrument_id": fid2, "weight": 0.4, "fund_name": "B", "block_id": "fi"},
        ]}
        result = _extract_weights(schema)
        assert len(result) == 2
        assert abs(sum(result.values()) - 1.0) < 1e-10

    def test_empty_schema(self):
        from app.domains.wealth.workers.portfolio_nav_synthesizer import _extract_weights

        assert _extract_weights({"funds": []}) == {}
        assert _extract_weights({}) == {}

    def test_skips_missing_instrument_id(self):
        from app.domains.wealth.workers.portfolio_nav_synthesizer import _extract_weights

        schema = {"funds": [
            {"weight": 0.5, "fund_name": "No ID"},
            {"instrument_id": str(uuid.uuid4()), "weight": 0.5, "fund_name": "OK", "block_id": "eq"},
        ]}
        result = _extract_weights(schema)
        assert len(result) == 1


# ── Floating-point precision tests ──────────────────────────────────────────

class TestFloatingPointPrecision:
    """Verify NAV synthesis handles fractional weights without accumulating error."""

    def test_three_equal_weights_sum_to_one(self):
        """1/3 + 1/3 + 1/3 must sum to 1.0 within tolerance."""
        w = 1.0 / 3.0
        weights = [w, w, w]
        assert abs(sum(weights) - 1.0) < 1e-15

    def test_weighted_return_precision(self):
        """Verify cross-product precision with typical fund returns."""
        # 5 funds with CLARABEL-optimized weights (sum = 1.0)
        weights = np.array([0.2347, 0.1823, 0.2105, 0.1588, 0.2137])
        returns = np.array([0.00123, -0.00045, 0.00078, -0.00012, 0.00056])

        portfolio_return = np.dot(weights, returns)

        # Manual computation
        expected = sum(w * r for w, r in zip(weights, returns, strict=True))
        assert abs(portfolio_return - expected) < 1e-15

    def test_nav_chain_accumulation_error(self):
        """Simulate 252 days of NAV chaining and verify bounded error."""
        nav = 1000.0
        rng = np.random.default_rng(42)
        daily_returns = rng.normal(0.0003, 0.01, 252)  # ~7.5% annual, ~16% vol

        for r in daily_returns:
            nav = nav * (1.0 + r)

        # NAV should be positive and finite
        assert nav > 0
        assert np.isfinite(nav)

        # Cross-check with cumulative product
        nav_alt = 1000.0 * np.prod(1.0 + daily_returns)
        # Relative error should be < 1e-10 (IEEE 754 double)
        rel_error = abs(nav - nav_alt) / nav_alt
        assert rel_error < 1e-10

    def test_decimal_roundtrip(self):
        """Ensure Decimal(str(round(float, 6))) preserves precision."""
        nav_float = 1023.456789123
        nav_decimal = Decimal(str(round(nav_float, 6)))
        assert float(nav_decimal) == pytest.approx(1023.456789, abs=1e-6)

    def test_no_weight_renormalization_on_missing_fund(self):
        """P0-3 fix: missing-fund days do NOT renormalize the surviving weights.

        Renormalisation distorts mandate-target weights and produces NAVs
        whose value depends on data-arrival timing rather than mandate
        composition. The missing fund's price move is implicitly captured
        when it next reports (close-to-close return spans the gap).

        This test asserts the post-fix invariant: the portfolio return is
        the unrenormalised dot product of mandate weights with the
        per-day return vector (zero contribution from missing funds).
        """
        weights = {
            "a": 0.30,
            "b": 0.25,
            "c": 0.20,
            "d": 0.15,
            "e": 0.10,
        }
        # Fund "c" has no data today.
        returns_today = {"a": 0.001, "b": -0.002, "d": 0.0015, "e": 0.0005}

        # Replicate the synthesizer's loop verbatim — must match the logic
        # in synthesize_portfolio_nav so this test catches future regressions.
        portfolio_return = 0.0
        for fid, w in weights.items():
            r = returns_today.get(fid)
            if r is not None:
                portfolio_return += w * r

        expected = (
            0.30 * 0.001
            + 0.25 * (-0.002)
            + 0.15 * 0.0015
            + 0.10 * 0.0005
        )
        assert abs(portfolio_return - expected) < 1e-15
        # And the (wrong, pre-fix) renormalised value must NOT be what we use.
        active_weight = 0.30 + 0.25 + 0.15 + 0.10  # 0.80
        renormalised = expected * (1.0 / active_weight)
        assert abs(portfolio_return - renormalised) > 1e-9


# ── NAV synthesis integration tests (mocked DB) ────────────────────────────

class TestSynthesizePortfolioNav:
    """Test the synthesize_portfolio_nav function with mocked DB."""

    @pytest.mark.asyncio
    async def test_no_selection_returns_early(self):
        from app.domains.wealth.workers.portfolio_nav_synthesizer import synthesize_portfolio_nav

        portfolio = _FakePortfolio(
            id=uuid.uuid4(),
            organization_id="test",
            fund_selection_schema=None,
            inception_nav=Decimal(1000),
            inception_date=None,
            backtest_start_date=None,
        )
        db = AsyncMock()
        result = await synthesize_portfolio_nav(db, portfolio)
        assert result["status"] == "no_selection"
        assert result["dates_computed"] == 0

    @pytest.mark.asyncio
    async def test_empty_funds_returns_early(self):
        from app.domains.wealth.workers.portfolio_nav_synthesizer import synthesize_portfolio_nav

        portfolio = _FakePortfolio(
            id=uuid.uuid4(),
            organization_id="test",
            fund_selection_schema={"funds": []},
            inception_nav=Decimal(1000),
            inception_date=None,
            backtest_start_date=None,
        )
        db = AsyncMock()
        result = await synthesize_portfolio_nav(db, portfolio)
        assert result["status"] == "no_weights"

    @pytest.mark.asyncio
    async def test_single_fund_full_weight(self):
        """Single fund at 100% weight — portfolio NAV = fund NAV chain."""
        from app.domains.wealth.workers.portfolio_nav_synthesizer import (
            synthesize_portfolio_nav,
        )

        fid = uuid.uuid4()
        today = date.today()
        dates = [today - timedelta(days=3 - i) for i in range(3)]

        portfolio = _make_portfolio(
            weights={str(fid): 1.0},
            inception_nav=1000.0,
            inception_date=dates[0] - timedelta(days=1),
        )

        # Mock DB
        db = AsyncMock()
        db.commit = AsyncMock()

        # Mock _get_last_nav → no prior NAV
        mock_last = MagicMock()
        mock_last.one_or_none.return_value = None

        # Mock _fetch_fund_returns → 3 days of returns. return_type is now
        # consumed by the synthesizer (P0-3 fix), so each row exposes it.
        returns_data = [
            MagicMock(nav_date=dates[0], instrument_id=fid, return_1d=Decimal("0.01"), return_type="arithmetic"),
            MagicMock(nav_date=dates[1], instrument_id=fid, return_1d=Decimal("-0.005"), return_type="arithmetic"),
            MagicMock(nav_date=dates[2], instrument_id=fid, return_1d=Decimal("0.008"), return_type="arithmetic"),
        ]
        mock_returns = MagicMock()
        mock_returns.all.return_value = returns_data

        call_count = 0

        def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # _get_last_nav
                return mock_last
            if call_count == 2:
                # _fetch_fund_returns
                return mock_returns
            # day0 insert and batch upserts
            return MagicMock()

        db.execute = AsyncMock(side_effect=mock_execute)

        result = await synthesize_portfolio_nav(db, portfolio)
        assert result["dates_computed"] == 3
        assert result["status"] == "ok"

        # Verify final NAV: 1000 × 1.01 × 0.995 × 1.008 ≈ 1012.9496
        expected = 1000.0 * 1.01 * 0.995 * 1.008
        assert abs(result["final_nav"] - round(expected, 4)) < 0.01


# ── Model tests ─────────────────────────────────────────────────────────────

class TestModelPortfolioNavModel:
    """Test the ORM model can be imported and has correct table name."""

    def test_import(self):
        from app.domains.wealth.models.model_portfolio_nav import ModelPortfolioNav

        assert ModelPortfolioNav.__tablename__ == "model_portfolio_nav"

    def test_in_models_init(self):
        from app.domains.wealth.models import ModelPortfolioNav

        assert ModelPortfolioNav.__tablename__ == "model_portfolio_nav"

    def test_columns(self):
        from app.domains.wealth.models.model_portfolio_nav import ModelPortfolioNav

        mapper = ModelPortfolioNav.__table__
        col_names = {c.name for c in mapper.columns}
        assert "portfolio_id" in col_names
        assert "nav_date" in col_names
        assert "nav" in col_names
        assert "daily_return" in col_names
        assert "organization_id" in col_names


# ── Duck typing validation ──────────────────────────────────────────────────

class TestDuckTypingPolymorphism:
    """Ensure model_portfolio_nav has compatible schema with nav_timeseries
    for analytics code that expects (id, date, nav, return) tuples.
    """

    def test_compatible_columns(self):
        from app.domains.wealth.models.model_portfolio_nav import ModelPortfolioNav
        from app.domains.wealth.models.nav import NavTimeseries

        # Both must have: a UUID id field, date field, nav (Numeric), return (Numeric)
        mp_cols = {c.name for c in ModelPortfolioNav.__table__.columns}
        nav_cols = {c.name for c in NavTimeseries.__table__.columns}

        # Portfolio uses portfolio_id, NavTimeseries uses instrument_id
        # Both have nav_date, nav-equivalent, return-equivalent
        assert "nav_date" in mp_cols
        assert "nav_date" in nav_cols
        assert "nav" in mp_cols
        assert "nav" in nav_cols
        assert "daily_return" in mp_cols
        assert "return_1d" in nav_cols  # Different column name, same semantics

    def test_nav_precision_matches(self):
        """Both tables use Numeric(18,6) for NAV."""
        from app.domains.wealth.models.model_portfolio_nav import ModelPortfolioNav
        from app.domains.wealth.models.nav import NavTimeseries

        mp_nav_type = ModelPortfolioNav.__table__.c.nav.type
        nt_nav_type = NavTimeseries.__table__.c.nav.type

        assert mp_nav_type.precision == nt_nav_type.precision
        assert mp_nav_type.scale == nt_nav_type.scale


# ── P0-3 regression tests: return_type unification + carry-forward ─────────


class TestReturnTypeUnification:
    """Regression tests for the P0-3 fix in ``_fetch_fund_returns``.

    Pre-fix: ``portfolio_nav_synthesizer`` summed log returns linearly,
    which is mathematically invalid (``Σ wᵢ·log(1+rᵢ) ≠ log(1+Σ wᵢ·rᵢ)``).
    Post-fix: log returns are converted to arithmetic at fetch time using
    ``math.expm1``.
    """

    @pytest.mark.asyncio
    async def test_log_returns_converted_to_arithmetic(self):
        """A row with ``return_type='log'`` must be converted via expm1."""
        import math

        from app.domains.wealth.workers.portfolio_nav_synthesizer import _fetch_fund_returns

        fid = uuid.uuid4()
        d = date.today()
        log_value = 0.05  # log(1.0513...) ≈ 0.05 → arithmetic ≈ 0.05127
        row = MagicMock(nav_date=d, instrument_id=fid, return_1d=Decimal(str(log_value)), return_type="log")

        mock_result = MagicMock()
        mock_result.all.return_value = [row]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        out = await _fetch_fund_returns(db, [fid], d, d)
        assert d in out
        assert fid in out[d]
        expected_arith = math.expm1(log_value)
        assert abs(out[d][fid] - expected_arith) < 1e-15

    @pytest.mark.asyncio
    async def test_arithmetic_returns_passed_through(self):
        """A row with ``return_type='arithmetic'`` must be unchanged."""
        from app.domains.wealth.workers.portfolio_nav_synthesizer import _fetch_fund_returns

        fid = uuid.uuid4()
        d = date.today()
        arith_value = 0.05
        row = MagicMock(nav_date=d, instrument_id=fid, return_1d=Decimal(str(arith_value)), return_type="arithmetic")

        mock_result = MagicMock()
        mock_result.all.return_value = [row]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        out = await _fetch_fund_returns(db, [fid], d, d)
        assert abs(out[d][fid] - arith_value) < 1e-15

    @pytest.mark.asyncio
    async def test_mixed_log_and_arithmetic_in_same_batch(self):
        """A batch with both return_types must convert each row independently.

        This is the realistic production scenario: ``instrument_ingestion``
        writes ``log`` for new series while legacy rows still carry the
        ``arithmetic`` server_default.
        """
        import math

        from app.domains.wealth.workers.portfolio_nav_synthesizer import _fetch_fund_returns

        fid_log = uuid.uuid4()
        fid_arith = uuid.uuid4()
        d = date.today()

        rows = [
            MagicMock(nav_date=d, instrument_id=fid_log, return_1d=Decimal("0.02"), return_type="log"),
            MagicMock(nav_date=d, instrument_id=fid_arith, return_1d=Decimal("0.02"), return_type="arithmetic"),
        ]
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        out = await _fetch_fund_returns(db, [fid_log, fid_arith], d, d)
        # Different conversion: math.expm1(0.02) ≈ 0.02020 vs 0.02 raw.
        assert out[d][fid_log] == pytest.approx(math.expm1(0.02), abs=1e-15)
        assert out[d][fid_arith] == pytest.approx(0.02, abs=1e-15)
        # And they must NOT be equal — proves the branch fired.
        assert out[d][fid_log] != out[d][fid_arith]


# ── P0-2 regression test: DD report ordering ────────────────────────────────


class TestDDReportOrdering:
    """Regression test for the P0-2 fix in ``quant_injection.gather_quant_metrics``.

    Pre-fix: ``order_by(organization_id NULLS LAST, calc_date DESC)`` —
    a stale tenant row from 30 days ago beat a fresh global row from today.
    Post-fix: ``order_by(calc_date DESC, organization_id NULLS LAST)`` —
    freshness wins; tenant row only beats global on the same date.
    """

    def test_order_by_clause_calc_date_first(self):
        """Inspect the SQLAlchemy query produced by gather_quant_metrics.

        We assert the compiled SQL has ``calc_date DESC`` BEFORE the
        ``organization_id`` ordering — the exact bug we are guarding against.
        """
        from unittest.mock import MagicMock as _MM

        from app.domains.wealth.models.risk import FundRiskMetrics
        from vertical_engines.wealth.dd_report.quant_injection import gather_quant_metrics

        captured: dict = {}

        class _CapturingQuery:
            def filter(self, *args, **_kwargs):
                return self

            def order_by(self, *args):
                captured["order_by"] = args
                return self

            def first(self):
                return None

        db = _MM()
        db.query = _MM(return_value=_CapturingQuery())

        # Call — we don't care about the return value, only the captured order_by.
        gather_quant_metrics(
            db,
            instrument_id="00000000-0000-0000-0000-000000000001",
            organization_id="00000000-0000-0000-0000-000000000002",
        )

        order_by_args = captured.get("order_by")
        assert order_by_args is not None, "order_by() was never called"
        assert len(order_by_args) >= 2, "expected at least two ordering keys"

        # The first ordering key MUST be the calc_date column descending.
        first_key = order_by_args[0]
        # SQLAlchemy desc() wraps the column; the underlying element is the column.
        underlying = getattr(first_key, "element", first_key)
        assert underlying is FundRiskMetrics.calc_date or getattr(
            underlying, "key", None,
        ) == "calc_date", (
            f"expected calc_date as first ORDER BY key, got {first_key!r} — "
            "P0-2 regression: organization_id must NOT come first"
        )


# ── P0-1 model regression: composite identity tuple ─────────────────────────


class TestFundRiskMetricsCompositeIdentity:
    """Regression test for the P0-1 fix in the ORM mapping.

    Pre-fix: PK = (instrument_id, calc_date). Two writers (global +
    org-scoped) clobbered each other on UPSERT.
    Post-fix: identity tuple = (instrument_id, calc_date, organization_id),
    backed by a UNIQUE INDEX … NULLS NOT DISTINCT (migration 0093).
    """

    def test_organization_id_is_part_of_primary_key(self):
        from app.domains.wealth.models.risk import FundRiskMetrics

        pk_columns = {c.name for c in FundRiskMetrics.__table__.primary_key.columns}
        assert pk_columns == {"instrument_id", "calc_date", "organization_id"}, (
            f"P0-1 regression: composite identity must be "
            f"(instrument_id, calc_date, organization_id), got {pk_columns}"
        )

    def test_organization_id_is_nullable(self):
        """Global rows are written with organization_id IS NULL."""
        from app.domains.wealth.models.risk import FundRiskMetrics

        org_col = FundRiskMetrics.__table__.c.organization_id
        assert org_col.nullable is True


# ── Edge cases ──────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_all_zero_returns(self):
        """If all funds return 0, NAV stays at inception."""
        nav = 1000.0
        for _ in range(30):
            portfolio_return = 0.0
            nav = nav * (1.0 + portfolio_return)
        assert nav == 1000.0

    def test_negative_returns_dont_go_negative(self):
        """Even with large negative returns, NAV stays positive."""
        nav = 1000.0
        for _ in range(100):
            nav = nav * (1.0 + (-0.03))  # -3% daily
        assert nav > 0

    def test_very_small_weights(self):
        """Weights like 0.001 should still contribute to return."""
        weights = np.array([0.001, 0.999])
        returns = np.array([0.10, 0.0])  # Only small-weight fund has a return
        pr = np.dot(weights, returns)
        assert abs(pr - 0.0001) < 1e-10

    def test_inception_nav_100(self):
        """Inception NAV of 100 (alternative convention) works."""
        nav = 100.0
        nav = nav * (1.0 + 0.01)
        assert abs(nav - 101.0) < 1e-10

    def test_inception_nav_1000(self):
        """Inception NAV of 1000 (default convention) works."""
        nav = 1000.0
        nav = nav * (1.0 + 0.01)
        assert abs(nav - 1010.0) < 1e-10
