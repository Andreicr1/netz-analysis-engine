"""FE fundinfo instrument data provider.

Implements InstrumentDataProvider protocol for production fund data.
Extended async methods provide richer data (risk, performance, exposures, fees)
beyond what the sync protocol requires.

The sync protocol methods (fetch_instrument, fetch_batch, fetch_batch_history)
wrap async calls via asyncio.to_thread / event loop bridging, matching the
pattern established by Yahoo Finance provider.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
import structlog

from app.services.providers.fefundinfo_client import FEFundInfoClient
from app.services.providers.protocol import RawInstrumentData, safe_get

logger = structlog.get_logger()


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from sync context.

    Tries to use the running event loop (via asyncio.run_coroutine_threadsafe)
    or creates a new one if none exists. This matches the pattern used by
    the EDGAR edgartools integration.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're inside an async context (e.g., called from to_thread)
        # Create a new loop in this thread
        return asyncio.run(coro)
    return asyncio.run(coro)


class FEFundInfoProvider:
    """Implements InstrumentDataProvider + extended async methods for FE fundinfo.

    Args:
        client: Configured FEFundInfoClient instance.

    """

    def __init__(self, client: FEFundInfoClient):
        self._client = client

    # ── InstrumentDataProvider protocol (sync) ──────────────────

    def fetch_instrument(self, ticker: str) -> RawInstrumentData | None:
        """Fetch single instrument by ISIN. Sync wrapper over async client."""
        try:
            instruments = _run_async(self._client.get_fund_information([ticker]))
            if not instruments:
                return None
            return self._normalize(ticker, instruments[0])
        except Exception:
            logger.warning("fefundinfo fetch_instrument failed for %s", ticker, exc_info=True)
            return None

    def fetch_batch(self, tickers: list[str]) -> list[RawInstrumentData]:
        """Batch fetch instrument metadata. Tickers are ISINs."""
        try:
            instruments = _run_async(self._client.get_fund_information(tickers))
        except Exception:
            logger.warning("fefundinfo fetch_batch failed", exc_info=True)
            return []

        results: list[RawInstrumentData] = []
        isin_to_data: dict[str, dict[str, Any]] = {}
        for inst in instruments:
            isin = inst.get("Isin") or inst.get("isin") or ""
            if isin:
                isin_to_data[isin] = inst

        for ticker in tickers:
            data = isin_to_data.get(ticker)
            if data:
                normalized = self._normalize(ticker, data)
                if normalized:
                    results.append(normalized)
        return results

    def fetch_batch_history(
        self, tickers: list[str], period: str = "3y",
    ) -> dict[str, pd.DataFrame]:
        """Fetch NAV time series via Dynamic Data Series API.

        Returns dict mapping ISIN to DataFrame with columns: Date, Close.
        """
        try:
            series_data = _run_async(
                self._client.get_nav_series(tickers, series_type=2, period="Daily"),
            )
        except Exception:
            logger.warning("fefundinfo fetch_batch_history failed", exc_info=True)
            return {}

        result: dict[str, pd.DataFrame] = {}
        for item in series_data:
            history = item.get("HistoryData", {})
            instruments = history.get("Instrument", [])
            for inst in instruments:
                isin = inst.get("Isin", "")
                if not isin:
                    continue
                series_list = inst.get("SeriesList", [])
                if not series_list:
                    continue
                series_entries = series_list[0].get("SeriesData", [])
                if not series_entries:
                    continue
                rows = []
                for entry in series_entries:
                    date_val = entry.get("seriesData") or entry.get("SeriesDate")
                    value = entry.get("seriesValue") or entry.get("SeriesValue")
                    if date_val and value is not None:
                        try:
                            rows.append({"Date": str(date_val), "Close": float(value)})
                        except (ValueError, TypeError):
                            continue
                if rows:
                    df = pd.DataFrame(rows)
                    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
                    df = df.dropna(subset=["Date"])
                    df = df.set_index("Date").sort_index()
                    result[isin] = df
        return result

    # ── Extended async methods (FE fundinfo specific) ───────────

    async def fetch_risk_profile(
        self, isin: str, currency: str = "USD",
    ) -> dict[str, Any]:
        """Fetch risk/analytics ratios for a single fund."""
        try:
            data = await self._client.get_analytics([isin])
            return data[0] if data else {}
        except Exception:
            logger.warning("fefundinfo fetch_risk_profile failed", isin=isin, exc_info=True)
            return {}

    async def fetch_performance_summary(
        self, isin: str, currency: str = "USD",
    ) -> dict[str, Any]:
        """Fetch cumulative + annualised performance."""
        try:
            cumulative, annualised = await asyncio.gather(
                self._client.get_cumulative_performance_v2([isin], currency=currency),
                self._client.get_annualised_performance([isin], currency=currency),
                return_exceptions=True,
            )
            return {
                "cumulative": cumulative[0] if isinstance(cumulative, list) and cumulative else {},
                "annualised": annualised[0] if isinstance(annualised, list) and annualised else {},
            }
        except Exception:
            logger.warning("fefundinfo fetch_performance_summary failed", exc_info=True)
            return {}

    async def fetch_fees(self, isin: str) -> dict[str, Any]:
        """Fetch fee structure for a fund."""
        try:
            data = await self._client.get_fees([isin])
            return data[0] if data else {}
        except Exception:
            logger.warning("fefundinfo fetch_fees failed", exc_info=True)
            return {}

    async def fetch_exposures(self, isin: str) -> dict[str, Any]:
        """Fetch geographic, sector, currency, and asset class exposures."""
        try:
            data = await self._client.get_exposures_breakdown([isin])
            return data[0] if data else {}
        except Exception:
            logger.warning("fefundinfo fetch_exposures failed", exc_info=True)
            return {}

    async def fetch_holdings(self, isin: str) -> list[dict[str, Any]]:
        """Fetch full holdings breakdown."""
        try:
            data = await self._client.get_holdings_breakdown([isin])
            return data
        except Exception:
            logger.warning("fefundinfo fetch_holdings failed", exc_info=True)
            return []

    async def fetch_fund_snapshot(
        self, isin: str, currency: str = "USD",
    ) -> dict[str, Any]:
        """Aggregate call: instrument + risk + performance + fees + AUM.

        Used by DD reports and screener for complete fund profile.
        """
        try:
            instrument, risk, performance, fees, aum = await asyncio.gather(
                self._client.get_fund_information([isin]),
                self._client.get_analytics([isin]),
                self._client.get_cumulative_performance_v2([isin], currency=currency),
                self._client.get_fees([isin]),
                self._client.get_aum([isin]),
                return_exceptions=True,
            )
            return {
                "instrument": instrument[0] if isinstance(instrument, list) and instrument else {},
                "risk": risk[0] if isinstance(risk, list) and risk else {},
                "performance": performance[0] if isinstance(performance, list) and performance else {},
                "fees": fees[0] if isinstance(fees, list) and fees else {},
                "aum": aum[0] if isinstance(aum, list) and aum else {},
            }
        except Exception:
            logger.warning("fefundinfo fetch_fund_snapshot failed", exc_info=True)
            return {}

    # ── Normalization ───────────────────────────────────────────

    @staticmethod
    def _normalize(isin: str, data: dict[str, Any]) -> RawInstrumentData | None:
        """Normalize FE fundinfo instrument data into RawInstrumentData."""
        name = (
            safe_get(data, "ShareClassName")
            or safe_get(data, "InstrumentName")
            or safe_get(data, "Name")
            or isin
        )
        currency = safe_get(data, "CurrencyCode") or safe_get(data, "Currency") or "USD"
        geography = safe_get(data, "DomicileCountry") or safe_get(data, "Country") or "unknown"

        # Extract fund-relevant attributes
        attrs: dict[str, Any] = {
            "aum_usd": safe_get(data, "Aum", coerce=str),
            "manager_name": safe_get(data, "PortfolioManagerName"),
            "inception_date": safe_get(data, "LaunchDate"),
            "fund_type": safe_get(data, "InstrumentTypeName"),
            "category": safe_get(data, "SectorName"),
            "domicile": safe_get(data, "DomicileCountry"),
            "share_class_name": safe_get(data, "ShareClassName"),
            "citicode": safe_get(data, "CitiCode") or safe_get(data, "Citicode"),
            "instrument_code": safe_get(data, "InstrumentCode"),
        }
        # Remove None values to keep attrs clean
        attrs = {k: v for k, v in attrs.items() if v is not None}

        asset_class = "equity"
        sector = (safe_get(data, "SectorName") or "").lower()
        if "bond" in sector or "fixed" in sector or "credit" in sector:
            asset_class = "fixed_income"
        elif "money" in sector or "cash" in sector:
            asset_class = "money_market"
        elif "property" in sector or "real" in sector:
            asset_class = "real_estate"
        elif "commodity" in sector or "gold" in sector:
            asset_class = "commodities"
        elif "multi" in sector or "mixed" in sector:
            asset_class = "multi_asset"

        return RawInstrumentData(
            ticker=isin,
            isin=isin,
            name=name,
            instrument_type="fund",
            asset_class=asset_class,
            geography=geography,
            currency=currency,
            source="fefundinfo",
            raw_attributes=attrs,
        )
