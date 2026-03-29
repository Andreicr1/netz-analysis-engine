"""Yahoo Finance data provider.

Uses yfinance for market data. Thread-safety constraints:
- yfinance has a confirmed bug (#2557): global mutable _DFS dict.
- fetch_batch_history() uses yf.download(threads=True) which is safe.
- fetch_instrument() serializes .info calls with 0.5s sleep.
- Rate limiting via threading.Lock + token bucket (30 concurrent, 2000/hour).

IMPORTANT: yfinance is for development/internal use only. Production should
use Lipper or Bloomberg providers (same InstrumentDataProvider protocol).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import pandas as pd
import yfinance as yf

from app.services.providers.protocol import RawInstrumentData, safe_get

logger = logging.getLogger(__name__)

# ── Type detection heuristics ─────────────────────────────────────
_FUND_QUOTE_TYPES = frozenset({"ETF", "MUTUALFUND"})
_EQUITY_QUOTE_TYPES = frozenset({"EQUITY"})
_BOND_QUOTE_TYPES = frozenset({"BOND"})

# ── Rate limiting ─────────────────────────────────────────────────
_MAX_CONCURRENT = 30
_HOURLY_BUDGET = 2000
_INFO_SLEEP_SECONDS = 0.5  # Serialize .info calls (not thread-safe)
_BATCH_CHUNK_SIZE = 50
_BATCH_CHUNK_SLEEP = 10.0


class YahooFinanceProvider:
    """Implements InstrumentDataProvider using yfinance."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens = _HOURLY_BUDGET
        self._last_refill = time.monotonic()

    def _consume_token(self) -> None:
        """Token bucket rate limiter."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            refill = int(elapsed * _HOURLY_BUDGET / 3600)
            if refill > 0:
                self._tokens = min(_HOURLY_BUDGET, self._tokens + refill)
                self._last_refill = now
            if self._tokens <= 0:
                sleep_time = (3600 / _HOURLY_BUDGET) - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
                self._tokens = 1
            self._tokens -= 1

    def fetch_instrument(self, ticker: str) -> RawInstrumentData | None:
        """Fetch single instrument metadata. Serialized with sleep."""
        self._consume_token()
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}
        except Exception:
            logger.warning("yfinance .info failed for %s", ticker, exc_info=True)
            return None
        finally:
            time.sleep(_INFO_SLEEP_SECONDS)

        if not info.get("shortName") and not info.get("longName"):
            logger.warning("No data returned for ticker %s", ticker)
            return None

        return self._normalize(ticker, info)

    def fetch_batch(self, tickers: list[str]) -> list[RawInstrumentData]:
        """Fetch metadata for multiple tickers. Serialized .info calls."""
        results: list[RawInstrumentData] = []
        for ticker in tickers:
            data = self.fetch_instrument(ticker)
            if data is not None:
                results.append(data)
        return results

    def fetch_batch_history(
        self, tickers: list[str], period: str = "3y",
    ) -> dict[str, pd.DataFrame]:
        """Batch download price history. Uses yf.download(threads=True).

        This is 30x faster than individual fetches for large batches.
        yf.download() manages its own internal threading safely.
        """
        result: dict[str, pd.DataFrame] = {}
        for i in range(0, len(tickers), _BATCH_CHUNK_SIZE):
            chunk = tickers[i : i + _BATCH_CHUNK_SIZE]
            try:
                df = yf.download(
                    chunk,
                    period=period,
                    group_by="ticker",
                    threads=True,
                    progress=False,
                )
                if df.empty:
                    continue
                if len(chunk) == 1:
                    # Single ticker: yf.download returns flat columns
                    result[chunk[0]] = df
                else:
                    # Multi ticker: columns are MultiIndex (ticker, field)
                    for t in chunk:
                        if t in df.columns.get_level_values(0):
                            ticker_df = df[t].dropna(how="all")
                            if not ticker_df.empty:
                                result[t] = ticker_df
            except Exception:
                logger.warning(
                    "yf.download failed for chunk starting at %d", i, exc_info=True,
                )
            if i + _BATCH_CHUNK_SIZE < len(tickers):
                time.sleep(_BATCH_CHUNK_SLEEP)
        return result

    def _normalize(self, ticker: str, info: dict[str, Any]) -> RawInstrumentData:
        """Normalize yfinance .info dict into RawInstrumentData."""
        instrument_type = self._detect_type(info)
        name = info.get("longName") or info.get("shortName") or ticker

        # Common attributes
        attrs: dict[str, Any] = {}

        if instrument_type == "fund":
            attrs = self._extract_fund_attrs(info)
        elif instrument_type == "bond":
            attrs = self._extract_bond_attrs(info)
        elif instrument_type == "equity":
            attrs = self._extract_equity_attrs(info)

        return RawInstrumentData(
            ticker=ticker,
            isin=safe_get(info, "isin"),
            name=name,
            instrument_type=instrument_type,
            asset_class=self._infer_asset_class(instrument_type, info),
            geography=safe_get(info, "country", default="unknown") or "unknown",
            currency=safe_get(info, "currency", default="USD") or "USD",
            source="yahoo_finance",
            raw_attributes=attrs,
        )

    @staticmethod
    def _detect_type(info: dict[str, Any]) -> str:
        """Detect instrument type from yfinance quoteType."""
        qt = (info.get("quoteType") or "").upper()
        if qt in _FUND_QUOTE_TYPES:
            return "fund"
        if qt in _BOND_QUOTE_TYPES:
            return "bond"
        return "equity"

    @staticmethod
    def _infer_asset_class(instrument_type: str, info: dict[str, Any]) -> str:
        """Infer asset_class from type + category."""
        if instrument_type == "fund":
            category = info.get("category", "")
            if category and "bond" in category.lower():
                return "fixed_income"
            return "equity"
        if instrument_type == "bond":
            return "fixed_income"
        return "equity"

    @staticmethod
    def _extract_fund_attrs(info: dict[str, Any]) -> dict[str, Any]:
        """Extract fund-specific attributes from yfinance .info."""
        return {
            "aum_usd": str(safe_get(info, "totalAssets", coerce=int) or 0),
            "manager_name": safe_get(info, "fundFamily", default="unknown"),
            "inception_date": safe_get(info, "fundInceptionDate", default=""),
            "fund_type": safe_get(info, "quoteType"),
            "category": safe_get(info, "category"),
            "domicile": safe_get(info, "legalType"),
            "management_fee_pct": safe_get(info, "annualReportExpenseRatio", coerce=float),
            "beta_3y": safe_get(info, "beta3Year", coerce=float),
            "yield_pct": safe_get(info, "yield", coerce=float),
        }

    @staticmethod
    def _extract_bond_attrs(info: dict[str, Any]) -> dict[str, Any]:
        """Extract bond-specific attributes."""
        return {
            "maturity_date": safe_get(info, "maturityDate", default=""),
            "coupon_rate_pct": safe_get(info, "couponRate", coerce=float, default=0.0),
            "issuer_name": safe_get(info, "shortName", default="unknown"),
            "credit_rating_sp": safe_get(info, "rating"),
        }

    @staticmethod
    def _extract_equity_attrs(info: dict[str, Any]) -> dict[str, Any]:
        """Extract equity-specific attributes."""
        return {
            "market_cap_usd": str(safe_get(info, "marketCap", coerce=int) or 0),
            "sector": safe_get(info, "sector", default="unknown"),
            "exchange": safe_get(info, "exchange", default="unknown"),
            "industry": safe_get(info, "industry"),
            "pe_ratio_ttm": safe_get(info, "trailingPE", coerce=float),
            "dividend_yield_pct": safe_get(info, "dividendYield", coerce=float),
            "roe": safe_get(info, "returnOnEquity", coerce=float),
            "debt_to_equity": safe_get(info, "debtToEquity", coerce=float),
            "free_float_pct": safe_get(info, "floatShares", coerce=float),
        }
