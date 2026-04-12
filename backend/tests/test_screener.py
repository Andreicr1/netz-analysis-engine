"""Tests for the Wealth Instrument Screener Suite — Sprint 1.

Covers:
- LayerEvaluator (Layer 1 eliminatory, Layer 2 mandate fit)
- ScreenerService (3-layer screening, early exit, watchlist)
- QuantMetrics computation (Sharpe, drawdown, bond metrics)
- Composite scoring with percentile rank
- CsvImportAdapter (valid CSV, invalid rows, formula injection)
- TiingoInstrumentProvider protocol conformance
- Hysteresis / status determination
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from vertical_engines.wealth.screener.layer_evaluator import (
    LayerEvaluator,
    determine_status,
)
from vertical_engines.wealth.screener.models import (
    CriterionResult,
    InstrumentScreeningResult,
    ScreeningRunResult,
)
from vertical_engines.wealth.screener.quant_metrics import (
    QuantMetrics,
    composite_score,
    compute_bond_metrics,
    compute_quant_metrics,
)
from vertical_engines.wealth.screener.service import ScreenerService

# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def layer1_config():
    return {
        "fund": {
            "min_aum_usd": 100_000_000,
            "min_track_record_years": 3,
            "allowed_domiciles": ["IE", "LU", "KY", "US", "GB"],
        },
        "bond": {
            "min_credit_rating": "BBB-",
            "min_outstanding_usd": 50_000_000,
        },
        "equity": {
            "min_market_cap_usd": 1_000_000_000,
            "allowed_exchanges": ["NYSE", "NASDAQ", "LSE"],
        },
    }


@pytest.fixture
def layer2_config():
    return {
        "blocks": {
            "US_EQUITY": {
                "criteria": {
                    "asset_class": "equity",
                    "geography": "US",
                    "max_pe_ratio": 40,
                },
            },
            "GLOBAL_FI": {
                "criteria": {
                    "asset_class": "fixed_income",
                    "max_duration_years": 10,
                },
            },
        },
    }


@pytest.fixture
def layer3_config():
    return {
        "fund": {
            "weights": {
                "sharpe_ratio": 0.30,
                "max_drawdown": 0.25,
                "pct_positive_months": 0.20,
            },
            "min_data_period_days": 756,
        },
        "bond": {
            "weights": {
                "spread_vs_benchmark": 0.40,
                "liquidity_score": 0.30,
                "duration_efficiency": 0.30,
            },
        },
        "equity": {
            "weights": {
                "pe_relative_sector": 0.25,
                "roe": 0.25,
                "debt_equity": 0.20,
                "momentum_score": 0.30,
            },
        },
    }


@pytest.fixture
def screener(layer1_config, layer2_config, layer3_config):
    return ScreenerService(layer1_config, layer2_config, layer3_config)


@pytest.fixture
def passing_fund_attrs():
    return {
        "aum_usd": "200000000",
        "track_record_years": "5",
        "domiciles": "IE",
        "structures": "UCITS",
        "manager_name": "BlackRock",
        "inception_date": "2019-01-01",
    }


@pytest.fixture
def failing_fund_attrs():
    return {
        "aum_usd": "50000000",  # Below 100M threshold
        "track_record_years": "5",
        "domicile": "IE",
        "manager_name": "Small Fund",
        "inception_date": "2019-01-01",
    }


# ═══════════════════════════════════════════════════════════════════
#  Layer 1 Tests
# ═══════════════════════════════════════════════════════════════════

class TestLayerEvaluator:
    def test_layer1_fund_passes(self, layer1_config, passing_fund_attrs):
        evaluator = LayerEvaluator(layer1_config)
        results = evaluator.evaluate_layer1("fund", passing_fund_attrs, layer1_config)
        assert all(r.passed for r in results), f"Failed criteria: {[r for r in results if not r.passed]}"

    def test_layer1_fund_fails_aum(self, layer1_config, failing_fund_attrs):
        evaluator = LayerEvaluator(layer1_config)
        results = evaluator.evaluate_layer1("fund", failing_fund_attrs, layer1_config)
        failed = [r for r in results if not r.passed]
        assert len(failed) >= 1
        assert any("aum" in r.criterion for r in failed)

    def test_layer1_fund_fails_domicile(self, layer1_config, passing_fund_attrs):
        attrs = {**passing_fund_attrs, "domiciles": "XX"}
        evaluator = LayerEvaluator(layer1_config)
        results = evaluator.evaluate_layer1("fund", attrs, layer1_config)
        failed = [r for r in results if not r.passed]
        assert any("domicile" in r.criterion for r in failed)

    def test_layer1_bond_rating_passes(self, layer1_config):
        # min_credit_rating handled as special case, min_outstanding_usd strips "min_" → "outstanding_usd"
        attrs = {"credit_rating_sp": "A+", "outstanding_usd": "100000000",
                 "maturity_date": "2030-01-01", "coupon_rate_pct": "5.0", "issuer_name": "Test"}
        evaluator = LayerEvaluator(layer1_config)
        results = evaluator.evaluate_layer1("bond", attrs, layer1_config)
        assert all(r.passed for r in results)

    def test_layer1_bond_rating_fails(self, layer1_config):
        attrs = {"credit_rating_sp": "BB", "outstanding_usd": "100000000"}
        evaluator = LayerEvaluator(layer1_config)
        results = evaluator.evaluate_layer1("bond", attrs, layer1_config)
        failed = [r for r in results if not r.passed]
        assert any("credit_rating" in r.criterion for r in failed)

    def test_layer1_equity_passes(self, layer1_config):
        attrs = {"market_cap_usd": "5000000000", "exchanges": "NYSE"}
        evaluator = LayerEvaluator(layer1_config)
        results = evaluator.evaluate_layer1("equity", attrs, layer1_config)
        assert all(r.passed for r in results)

    def test_layer1_equity_fails_market_cap(self, layer1_config):
        attrs = {"market_cap_usd": "500000000", "exchanges": "NYSE"}
        evaluator = LayerEvaluator(layer1_config)
        results = evaluator.evaluate_layer1("equity", attrs, layer1_config)
        failed = [r for r in results if not r.passed]
        assert any("market_cap" in r.criterion for r in failed)

    def test_layer1_missing_data_fails(self, layer1_config):
        evaluator = LayerEvaluator(layer1_config)
        results = evaluator.evaluate_layer1("fund", {}, layer1_config)
        failed = [r for r in results if not r.passed]
        assert len(failed) >= 1

    def test_layer1_results_have_audit_trail(self, layer1_config, passing_fund_attrs):
        evaluator = LayerEvaluator(layer1_config)
        results = evaluator.evaluate_layer1("fund", passing_fund_attrs, layer1_config)
        for r in results:
            assert r.criterion
            assert r.expected
            assert r.actual is not None  # Can be empty string for missing data
            assert r.layer == 1

    def test_layer2_block_criteria(self, layer1_config, layer2_config):
        evaluator = LayerEvaluator(layer1_config)
        attrs = {"asset_class": "equity", "geography": "US", "pe_ratio": "25"}
        results = evaluator.evaluate_layer2("equity", attrs, "US_EQUITY", layer2_config)
        assert all(r.passed for r in results)

    def test_layer2_block_fails(self, layer1_config, layer2_config):
        evaluator = LayerEvaluator(layer1_config)
        attrs = {"asset_class": "equity", "geography": "US", "pe_ratio": "50"}
        results = evaluator.evaluate_layer2("equity", attrs, "US_EQUITY", layer2_config)
        failed = [r for r in results if not r.passed]
        assert any("pe_ratio" in r.criterion for r in failed)

    def test_layer2_no_block(self, layer1_config, layer2_config):
        evaluator = LayerEvaluator(layer1_config)
        results = evaluator.evaluate_layer2("fund", {}, None, layer2_config)
        assert results == []


# ═══════════════════════════════════════════════════════════════════
#  Hysteresis Tests
# ═══════════════════════════════════════════════════════════════════

class TestHysteresis:
    def test_first_screening_pass(self):
        assert determine_status(0.70, None) == "PASS"

    def test_first_screening_watchlist(self):
        assert determine_status(0.50, None) == "WATCHLIST"

    def test_first_screening_fail(self):
        assert determine_status(0.30, None) == "FAIL"

    def test_watchlist_needs_buffer_to_promote(self):
        # 0.60 = pass_threshold, hysteresis = 0.05
        # Need >= 0.65 to promote from WATCHLIST
        assert determine_status(0.62, "WATCHLIST") == "WATCHLIST"
        assert determine_status(0.66, "WATCHLIST") == "PASS"

    def test_pass_needs_buffer_to_demote(self):
        # Need < 0.55 to demote from PASS
        assert determine_status(0.57, "PASS") == "PASS"
        assert determine_status(0.54, "PASS") == "WATCHLIST"

    def test_none_score_returns_watchlist(self):
        assert determine_status(None, None) == "WATCHLIST"
        assert determine_status(None, "PASS") == "WATCHLIST"


# ═══════════════════════════════════════════════════════════════════
#  ScreenerService Tests
# ═══════════════════════════════════════════════════════════════════

class TestScreenerService:
    def test_screen_instrument_layer1_fail_early_exit(self, screener, failing_fund_attrs):
        result = screener.screen_instrument(
            instrument_id=uuid.uuid4(),
            instrument_type="fund",
            attributes=failing_fund_attrs,
        )
        assert result.overall_status == "FAIL"
        assert result.failed_at_layer == 1
        assert result.score is None

    def test_screen_instrument_passes_all_layers(self, screener, passing_fund_attrs):
        result = screener.screen_instrument(
            instrument_id=uuid.uuid4(),
            instrument_type="fund",
            attributes=passing_fund_attrs,
        )
        # Without quant metrics, Layer 3 returns None → WATCHLIST
        assert result.overall_status == "WATCHLIST"
        assert result.score is None

    def test_screen_instrument_with_quant(self, screener, passing_fund_attrs):
        metrics = QuantMetrics(
            sharpe_ratio=1.2,
            annual_volatility_pct=12.0,
            max_drawdown_pct=-15.0,
            pct_positive_months=0.65,
            annual_return_pct=10.0,
            data_period_days=800,
        )
        peer_vals = {
            "sharpe_ratio": [0.5, 0.8, 1.0, 1.1, 1.3, 1.5, 0.7, 0.9, 1.2],
            "max_drawdown": [-20, -18, -15, -12, -10, -25, -22, -17, -14],
            "pct_positive_months": [0.5, 0.55, 0.6, 0.65, 0.7, 0.58, 0.62, 0.68, 0.72],
        }
        result = screener.screen_instrument(
            instrument_id=uuid.uuid4(),
            instrument_type="fund",
            attributes=passing_fund_attrs,
            quant_metrics=metrics,
            peer_values=peer_vals,
        )
        assert result.score is not None
        assert 0.0 <= result.score <= 1.0
        assert result.overall_status in ("PASS", "WATCHLIST", "FAIL")

    def test_screen_universe_batch(self, screener, passing_fund_attrs, failing_fund_attrs):
        instruments = [
            {
                "instrument_id": uuid.uuid4(),
                "instrument_type": "fund",
                "attributes": passing_fund_attrs,
            },
            {
                "instrument_id": uuid.uuid4(),
                "instrument_type": "fund",
                "attributes": failing_fund_attrs,
            },
        ]
        result = screener.screen_universe(instruments, uuid.uuid4())
        assert result.instrument_count == 2
        assert len(result.results) == 2
        statuses = {r.overall_status for r in result.results}
        assert "FAIL" in statuses

    def test_config_hash_deterministic(self, screener):
        h1 = screener.config_hash
        h2 = screener.config_hash
        assert h1 == h2

    def test_analysis_type_by_instrument(self, screener, passing_fund_attrs):
        fund_result = screener.screen_instrument(
            instrument_id=uuid.uuid4(),
            instrument_type="fund",
            attributes=passing_fund_attrs,
        )
        assert fund_result.required_analysis_type == "dd_report"

    def test_bond_analysis_type(self, screener):
        attrs = {"credit_rating_sp": "AA", "outstanding_usd": "100000000",
                 "maturity_date": "2030-01-01", "coupon_rate_pct": "5.0", "issuer_name": "US Treasury"}
        result = screener.screen_instrument(
            instrument_id=uuid.uuid4(),
            instrument_type="bond",
            attributes=attrs,
        )
        assert result.required_analysis_type == "bond_brief"

    def test_layer_results_serializable(self, screener, passing_fund_attrs):
        result = screener.screen_instrument(
            instrument_id=uuid.uuid4(),
            instrument_type="fund",
            attributes=passing_fund_attrs,
        )
        serialized = result.layer_results_dict
        assert isinstance(serialized, list)
        if serialized:
            assert "criterion" in serialized[0]
            assert "passed" in serialized[0]


# ═══════════════════════════════════════════════════════════════════
#  Quant Metrics Tests
# ═══════════════════════════════════════════════════════════════════

class TestQuantMetrics:
    def _make_price_series(self, n_days=500, annual_return=0.10, volatility=0.15):
        """Generate synthetic daily price data."""
        dates = pd.date_range(end=datetime.now(), periods=n_days, freq="B")
        n = len(dates)  # may differ from n_days on weekends/holidays
        daily_return = annual_return / 252
        daily_vol = volatility / np.sqrt(252)
        returns = np.random.normal(daily_return, daily_vol, n)
        prices = 100 * np.exp(np.cumsum(returns))
        return pd.DataFrame({"Close": prices}, index=dates)

    def test_compute_quant_metrics_valid(self):
        df = self._make_price_series(n_days=600)
        result = compute_quant_metrics(df)
        assert result is not None
        assert isinstance(result.sharpe_ratio, float)
        assert result.data_period_days > 0
        assert result.annual_volatility_pct > 0
        assert result.max_drawdown_pct <= 0  # Drawdown is negative

    def test_compute_quant_metrics_insufficient_data(self):
        df = pd.DataFrame({"Close": [100, 101, 102]}, index=pd.date_range("2024-01-01", periods=3))
        result = compute_quant_metrics(df)
        assert result is None

    def test_compute_quant_metrics_empty_df(self):
        result = compute_quant_metrics(pd.DataFrame())
        assert result is None

    def test_compute_quant_metrics_none(self):
        result = compute_quant_metrics(None)
        assert result is None

    def test_compute_bond_metrics(self):
        attrs = {
            "coupon_rate_pct": "5.5",
            "outstanding_usd": "500000000",
            "face_value_usd": "1000000000",
            "duration_years": "7",
            "benchmark_yield_pct": "4.0",
        }
        result = compute_bond_metrics(attrs)
        assert result is not None
        assert result.spread_vs_benchmark_bps == 150.0
        assert 0 <= result.liquidity_score <= 1.0
        assert result.duration_efficiency > 0

    def test_compute_bond_metrics_missing_data(self):
        result = compute_bond_metrics({})
        assert result is not None  # Returns zeros, not None
        assert result.spread_vs_benchmark_bps == 0

    def test_composite_score_basic(self):
        metrics = {"sharpe_ratio": 1.2, "max_drawdown": -15.0}
        peers = {
            "sharpe_ratio": [0.5, 0.8, 1.0, 1.3, 1.5],
            "max_drawdown": [-25, -20, -15, -10, -5],
        }
        weights = {"sharpe_ratio": 0.5, "max_drawdown": 0.5}
        score = composite_score(metrics, peers, weights)
        assert score is not None
        assert 0.0 <= score <= 1.0

    def test_composite_score_insufficient_peers(self):
        metrics = {"sharpe_ratio": 1.0}
        peers = {"sharpe_ratio": [1.0, 1.1]}  # Only 2 peers, need 3+
        weights = {"sharpe_ratio": 1.0}
        score = composite_score(metrics, peers, weights)
        assert score is None

    def test_composite_score_no_matching_weights(self):
        metrics = {"unknown_metric": 1.0}
        peers = {"unknown_metric": [0.5, 1.0, 1.5]}
        weights = {"sharpe_ratio": 1.0}  # Different metric
        score = composite_score(metrics, peers, weights)
        assert score is None

    def test_composite_score_lower_is_better(self):
        # annual_volatility_pct is lower-is-better
        # Lower volatility should get higher score
        metrics_good = {"annual_volatility_pct": 5.0}
        metrics_bad = {"annual_volatility_pct": 25.0}
        peers = {"annual_volatility_pct": [5, 10, 15, 20, 25]}
        weights = {"annual_volatility_pct": 1.0}
        lower_better = frozenset({"annual_volatility_pct"})
        score_good = composite_score(metrics_good, peers, weights, lower_is_better=lower_better)
        score_bad = composite_score(metrics_bad, peers, weights, lower_is_better=lower_better)
        assert score_good is not None
        assert score_bad is not None
        assert score_good > score_bad


# ═══════════════════════════════════════════════════════════════════
#  CSV Import Tests
# ═══════════════════════════════════════════════════════════════════

class TestCsvImportAdapter:
    def _make_csv(self, rows: list[str]) -> io.BytesIO:
        return io.BytesIO("\n".join(rows).encode("utf-8"))

    def test_valid_fund_csv(self):
        from app.services.providers.csv_import_adapter import CsvImportAdapter
        csv_data = self._make_csv([
            "name,aum_usd,manager_name,inception_date,isin,ticker,asset_class,geography",
            "BlackRock Fund,500000000,BlackRock,2020-01-01,IE00B4L5Y983,IWDA,equity,IE",
            "Vanguard Fund,300000000,Vanguard,2019-06-15,IE00B3XXRP09,VWCE,equity,IE",
        ])
        adapter = CsvImportAdapter()
        result = adapter.parse(csv_data, "fund")
        assert result.imported == 2
        assert result.skipped == 0
        assert len(result.instruments) == 2
        assert result.instruments[0].name == "BlackRock Fund"

    def test_missing_required_columns(self):
        from app.services.providers.csv_import_adapter import CsvImportAdapter
        csv_data = self._make_csv([
            "name,isin",
            "Some Fund,IE00B4L5Y983",
        ])
        adapter = CsvImportAdapter()
        result = adapter.parse(csv_data, "fund")
        assert result.imported == 0
        assert len(result.errors) >= 1
        assert "Missing required columns" in result.errors[0].message

    def test_empty_required_field(self):
        from app.services.providers.csv_import_adapter import CsvImportAdapter
        csv_data = self._make_csv([
            "name,aum_usd,manager_name,inception_date",
            ",500000000,BlackRock,2020-01-01",
        ])
        adapter = CsvImportAdapter()
        result = adapter.parse(csv_data, "fund")
        assert result.imported == 0
        assert result.skipped > 0

    def test_duplicate_isin_rejected(self):
        from app.services.providers.csv_import_adapter import CsvImportAdapter
        csv_data = self._make_csv([
            "name,aum_usd,manager_name,inception_date,isin",
            "Fund A,500000000,BlackRock,2020-01-01,IE00B4L5Y983",
            "Fund B,300000000,Vanguard,2019-06-15,IE00B4L5Y983",
        ])
        adapter = CsvImportAdapter()
        result = adapter.parse(csv_data, "fund")
        assert result.imported == 1
        assert result.skipped == 1
        assert any("Duplicate ISIN" in e.message for e in result.errors)

    def test_formula_injection_sanitized(self):
        from app.services.providers.csv_import_adapter import CsvImportAdapter
        csv_data = self._make_csv([
            "name,aum_usd,manager_name,inception_date",
            "=CMD('calc'),500000000,BlackRock,2020-01-01",
        ])
        adapter = CsvImportAdapter()
        result = adapter.parse(csv_data, "fund")
        assert result.imported == 1
        # Name should be sanitized with leading quote
        assert result.instruments[0].name.startswith("'")

    def test_bond_csv_required_columns(self):
        from app.services.providers.csv_import_adapter import CsvImportAdapter
        csv_data = self._make_csv([
            "name,maturity_date,coupon_rate_pct,issuer_name,isin",
            "US Treasury 10Y,2034-05-15,4.25,US Treasury,US912810TN81",
        ])
        adapter = CsvImportAdapter()
        result = adapter.parse(csv_data, "bond")
        assert result.imported == 1
        assert result.instruments[0].instrument_type == "bond"
        assert result.instruments[0].asset_class == "fixed_income"

    def test_invalid_instrument_type(self):
        from app.services.providers.csv_import_adapter import CsvImportAdapter
        csv_data = self._make_csv(["name", "Test"])
        adapter = CsvImportAdapter()
        result = adapter.parse(csv_data, "unknown_type")
        assert result.imported == 0
        assert len(result.errors) == 1

    def test_invalid_utf8(self):
        from app.services.providers.csv_import_adapter import CsvImportAdapter
        adapter = CsvImportAdapter()
        result = adapter.parse(io.BytesIO(b"\x80\x81\x82"), "fund")
        assert result.imported == 0
        assert any("UTF-8" in e.message for e in result.errors)


# ═══════════════════════════════════════════════════════════════════
#  Provider Protocol Tests
# ═══════════════════════════════════════════════════════════════════

class TestProviderProtocol:
    def test_tiingo_provider_implements_protocol(self):
        from app.services.providers.protocol import InstrumentDataProvider
        from app.services.providers.tiingo_instrument_provider import TiingoInstrumentProvider
        provider = TiingoInstrumentProvider()
        assert isinstance(provider, InstrumentDataProvider)

    def test_safe_get_handles_nan(self):
        from app.services.providers.protocol import safe_get
        assert safe_get({"x": float("nan")}, "x", default=0) == 0
        assert safe_get({"x": float("inf")}, "x", default=0) == 0
        assert safe_get({"x": 42}, "x") == 42
        assert safe_get({}, "x", default="default") == "default"

    def test_safe_get_with_coerce(self):
        from app.services.providers.protocol import safe_get
        assert safe_get({"x": "42"}, "x", coerce=int) == 42
        assert safe_get({"x": "not_a_number"}, "x", coerce=int, default=0) == 0

    def test_raw_instrument_data_frozen(self):
        from app.services.providers.protocol import RawInstrumentData
        data = RawInstrumentData(
            ticker="AAPL",
            isin=None,
            name="Apple Inc",
            instrument_type="equity",
            asset_class="equity",
            geography="US",
            currency="USD",
            source="yahoo_finance",
        )
        with pytest.raises(AttributeError):
            data.ticker = "MSFT"  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════
#  Screening Models Tests
# ═══════════════════════════════════════════════════════════════════

class TestScreeningModels:
    def test_criterion_result_frozen(self):
        cr = CriterionResult(
            criterion="min_aum", expected="100M", actual="200M", passed=True, layer=1,
        )
        with pytest.raises(AttributeError):
            cr.passed = False  # type: ignore[misc]

    def test_instrument_screening_result_dict(self):
        result = InstrumentScreeningResult(
            instrument_id=uuid.uuid4(),
            instrument_type="fund",
            overall_status="PASS",
            score=0.75,
            failed_at_layer=None,
            layer_results=[
                CriterionResult("min_aum", "100M", "200M", True, 1),
            ],
            required_analysis_type="dd_report",
        )
        d = result.layer_results_dict
        assert len(d) == 1
        assert d[0]["criterion"] == "min_aum"
        assert d[0]["passed"] is True

    def test_screening_run_result(self):
        run = ScreeningRunResult(
            run_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            run_type="batch",
            instrument_count=0,
            config_hash="abc123",
        )
        assert run.results == []
