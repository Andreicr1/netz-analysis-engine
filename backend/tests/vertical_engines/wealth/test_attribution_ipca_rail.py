"""Tests for IPCA attribution rail (≥ 5 dispatcher tests)."""
import json
from datetime import date
from unittest.mock import patch, MagicMock
from uuid import uuid4

import numpy as np
import pytest

from vertical_engines.wealth.attribution.models import (
    AttributionRequest,
    HoldingsBasedResult,
    BenchmarkProxyResult,
    BenchmarkResolution,
    BrinsonResult,
    FundAttributionResult,
    RailBadge,
)
from vertical_engines.wealth.attribution.service import compute_fund_attribution
from quant_engine.ipca.fit import IPCAFit


@pytest.fixture
def mock_request():
    return AttributionRequest(
        fund_instrument_id=uuid4(),
        asof=date(2026, 4, 19),
        fund_asset_class="Equity",
        fund_cik="0001234567"
    )


@pytest.fixture
def mock_ipca_fit():
    return IPCAFit(
        gamma=np.random.randn(6, 3),
        factor_returns=np.random.randn(3, 20),
        K=3,
        intercept=False,
        r_squared=0.8,
        oos_r_squared=0.6,
        converged=True,
        n_iterations=50,
        dates=None,
    )


@pytest.mark.asyncio
async def test_ipca_rail_wins_when_oos_r2_high(mock_request):
    """1. IPCA rail wins when OOS R² ≥ 0.50 and HOLDINGS unavailable."""
    with patch("vertical_engines.wealth.attribution.service._run_ipca_rail") as mock_ipca:
        mock_ipca.return_value = MagicMock(
            factor_names=["Size", "Value", "Momentum"],
            factor_exposures=[0.1, 0.2, 0.3],
            factor_returns_contribution=[0.01, 0.02, 0.03],
            alpha=0.01,
            confidence=0.6,
        )
        
        # Mock holdings to return None
        async def mock_holdings(*args, **kwargs):
            return None
            
        res = await compute_fund_attribution(
            mock_request, db="mock_db", holdings_fetch=mock_holdings
        )
        
        assert res.badge == RailBadge.RAIL_IPCA
        assert res.ipca is not None


@pytest.mark.asyncio
async def test_ipca_rail_skipped_when_oos_r2_low(mock_request):
    """2. IPCA rail skipped when OOS R² < 0.50."""
    with patch("vertical_engines.wealth.attribution.service._run_ipca_rail") as mock_ipca:
        mock_ipca.return_value = None
        
        # Mock holdings to return None
        async def mock_holdings(*args, **kwargs):
            return None
            
        # Mock proxy to return None
        async def mock_proxy(*args, **kwargs):
            return None
            
        # Mock returns
        async def mock_returns(*args, **kwargs):
            return np.array([0.01]), np.array([[0.01]]), ("SPY",)
            
        res = await compute_fund_attribution(
            mock_request, db="mock_db", holdings_fetch=mock_holdings,
            proxy_fetch=mock_proxy, returns_fetch=mock_returns
        )
        
        assert res.badge != RailBadge.RAIL_IPCA


@pytest.mark.asyncio
async def test_priority_order_holdings_first(mock_request):
    """3. Priority order: HOLDINGS → IPCA → PROXY → RETURNS."""
    with patch("vertical_engines.wealth.attribution.service._run_ipca_rail") as mock_ipca:
        mock_ipca.return_value = MagicMock()
        
        async def mock_holdings(*args, **kwargs):
            return HoldingsBasedResult(
                sectors=(), period_of_report=None, coverage_pct=0.9,
                confidence=0.9, holdings_count=100, degraded=False
            )
            
        res = await compute_fund_attribution(
            mock_request, db="mock_db", holdings_fetch=mock_holdings
        )
        
        assert res.badge == RailBadge.RAIL_HOLDINGS
        mock_ipca.assert_not_called()


@pytest.mark.asyncio
async def test_badge_correctly_set_to_rail_ipca(mock_request):
    """4. Badge correctly set to RAIL_IPCA."""
    with patch("vertical_engines.wealth.attribution.service._run_ipca_rail") as mock_ipca:
        mock_ipca.return_value = MagicMock(
            factor_names=["Size", "Value"],
            factor_exposures=[0.1, 0.2],
            factor_returns_contribution=[0.01, 0.02],
            alpha=0.01,
            confidence=0.6,
        )
        
        async def mock_holdings(*args, **kwargs):
            return None
            
        res = await compute_fund_attribution(
            mock_request, db="mock_db", holdings_fetch=mock_holdings
        )
        
        assert res.badge == RailBadge.RAIL_IPCA
        assert res.metadata["n_factors"] == "2"


@pytest.mark.asyncio
async def test_fund_with_no_characteristics(mock_request):
    """5. Fund with no characteristics → rail returns None, dispatcher falls through."""
    with patch("vertical_engines.wealth.attribution.service._run_ipca_rail") as mock_ipca:
        mock_ipca.return_value = None
        
        async def mock_holdings(*args, **kwargs):
            return None
            
        async def mock_proxy(*args, **kwargs):
            return BenchmarkProxyResult(
                resolution=BenchmarkResolution("ticker"),
                brinson=BrinsonResult(0, 0, 0, 0, ()),
                confidence=0.8,
                degraded=False
            )
            
        res = await compute_fund_attribution(
            mock_request, db="mock_db", holdings_fetch=mock_holdings, proxy_fetch=mock_proxy
        )
        
        assert res.badge == RailBadge.RAIL_PROXY
