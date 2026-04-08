#!/usr/bin/env python3
"""
Massive API — Proof of Concept (POC)

Validates coverage for the Netz Analysis Engine migration from YFinance.
Tests: equities, ETFs, and mutual funds (the critical gap).

Usage:
    MASSIVE_API_KEY=your_key python massive_poc.py

Or edit MASSIVE_API_KEY below.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta

# ── Configuration ────────────────────────────────────────────────────

MASSIVE_API_KEY = os.environ.get("MASSIVE_API_KEY", "COLE_SUA_API_KEY_AQUI")
BASE_URL = "https://api.massive.com"

# Test tickers — mixed asset classes matching our instruments_universe
TEST_TICKERS = {
    # Equities (should work)
    "AAPL": "equity",
    "MSFT": "equity",
    # ETFs (should work — exchange-traded)
    "SPY": "etf",
    "IVV": "etf",
    "AGG": "etf_bond",
    "BND": "etf_bond",
    # Mutual Funds (THE critical test — OTC/NAV-based, not exchange-traded)
    "OAKMX": "mutual_fund",   # Oakmark Fund (from our dev_seed)
    "DODGX": "mutual_fund",   # Dodge & Cox Stock Fund (from our dev_seed)
    "PRWCX": "mutual_fund",   # T. Rowe Price Capital Appreciation
    "VFINX": "mutual_fund",   # Vanguard 500 Index Fund
}

# Date range for historical test
END_DATE = date.today()
START_DATE = END_DATE - timedelta(days=30)


# ── HTTP Client (zero dependencies — stdlib only) ────────────────────

import urllib.error
import urllib.parse
import urllib.request


@dataclass
class ApiResult:
    ticker: str
    asset_type: str
    endpoint: str
    status_code: int
    latency_ms: float
    result_count: int
    sample: dict | None
    error: str | None


def api_get(path: str, params: dict | None = None) -> tuple[int, dict, float]:
    """GET request to Massive API. Returns (status_code, json_body, latency_ms)."""
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    # Massive uses apiKey query param (per docs)
    sep = "&" if "?" in url else "?"
    url += f"{sep}apiKey={MASSIVE_API_KEY}"

    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            latency = (time.perf_counter() - t0) * 1000
            body = json.loads(resp.read().decode())
            return resp.status, body, latency
    except urllib.error.HTTPError as e:
        latency = (time.perf_counter() - t0) * 1000
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {"error": str(e)}
        return e.code, body, latency
    except Exception as e:
        latency = (time.perf_counter() - t0) * 1000
        return 0, {"error": str(e)}, latency


# ── Test Suite ────────────────────────────────────────────────────────

def test_aggregates(ticker: str, asset_type: str) -> ApiResult:
    """Test: GET /v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}
    This is the main historical OHLCV endpoint — equivalent to yf.download().
    """
    path = f"/v2/aggs/ticker/{ticker}/range/1/day/{START_DATE}/{END_DATE}"
    status, body, latency = api_get(path, {"adjusted": "true", "sort": "asc", "limit": "50"})

    results = body.get("results", [])
    sample = results[0] if results else None
    error = body.get("error") or body.get("message") if status != 200 else None

    return ApiResult(
        ticker=ticker, asset_type=asset_type, endpoint="aggregates",
        status_code=status, latency_ms=latency, result_count=len(results),
        sample=sample, error=error,
    )


def test_ticker_details(ticker: str, asset_type: str) -> ApiResult:
    """Test: GET /v3/reference/tickers/{ticker}
    Metadata endpoint — equivalent to yf.Ticker().info.
    """
    path = f"/v3/reference/tickers/{ticker}"
    status, body, latency = api_get(path)

    result = body.get("results")
    error = body.get("error") or body.get("message") if status != 200 else None

    return ApiResult(
        ticker=ticker, asset_type=asset_type, endpoint="ticker_details",
        status_code=status, latency_ms=latency, result_count=1 if result else 0,
        sample=result, error=error,
    )


def test_snapshot(ticker: str, asset_type: str) -> ApiResult:
    """Test: GET /v2/snapshot/locale/us/markets/stocks/tickers/{ticker}
    Real-time snapshot — equivalent to yf.Ticker().fast_info.
    """
    path = f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}"
    status, body, latency = api_get(path)

    result = body.get("ticker")
    error = body.get("error") or body.get("message") if status != 200 else None

    return ApiResult(
        ticker=ticker, asset_type=asset_type, endpoint="snapshot",
        status_code=status, latency_ms=latency, result_count=1 if result else 0,
        sample=result, error=error,
    )


def test_ticker_types() -> ApiResult:
    """Test: GET /v3/reference/tickers/types
    Lists all supported ticker types — check if MUTUALFUND/OEF exists.
    """
    path = "/v3/reference/tickers/types"
    status, body, latency = api_get(path)

    results = body.get("results", [])
    error = body.get("error") or body.get("message") if status != 200 else None

    return ApiResult(
        ticker="N/A", asset_type="reference", endpoint="ticker_types",
        status_code=status, latency_ms=latency, result_count=len(results),
        sample={"types": results[:20]} if results else None, error=error,
    )


# ── Report ────────────────────────────────────────────────────────────

def print_header(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def print_result(r: ApiResult) -> None:
    status_icon = "OK" if r.status_code == 200 and r.result_count > 0 else "FAIL"
    if r.status_code == 200 and r.result_count == 0:
        status_icon = "EMPTY"
    print(f"\n  [{status_icon}] {r.ticker} ({r.asset_type}) — {r.endpoint}")
    print(f"       HTTP {r.status_code} | {r.latency_ms:.0f}ms | {r.result_count} results")
    if r.error:
        print(f"       ERROR: {r.error}")
    if r.sample:
        sample_str = json.dumps(r.sample, indent=2, default=str)
        # Truncate long samples
        lines = sample_str.split("\n")
        if len(lines) > 12:
            lines = lines[:12] + ["  ... (truncated)"]
        for line in lines:
            print(f"       {line}")


def main() -> None:
    if MASSIVE_API_KEY == "COLE_SUA_API_KEY_AQUI":
        print("ERROR: Set MASSIVE_API_KEY environment variable or edit the script.")
        print("Usage: MASSIVE_API_KEY=your_key python massive_poc.py")
        sys.exit(1)

    print_header("MASSIVE API — Proof of Concept")
    print(f"  Base URL: {BASE_URL}")
    print(f"  Date range: {START_DATE} → {END_DATE}")
    print(f"  Tickers: {len(TEST_TICKERS)}")

    # ── Test 0: Ticker Types Reference ─────────────────────────────
    print_header("TEST 0: Supported Ticker Types")
    r = test_ticker_types()
    print_result(r)

    # ── Test 1: Historical Aggregates (OHLCV) ──────────────────────
    print_header("TEST 1: Historical Aggregates (Daily OHLCV)")
    agg_results: dict[str, ApiResult] = {}
    for ticker, asset_type in TEST_TICKERS.items():
        r = test_aggregates(ticker, asset_type)
        agg_results[ticker] = r
        print_result(r)
        time.sleep(0.2)  # Rate limit courtesy

    # ── Test 2: Ticker Details (Metadata) ──────────────────────────
    print_header("TEST 2: Ticker Details (Metadata)")
    detail_results: dict[str, ApiResult] = {}
    for ticker, asset_type in TEST_TICKERS.items():
        r = test_ticker_details(ticker, asset_type)
        detail_results[ticker] = r
        print_result(r)
        time.sleep(0.2)

    # ── Test 3: Real-Time Snapshot ─────────────────────────────────
    print_header("TEST 3: Real-Time Snapshot")
    snap_results: dict[str, ApiResult] = {}
    for ticker, asset_type in TEST_TICKERS.items():
        r = test_snapshot(ticker, asset_type)
        snap_results[ticker] = r
        print_result(r)
        time.sleep(0.2)

    # ── Summary Matrix ─────────────────────────────────────────────
    print_header("COVERAGE MATRIX")
    print(f"\n  {'Ticker':<10} {'Type':<14} {'Aggregates':<14} {'Details':<14} {'Snapshot':<14}")
    print(f"  {'-'*10} {'-'*14} {'-'*14} {'-'*14} {'-'*14}")

    for ticker, asset_type in TEST_TICKERS.items():
        def status(r: ApiResult) -> str:
            if r.status_code == 200 and r.result_count > 0:
                return f"OK ({r.result_count})"
            if r.status_code == 200:
                return "EMPTY"
            return f"ERR {r.status_code}"

        agg = status(agg_results[ticker])
        det = status(detail_results[ticker])
        snap = status(snap_results[ticker])
        print(f"  {ticker:<10} {asset_type:<14} {agg:<14} {det:<14} {snap:<14}")

    # ── Latency Summary ────────────────────────────────────────────
    all_results = list(agg_results.values()) + list(detail_results.values()) + list(snap_results.values())
    ok_results = [r for r in all_results if r.status_code == 200]
    if ok_results:
        avg_lat = sum(r.latency_ms for r in ok_results) / len(ok_results)
        max_lat = max(r.latency_ms for r in ok_results)
        min_lat = min(r.latency_ms for r in ok_results)
        print("\n  Latency (successful requests):")
        print(f"    Min: {min_lat:.0f}ms  Avg: {avg_lat:.0f}ms  Max: {max_lat:.0f}ms")

    # ── Verdict ────────────────────────────────────────────────────
    print_header("VERDICT")
    mf_aggs = [agg_results[t] for t, at in TEST_TICKERS.items() if at == "mutual_fund"]
    mf_ok = sum(1 for r in mf_aggs if r.status_code == 200 and r.result_count > 0)
    mf_total = len(mf_aggs)

    etf_aggs = [agg_results[t] for t, at in TEST_TICKERS.items() if at.startswith("etf")]
    etf_ok = sum(1 for r in etf_aggs if r.status_code == 200 and r.result_count > 0)
    etf_total = len(etf_aggs)

    eq_aggs = [agg_results[t] for t, at in TEST_TICKERS.items() if at == "equity"]
    eq_ok = sum(1 for r in eq_aggs if r.status_code == 200 and r.result_count > 0)
    eq_total = len(eq_aggs)

    print(f"\n  Equities:     {eq_ok}/{eq_total} tickers with OHLCV data")
    print(f"  ETFs:         {etf_ok}/{etf_total} tickers with OHLCV data")
    print(f"  Mutual Funds: {mf_ok}/{mf_total} tickers with OHLCV data")

    if mf_ok == 0:
        print("\n  !! CRITICAL: Massive does NOT return data for mutual fund tickers.")
        print("     This confirms the documented limitation — Massive covers exchange-traded")
        print("     instruments only (stocks, ETFs, options, forex, crypto, indices).")
        print("     Mutual fund NAV pricing requires a separate provider (Morningstar, LSEG,")
        print("     FEFundInfo, or SEC N-PORT-derived NAV).")
    elif mf_ok < mf_total:
        print(f"\n  !! PARTIAL: Massive returns data for {mf_ok}/{mf_total} mutual funds.")
        print("     Coverage is incomplete — need secondary provider for gaps.")
    else:
        print(f"\n  ++ FULL: Massive covers all {mf_total} mutual fund tickers tested.")

    print()


if __name__ == "__main__":
    main()
