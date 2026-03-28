"""Real data extraction tests for SEC Data Providers.

Exercises the services against live SEC APIs (IAPD, EDGAR, EFTS) and the
production database. Finds bugs that mock-based tests cannot catch.

Usage:
    python backend/scripts/validate_sec_real_data.py
"""
from __future__ import annotations

import asyncio
import os
import ssl
import sys
import time
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
_REPO_ROOT = os.path.dirname(_BACKEND_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_REPO_ROOT, ".env"))
except ImportError:
    pass

if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

os.environ.setdefault("EDGAR_IDENTITY", "Netz Analysis Engine tech@netzco.com")

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.shared.models import Sec13fDiff as Sec13fDiffModel
from app.shared.models import Sec13fHolding as Sec13fHoldingModel
from data_providers.sec.adv_service import AdvService
from data_providers.sec.institutional_service import InstitutionalService, _classify_filer_type
from data_providers.sec.models import ThirteenFDiff, ThirteenFHolding
from data_providers.sec.shared import resolve_cik
from data_providers.sec.thirteenf_service import ThirteenFService

# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/netz",
)

_connect_args: dict[str, Any] = {}
if "sslmode=require" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("?sslmode=require", "").replace("&sslmode=require", "")
    _ctx = ssl.create_default_context()
    _ctx.check_hostname = False
    _ctx.verify_mode = ssl.CERT_NONE
    _connect_args["ssl"] = _ctx

_engine = create_async_engine(DATABASE_URL, echo=False, connect_args=_connect_args)
_session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def _get_session():
    async with _session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------

_bugs: list[str] = []
_warnings: list[str] = []


def bug(msg: str) -> None:
    print(f"    !! BUG: {msg}")
    _bugs.append(msg)


def warn(msg: str) -> None:
    print(f"    ?? WARN: {msg}")
    _warnings.append(msg)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

# CIKs to clean up at the end
_ciks_to_cleanup: list[str] = []


async def test_iapd_search(adv: AdvService) -> None:
    print("\n--- 1. IAPD Search (search_managers) ---")
    queries = ["Ares Capital", "Blackstone", "Apollo Global"]
    for query in queries:
        t0 = time.time()
        results = await adv.search_managers(query, limit=5)
        elapsed = time.time() - t0
        print(f"  [{len(results)} results] query=\"{query}\" ({elapsed:.1f}s)")
        for r in results[:2]:
            print(f"    CRD={r.crd_number} name={r.firm_name} status={r.registration_status} state={r.state}")
        if not results:
            bug(f"IAPD search for '{query}' returned 0 results")


async def test_13f_holdings(tf: ThirteenFService) -> dict[str, Any]:
    """Returns context dict for downstream tests."""
    print("\n--- 2. 13F Holdings (fetch_holdings via edgartools) ---")
    # Blackstone is a known large 13F filer
    blackstone_cik = "1393818"
    _ciks_to_cleanup.append(blackstone_cik)

    t0 = time.time()
    holdings = await tf.fetch_holdings(
        blackstone_cik, quarters=1, force_refresh=True, staleness_ttl_days=9999,
    )
    elapsed = time.time() - t0
    print(f"  Blackstone (CIK={blackstone_cik}): {len(holdings)} holdings ({elapsed:.1f}s)")

    if not holdings:
        bug("fetch_holdings returned 0 for Blackstone (known 13F filer)")
        return {"cik": blackstone_cik, "holdings": [], "report_date": None}

    h = holdings[0]
    print(f"    Sample: cusip={h.cusip} issuer={h.issuer_name}")
    print(f"      shares={h.shares}  value=${h.market_value}  class={h.asset_class}")
    print(f"      report_date={h.report_date}  filing_date={h.filing_date}")

    # Validate market_value x1000 multiplier
    if h.market_value is not None and h.market_value < 1000:
        bug(f"market_value={h.market_value} looks too small -- x1000 multiplier may be missing")

    # Validate types
    if not isinstance(h, ThirteenFHolding):
        bug(f"holding is {type(h).__name__}, expected ThirteenFHolding")

    # Check report_date is ISO format
    try:
        date.fromisoformat(h.report_date)
    except ValueError:
        bug(f"report_date '{h.report_date}' is not valid ISO date")

    return {
        "cik": blackstone_cik,
        "holdings": holdings,
        "report_date": date.fromisoformat(holdings[0].report_date),
    }


async def test_sector_aggregation(tf: ThirteenFService, ctx: dict[str, Any]) -> None:
    if not ctx["report_date"]:
        print("\n--- 3. Sector Aggregation --- SKIPPED (no holdings)")
        return

    print(f"\n--- 3. Sector Aggregation (report_date={ctx['report_date']}) ---")
    sectors = await tf.get_sector_aggregation(ctx["cik"], ctx["report_date"])
    total_w = sum(sectors.values())
    print(f"  {len(sectors)} asset classes, weight_sum={total_w:.6f}")
    for s, w in list(sectors.items())[:5]:
        pct = f"{w:.4%}"
        print(f"    {s}: {pct}")

    if abs(total_w - 1.0) > 0.01:
        bug(f"sector weight sum {total_w} != 1.0")

    if not sectors:
        bug("sector aggregation returned empty for Blackstone")


async def test_concentration(tf: ThirteenFService, ctx: dict[str, Any]) -> None:
    if not ctx["report_date"]:
        print("\n--- 4. Concentration Metrics --- SKIPPED (no holdings)")
        return

    print("\n--- 4. Concentration Metrics ---")
    metrics = await tf.get_concentration_metrics(ctx["cik"], ctx["report_date"])

    for key in ("hhi", "top_10_concentration", "position_count"):
        if key not in metrics:
            bug(f"missing '{key}' in concentration metrics")

    hhi = metrics.get("hhi", 0)
    top10 = metrics.get("top_10_concentration", 0)
    pos = metrics.get("position_count", 0)
    print(f"  HHI={hhi:.6f}  top10={top10:.4%}  positions={int(pos)}")

    if hhi < 0 or hhi > 1:
        bug(f"HHI={hhi} out of [0,1] range")
    if top10 < 0 or top10 > 1:
        bug(f"top_10_concentration={top10} out of [0,1] range")


async def test_compute_diffs(tf: ThirteenFService, ctx: dict[str, Any]) -> None:
    print("\n--- 5. Compute Diffs (2 quarters) ---")
    cik = ctx["cik"]

    # Fetch 2 quarters
    holdings = await tf.fetch_holdings(
        cik, quarters=2, force_refresh=True, staleness_ttl_days=9999,
    )
    report_dates = sorted(set(h.report_date for h in holdings))
    print(f"  Available report dates: {report_dates}")

    if len(report_dates) < 2:
        warn(f"Only {len(report_dates)} quarter(s) -- skipping diff computation")
        return

    q_from = date.fromisoformat(report_dates[-2])
    q_to = date.fromisoformat(report_dates[-1])
    diffs = await tf.compute_diffs(cik, q_from, q_to)
    print(f"  Diffs ({q_from} -> {q_to}): {len(diffs)} position changes")

    if not diffs:
        warn("compute_diffs returned empty -- unusual for a large filer across quarters")
        return

    # Action distribution
    actions: dict[str, int] = {}
    for d in diffs:
        actions[d.action] = actions.get(d.action, 0) + 1
    print(f"  Actions: {actions}")

    # Sample
    d = diffs[0]
    print(f"  Sample: {d.issuer_name} action={d.action} delta={d.shares_delta}")
    print(f"    weight_before={d.weight_before} weight_after={d.weight_after}")

    # Validate all diffs are ThirteenFDiff
    for d in diffs:
        if not isinstance(d, ThirteenFDiff):
            bug(f"diff is {type(d).__name__}, expected ThirteenFDiff")
            break

    # Validate action values
    valid_actions = {"NEW_POSITION", "INCREASED", "DECREASED", "EXITED", "UNCHANGED"}
    for d in diffs:
        if d.action not in valid_actions:
            bug(f"invalid action '{d.action}' for {d.issuer_name}")
            break

    # Weight invariant: weight_after sums should ~= 1.0
    wa_sum = sum(d.weight_after for d in diffs if d.weight_after is not None)
    if abs(wa_sum - 1.0) > 0.02:
        bug(f"weight_after sum = {wa_sum}, expected ~= 1.0")
    else:
        print(f"  weight_after sum = {wa_sum:.6f} (OK)")


async def test_institutional_discovery(inst: InstitutionalService) -> None:
    print("\n--- 6. Institutional Filer Discovery (EFTS) ---")
    t0 = time.time()
    filers = await inst.discover_institutional_filers(limit=10)
    elapsed = time.time() - t0
    print(f"  Found {len(filers)} filers ({elapsed:.1f}s)")

    for f in filers[:5]:
        name = f["filer_name"][:60]
        print(f"    CIK={f['cik']}  type={f['filer_type']}  name={name}")

    if not filers:
        bug("institutional filer discovery returned 0 results from EFTS")

    # Validate structure
    for f in filers:
        for key in ("cik", "filer_name", "filer_type"):
            if key not in f:
                bug(f"missing '{key}' in filer dict")
                break


async def test_cik_resolution_real() -> None:
    print("\n--- 7. CIK Resolution (real API -- all 3 tiers) ---")
    cases = [
        # (name, ticker, expected_method_or_none)
        ("Ares Capital Corporation", "ARCC", "ticker"),
        ("Blackstone Inc", "BX", "ticker"),
        ("Blue Owl Capital", None, "fuzzy"),
        ("KKR & Co Inc", "KKR", "ticker"),
        ("KKR & Co", None, None),  # may or may not resolve
        ("Oaktree Capital Management", None, None),
        ("Golub Capital", None, None),
        ("Owl Rock Capital", None, None),
        ("Totally Fake Entity ZZZZZZZ", None, "not_found"),
    ]

    for name, ticker, expected_method in cases:
        r = resolve_cik(name, ticker=ticker)
        status = "OK" if r.cik else "MISS"
        ticker_str = ticker or "-"
        print(f"  [{status}] {name} (ticker={ticker_str})")
        print(f"    CIK={r.cik}  method={r.method}  confidence={r.confidence:.2f}  matched={r.company_name}")

        if expected_method == "not_found" and r.cik is not None:
            bug(f"Expected not_found for fake entity, got CIK={r.cik}")
        elif expected_method and expected_method != "not_found" and r.method != expected_method:
            warn(f"Expected method={expected_method} but got {r.method}")


async def test_adv_ingest_and_fetch(adv: AdvService) -> None:
    """Test real-data round trip: ingest from SEC FOIA subset, then fetch."""
    print("\n--- 8. ADV Ingest + Fetch Round-Trip ---")

    # Use a real CRD: Ares Management = 108105
    ares_crd = "108105"

    # First check if already in DB (from a previous ingest)
    mgr = await adv.fetch_manager(ares_crd)
    if mgr:
        print(f"  Ares Management already in DB: CRD={mgr.crd_number} name={mgr.firm_name}")
        print(f"    AUM total=${mgr.aum_total}  state={mgr.state}  status={mgr.registration_status}")
    else:
        print(f"  Ares Management (CRD={ares_crd}) not in DB yet -- this is expected pre-ingest")

    # Ingest a real-looking CSV row for Ares
    import tempfile
    csv_content = (
        "CRD Number,Primary Business Name,SEC#,Status,Q5F2A,Q5F2B,Q5F2C,Main Office State,Main Office Country\n"
        f"{ares_crd},Ares Management LLC,801-34942,ACTIVE,282000000000,0,282000000000,CA,US\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(csv_content)
        tmp_path = f.name

    try:
        count = await adv.ingest_bulk_adv(csv_path=tmp_path)
        print(f"  Ingested {count} manager(s)")
    finally:
        os.unlink(tmp_path)

    # Fetch back
    mgr = await adv.fetch_manager(ares_crd)
    if mgr is None:
        bug("fetch_manager returned None after ingest")
    else:
        print(f"  Fetched: CRD={mgr.crd_number} name={mgr.firm_name} AUM=${mgr.aum_total} state={mgr.state}")
        if mgr.firm_name != "Ares Management LLC":
            bug(f"firm_name mismatch: {mgr.firm_name}")
        if mgr.aum_total != 282_000_000_000:
            bug(f"aum_total mismatch: {mgr.aum_total}")

    # Cleanup
    from app.shared.models import SecManager
    async with _get_session() as s, s.begin():
        await s.execute(delete(SecManager).where(SecManager.crd_number == ares_crd))
    print(f"  Cleaned up CRD={ares_crd}")


# ---------------------------------------------------------------------------
# Cleanup + Main
# ---------------------------------------------------------------------------

async def cleanup() -> None:
    print("\n--- Cleanup ---")
    try:
        async with _get_session() as session, session.begin():
            for cik in _ciks_to_cleanup:
                r1 = await session.execute(
                    delete(Sec13fDiffModel).where(Sec13fDiffModel.cik == cik),
                )
                r2 = await session.execute(
                    delete(Sec13fHoldingModel).where(Sec13fHoldingModel.cik == cik),
                )
                print(f"  CIK={cik}: deleted {r1.rowcount} diffs, {r2.rowcount} holdings")
        print("  Cleanup complete.")
    except Exception as exc:
        print(f"  Cleanup failed: {exc}")


async def main() -> int:
    print("=" * 60)
    print("SEC Data Providers -- Real Data Extraction Tests")
    print("=" * 60)

    # Verify DB
    try:
        async with _engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        print("  Database OK.\n")
    except Exception as exc:
        print(f"  Database connection failed: {exc}")
        return 1

    adv = AdvService(db_session_factory=_get_session)
    tf = ThirteenFService(db_session_factory=_get_session)
    inst = InstitutionalService(thirteenf_service=tf, db_session_factory=_get_session)

    try:
        await test_iapd_search(adv)
        ctx = await test_13f_holdings(tf)
        await test_sector_aggregation(tf, ctx)
        await test_concentration(tf, ctx)
        await test_compute_diffs(tf, ctx)
        await test_institutional_discovery(inst)
        await test_cik_resolution_real()
        await test_adv_ingest_and_fetch(adv)
    finally:
        await cleanup()
        await _engine.dispose()

    # Summary
    print("\n" + "=" * 60)
    if _bugs:
        print(f"  {len(_bugs)} BUG(S) FOUND:")
        for b in _bugs:
            print(f"    - {b}")
    if _warnings:
        print(f"  {len(_warnings)} WARNING(S):")
        for w in _warnings:
            print(f"    - {w}")
    if not _bugs and not _warnings:
        print("  All real data tests passed. No bugs found.")
    print("=" * 60)

    return 1 if _bugs else 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
