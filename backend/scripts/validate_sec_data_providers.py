"""Integration validation script for SEC Data Providers layer.

Exercises every public method of the 3 services (AdvService, ThirteenFService,
InstitutionalService) with real or realistic inputs against a live database.
Asserts return shapes, types, and invariants documented in the implementation guide.

Usage:
    make up && make migrate
    python backend/scripts/validate_sec_data_providers.py

Exit code 0 = all pass, 1 = any failure.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import traceback
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError, dataclass, fields
from datetime import date
from typing import Any

# ---------------------------------------------------------------------------
# Bootstrap: load .env and ensure backend/ is on sys.path.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
_REPO_ROOT = os.path.dirname(_BACKEND_DIR)

# Load .env from repo root (DATABASE_URL, REDIS_URL, etc.)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_REPO_ROOT, ".env"))
except ImportError:
    pass  # dotenv not installed — rely on shell env

if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# SEC data providers — the modules under test.
from data_providers.sec.models import (
    AdvFund,
    AdvManager,
    AdvTeamMember,
    CikResolution,
    CoverageType,
    InstitutionalAllocation,
    InstitutionalOwnershipResult,
    SeriesFetchResult,
    ThirteenFDiff,
    ThirteenFHolding,
)
from data_providers.sec.shared import (
    _check_rate_local,
    _normalize_heavy,
    _normalize_light,
    check_edgar_rate,
    check_iapd_rate,
    resolve_cik,
    run_in_sec_thread,
    sanitize_entity_name,
)

# ORM models for direct SQL cleanup.
from app.shared.models import (
    Sec13fDiff as Sec13fDiffModel,
    Sec13fHolding as Sec13fHoldingModel,
    SecInstitutionalAllocation as SecInstitutionalAllocationModel,
    SecManager,
)

# ---------------------------------------------------------------------------
# Test data prefix to avoid collision.
# ---------------------------------------------------------------------------
_PREFIX = "__test_sec_validate_"
_TEST_CRD = "9999990001"
_TEST_CIK = "9999990001"
_TEST_FILER_CIK = "9999990002"

# ---------------------------------------------------------------------------
# Result tracking.
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    elapsed_ms: float = 0.0


_results: list[CheckResult] = []


def _record(name: str, passed: bool, detail: str = "", elapsed_ms: float = 0.0) -> None:
    _results.append(CheckResult(name=name, passed=passed, detail=detail, elapsed_ms=elapsed_ms))
    tag = "\033[92mPASS\033[0m" if passed else "\033[91mFAIL\033[0m"
    line = f"  [{tag}] {name}"
    if not passed and detail:
        line += f": {detail}"
    print(line)


async def _run_check(name: str, coro_or_fn: Any) -> None:
    """Execute a single check, catching all exceptions."""
    t0 = time.perf_counter()
    try:
        if asyncio.iscoroutinefunction(coro_or_fn):
            await coro_or_fn()
        elif asyncio.iscoroutine(coro_or_fn):
            await coro_or_fn
        else:
            coro_or_fn()
        elapsed = (time.perf_counter() - t0) * 1000
        _record(name, True, elapsed_ms=elapsed)
    except AssertionError as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        _record(name, False, detail=str(exc) or "assertion failed", elapsed_ms=elapsed)
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        _record(name, False, detail=f"{type(exc).__name__}: {exc}", elapsed_ms=elapsed)


# ---------------------------------------------------------------------------
# DB setup.
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/netz",
)

# asyncpg uses ``ssl`` not ``sslmode`` — translate for Timescale Cloud / managed PG.
_connect_args: dict[str, Any] = {}
if "sslmode=require" in DATABASE_URL:
    import ssl as _ssl_mod
    DATABASE_URL = DATABASE_URL.replace("?sslmode=require", "").replace("&sslmode=require", "")
    _ctx = _ssl_mod.create_default_context()
    _ctx.check_hostname = False
    _ctx.verify_mode = _ssl_mod.CERT_NONE
    _connect_args["ssl"] = _ctx

_engine = create_async_engine(DATABASE_URL, echo=False, connect_args=_connect_args)
_session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def _get_session():
    async with _session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Group 1: shared.py — CIK Resolution (no DB needed)
# ---------------------------------------------------------------------------

def _group1_checks() -> list[tuple[str, Any]]:
    checks: list[tuple[str, Any]] = []

    def check_resolve_cik_empty():
        r = resolve_cik("", ticker=None)
        assert r.cik is None, f"expected None, got {r.cik}"
        assert r.method == "not_found", f"expected not_found, got {r.method}"
    checks.append(("g1_resolve_cik_empty", check_resolve_cik_empty))

    def check_resolve_cik_too_long():
        r = resolve_cik("x" * 201)
        assert r.cik is None, f"expected None, got {r.cik}"
    checks.append(("g1_resolve_cik_too_long", check_resolve_cik_too_long))

    def check_resolve_cik_injection():
        r = resolve_cik('name"OR 1=1')
        assert r.cik is None, f"expected None, got {r.cik}"
    checks.append(("g1_resolve_cik_injection", check_resolve_cik_injection))

    def check_sanitize_normal():
        r = sanitize_entity_name("Ares Capital")
        assert r == "Ares Capital", f"expected 'Ares Capital', got {r!r}"
    checks.append(("g1_sanitize_normal", check_sanitize_normal))

    def check_sanitize_empty():
        r = sanitize_entity_name("")
        assert r is None, f"expected None, got {r!r}"
    checks.append(("g1_sanitize_empty", check_sanitize_empty))

    def check_sanitize_none():
        # sanitize_entity_name accepts str, but the spec says None → None.
        # The function guards with `if not name`, which handles None.
        r = sanitize_entity_name(None)  # type: ignore[arg-type]
        assert r is None, f"expected None, got {r!r}"
    checks.append(("g1_sanitize_none", check_sanitize_none))

    def check_sanitize_punctuation():
        r = sanitize_entity_name("O'Brien & Sons, Inc.")
        assert r == "O'Brien & Sons, Inc.", f"expected same string, got {r!r}"
    checks.append(("g1_sanitize_punctuation", check_sanitize_punctuation))

    def check_normalize_heavy_strips_inc():
        r = _normalize_heavy("Ares Capital Inc")
        assert "inc" not in r.split(), f"expected 'inc' stripped, got {r!r}"
    checks.append(("g1_normalize_heavy_strips_inc", check_normalize_heavy_strips_inc))

    def check_normalize_heavy_keeps_meaningful():
        r = _normalize_heavy("Blue Owl Capital Partners Fund")
        assert "capital" in r, f"expected 'capital' preserved, got {r!r}"
        assert "partners" in r, f"expected 'partners' preserved, got {r!r}"
        assert "fund" in r, f"expected 'fund' preserved, got {r!r}"
    checks.append(("g1_normalize_heavy_keeps_meaningful", check_normalize_heavy_keeps_meaningful))

    def check_cik_resolution_frozen():
        c = CikResolution(cik="1234", company_name="Test", method="ticker", confidence=1.0)
        try:
            c.cik = "5678"  # type: ignore[misc]
            assert False, "should have raised"
        except (FrozenInstanceError, AttributeError):
            pass
    checks.append(("g1_cik_resolution_frozen", check_cik_resolution_frozen))

    async def check_run_in_sec_thread():
        result = await run_in_sec_thread(lambda: 42)
        assert result == 42, f"expected 42, got {result}"
    checks.append(("g1_run_in_sec_thread", check_run_in_sec_thread))

    return checks


# ---------------------------------------------------------------------------
# Group 2: models.py — Dataclass Invariants
# ---------------------------------------------------------------------------

def _group2_checks() -> list[tuple[str, Any]]:
    checks: list[tuple[str, Any]] = []

    _ALL_DATACLASSES = [
        AdvManager, AdvFund, AdvTeamMember,
        ThirteenFHolding, ThirteenFDiff,
        InstitutionalAllocation, CikResolution,
        InstitutionalOwnershipResult, SeriesFetchResult,
    ]

    def check_all_frozen():
        for cls in _ALL_DATACLASSES:
            # Verify frozen by checking __dataclass_params__
            assert cls.__dataclass_params__.frozen, f"{cls.__name__} is not frozen"
    checks.append(("g2_all_dataclasses_frozen", check_all_frozen))

    def check_coverage_type_values():
        assert CoverageType.FOUND.value == "found"
        assert CoverageType.NO_PUBLIC_SECURITIES.value == "no_public_securities"
        assert CoverageType.PUBLIC_SECURITIES_NO_HOLDERS.value == "public_securities_no_holders"
    checks.append(("g2_coverage_type_values", check_coverage_type_values))

    def check_institutional_ownership_defaults():
        r = InstitutionalOwnershipResult(
            manager_cik="1234",
            coverage=CoverageType.FOUND,
        )
        assert r.investors == [], f"expected empty list, got {r.investors}"
        assert r.note is None, f"expected None, got {r.note}"
    checks.append(("g2_institutional_ownership_defaults", check_institutional_ownership_defaults))

    def check_series_fetch_result_defaults():
        r = SeriesFetchResult()
        assert r.data == []
        assert r.warnings == []
        assert r.is_stale is False
    checks.append(("g2_series_fetch_result_defaults", check_series_fetch_result_defaults))

    return checks


# ---------------------------------------------------------------------------
# Group 3: AdvService — Against Live DB
# ---------------------------------------------------------------------------

def _group3_checks() -> list[tuple[str, Any]]:
    from data_providers.sec.adv_service import AdvService

    svc = AdvService(db_session_factory=_get_session)
    checks: list[tuple[str, Any]] = []

    async def check_search_empty():
        r = await svc.search_managers("")
        assert r == [], f"expected [], got {r}"
    checks.append(("g3_search_managers_empty", check_search_empty))

    async def check_search_whitespace():
        r = await svc.search_managers("   ")
        assert r == [], f"expected [], got {r}"
    checks.append(("g3_search_managers_whitespace", check_search_whitespace))

    async def check_fetch_invalid_crd():
        r = await svc.fetch_manager("abc")
        assert r is None, f"expected None, got {r}"
    checks.append(("g3_fetch_manager_invalid_crd", check_fetch_invalid_crd))

    async def check_fetch_not_found():
        r = await svc.fetch_manager("99999999")
        assert r is None, f"expected None, got {r}"
    checks.append(("g3_fetch_manager_not_found", check_fetch_not_found))

    async def check_fetch_funds_invalid():
        r = await svc.fetch_manager_funds("abc")
        assert r == [], f"expected [], got {r}"
    checks.append(("g3_fetch_manager_funds_invalid", check_fetch_funds_invalid))

    async def check_fetch_team_valid_crd():
        r = await svc.fetch_manager_team("12345")
        assert r == [], f"expected [], got {r}"
        assert isinstance(r, list)
    checks.append(("g3_fetch_manager_team_stub", check_fetch_team_valid_crd))

    async def check_fetch_team_invalid_crd():
        r = await svc.fetch_manager_team("abc")
        assert r == [], f"expected [], got {r}"
    checks.append(("g3_fetch_manager_team_invalid", check_fetch_team_invalid_crd))

    # Ingest a small inline CSV and verify round-trip.
    _CSV_CONTENT = (
        "CRD Number,Primary Business Name,SEC#,Status,Q5F2A,Q5F2B,Q5F2C,Main Office State\n"
        f"{_TEST_CRD},{_PREFIX}Test Firm,SEC-001,ACTIVE,1000000,500000,1500000,NY\n"
        "invalid_crd,Bad Firm,,,,,,,\n"  # Invalid CRD — skip
        "9999990002,,SEC-003,ACTIVE,0,0,0,CA\n"  # Missing name — skip
    )

    async def check_ingest_csv():
        # Write CSV to temp file
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(_CSV_CONTENT)
            tmp_path = f.name
        try:
            count = await svc.ingest_bulk_adv(csv_path=tmp_path)
            assert count == 1, f"expected 1 upserted, got {count}"
        finally:
            os.unlink(tmp_path)
    checks.append(("g3_ingest_bulk_adv_csv", check_ingest_csv))

    async def check_fetch_after_ingest():
        mgr = await svc.fetch_manager(_TEST_CRD)
        assert mgr is not None, "expected manager after ingest"
        assert mgr.firm_name == f"{_PREFIX}Test Firm", f"wrong firm_name: {mgr.firm_name}"
        assert mgr.crd_number == _TEST_CRD
        assert isinstance(mgr, AdvManager)
    checks.append(("g3_fetch_after_ingest", check_fetch_after_ingest))

    async def check_fetch_funds_after_ingest():
        funds = await svc.fetch_manager_funds(_TEST_CRD)
        assert funds == [], f"expected no funds, got {len(funds)}"
    checks.append(("g3_fetch_funds_after_ingest", check_fetch_funds_after_ingest))

    async def check_upsert_idempotent():
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(_CSV_CONTENT)
            tmp_path = f.name
        try:
            count = await svc.ingest_bulk_adv(csv_path=tmp_path)
            assert count == 1, f"expected 1 upserted (idempotent), got {count}"
        finally:
            os.unlink(tmp_path)

        # Verify no duplicates
        async with _get_session() as session:
            from sqlalchemy import select, func
            stmt = select(func.count()).select_from(SecManager).where(
                SecManager.crd_number == _TEST_CRD,
            )
            result = await session.execute(stmt)
            row_count = result.scalar()
            assert row_count == 1, f"expected 1 row, got {row_count} (duplicate!)"
    checks.append(("g3_upsert_idempotent", check_upsert_idempotent))

    return checks


# ---------------------------------------------------------------------------
# Group 4: ThirteenFService — Against Live DB
# ---------------------------------------------------------------------------

def _group4_checks() -> list[tuple[str, Any]]:
    from data_providers.sec.thirteenf_service import ThirteenFService

    # Use a no-op rate check to avoid hitting real EDGAR.
    svc = ThirteenFService(
        db_session_factory=_get_session,
        rate_check=lambda: None,
    )
    checks: list[tuple[str, Any]] = []

    async def check_fetch_invalid_cik():
        r = await svc.fetch_holdings("abc")
        assert r == [], f"expected [], got {r}"
    checks.append(("g4_fetch_holdings_invalid_cik", check_fetch_invalid_cik))

    async def check_fetch_not_found():
        r = await svc.fetch_holdings("9999999999")
        assert r == [], f"expected [], got {r}"
    checks.append(("g4_fetch_holdings_not_found", check_fetch_not_found))

    async def check_compute_diffs_invalid():
        r = await svc.compute_diffs("abc", date(2025, 9, 30), date(2025, 12, 31))
        assert r == [], f"expected [], got {r}"
    checks.append(("g4_compute_diffs_invalid_cik", check_compute_diffs_invalid))

    async def check_sector_agg_invalid():
        r = await svc.get_sector_aggregation("abc", date(2025, 12, 31))
        assert r == {}, f"expected {{}}, got {r}"
    checks.append(("g4_sector_aggregation_invalid", check_sector_agg_invalid))

    async def check_concentration_invalid():
        r = await svc.get_concentration_metrics("abc", date(2025, 12, 31))
        assert r == {}, f"expected {{}}, got {r}"
    checks.append(("g4_concentration_invalid", check_concentration_invalid))

    # _compute_diffs_internal — known inputs
    def check_diffs_increased():
        from_h = [ThirteenFHolding(
            cik=_TEST_CIK, report_date="2025-09-30", filing_date="2025-11-14",
            accession_number="0001", cusip="AAPL00001", issuer_name="AAPL",
            asset_class="COM", shares=100, market_value=15000,
            discretion=None, voting_sole=None, voting_shared=None, voting_none=None,
        )]
        to_h = [ThirteenFHolding(
            cik=_TEST_CIK, report_date="2025-12-31", filing_date="2026-02-14",
            accession_number="0002", cusip="AAPL00001", issuer_name="AAPL",
            asset_class="COM", shares=200, market_value=30000,
            discretion=None, voting_sole=None, voting_shared=None, voting_none=None,
        )]
        diffs = ThirteenFService._compute_diffs_internal(
            _TEST_CIK, from_h, to_h, date(2025, 9, 30), date(2025, 12, 31),
        )
        assert len(diffs) == 1
        d = diffs[0]
        assert d.action == "INCREASED", f"expected INCREASED, got {d.action}"
        assert d.shares_delta == 100, f"expected 100, got {d.shares_delta}"
    checks.append(("g4_diffs_increased", check_diffs_increased))

    def check_diffs_exited():
        from_h = [ThirteenFHolding(
            cik=_TEST_CIK, report_date="2025-09-30", filing_date="2025-11-14",
            accession_number="0001", cusip="MSFT00001", issuer_name="MSFT",
            asset_class="COM", shares=50, market_value=10000,
            discretion=None, voting_sole=None, voting_shared=None, voting_none=None,
        )]
        to_h: list[ThirteenFHolding] = []
        diffs = ThirteenFService._compute_diffs_internal(
            _TEST_CIK, from_h, to_h, date(2025, 9, 30), date(2025, 12, 31),
        )
        assert len(diffs) == 1
        d = diffs[0]
        assert d.action == "EXITED", f"expected EXITED, got {d.action}"
        assert d.shares_delta == -50, f"expected -50, got {d.shares_delta}"
    checks.append(("g4_diffs_exited", check_diffs_exited))

    def check_diffs_new_position():
        from_h: list[ThirteenFHolding] = []
        to_h = [ThirteenFHolding(
            cik=_TEST_CIK, report_date="2025-12-31", filing_date="2026-02-14",
            accession_number="0002", cusip="GOOG00001", issuer_name="GOOG",
            asset_class="COM", shares=300, market_value=45000,
            discretion=None, voting_sole=None, voting_shared=None, voting_none=None,
        )]
        diffs = ThirteenFService._compute_diffs_internal(
            _TEST_CIK, from_h, to_h, date(2025, 9, 30), date(2025, 12, 31),
        )
        assert len(diffs) == 1
        d = diffs[0]
        assert d.action == "NEW_POSITION", f"expected NEW_POSITION, got {d.action}"
        assert d.shares_delta == 300, f"expected 300, got {d.shares_delta}"
    checks.append(("g4_diffs_new_position", check_diffs_new_position))

    def check_weight_invariant():
        """For a multi-position diff, weight_before sums ≈ 1.0, weight_after sums ≈ 1.0."""
        from_h = [
            ThirteenFHolding(
                cik=_TEST_CIK, report_date="2025-09-30", filing_date="2025-11-14",
                accession_number="0001", cusip=f"TEST{i:05d}", issuer_name=f"Stock{i}",
                asset_class="COM", shares=100, market_value=10000,
                discretion=None, voting_sole=None, voting_shared=None, voting_none=None,
            )
            for i in range(5)
        ]
        to_h = [
            ThirteenFHolding(
                cik=_TEST_CIK, report_date="2025-12-31", filing_date="2026-02-14",
                accession_number="0002", cusip=f"TEST{i:05d}", issuer_name=f"Stock{i}",
                asset_class="COM", shares=100 + i * 10, market_value=10000 + i * 1000,
                discretion=None, voting_sole=None, voting_shared=None, voting_none=None,
            )
            for i in range(5)
        ]
        diffs = ThirteenFService._compute_diffs_internal(
            _TEST_CIK, from_h, to_h, date(2025, 9, 30), date(2025, 12, 31),
        )
        wb = sum(d.weight_before for d in diffs if d.weight_before is not None)
        wa = sum(d.weight_after for d in diffs if d.weight_after is not None)
        assert abs(wb - 1.0) < 0.01, f"weight_before sum {wb} not ~= 1.0"
        assert abs(wa - 1.0) < 0.01, f"weight_after sum {wa} not ~= 1.0"
    checks.append(("g4_weight_invariant", check_weight_invariant))

    # DB round-trip: insert test holdings, verify read-back and aggregations.
    async def check_db_roundtrip():
        _test_date_q1 = date(2025, 9, 30)
        _test_date_q2 = date(2025, 12, 31)

        # Insert test holdings via direct SQL
        async with _get_session() as session, session.begin():
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            rows = [
                {
                    "cik": _TEST_CIK, "report_date": _test_date_q1,
                    "filing_date": date(2025, 11, 14), "accession_number": "0000000001-25-000001",
                    "cusip": f"{_PREFIX}C1", "issuer_name": f"{_PREFIX}Issuer1",
                    "asset_class": "COM", "shares": 1000, "market_value": 50000,
                    "discretion": "SOLE", "voting_sole": 1000, "voting_shared": None,
                    "voting_none": None, "data_fetched_at": date(2025, 11, 15),
                },
                {
                    "cik": _TEST_CIK, "report_date": _test_date_q1,
                    "filing_date": date(2025, 11, 14), "accession_number": "0000000001-25-000001",
                    "cusip": f"{_PREFIX}C2", "issuer_name": f"{_PREFIX}Issuer2",
                    "asset_class": "PUT", "shares": 500, "market_value": 50000,
                    "discretion": "SOLE", "voting_sole": 500, "voting_shared": None,
                    "voting_none": None, "data_fetched_at": date(2025, 11, 15),
                },
                {
                    "cik": _TEST_CIK, "report_date": _test_date_q2,
                    "filing_date": date(2026, 2, 14), "accession_number": "0000000001-26-000001",
                    "cusip": f"{_PREFIX}C1", "issuer_name": f"{_PREFIX}Issuer1",
                    "asset_class": "COM", "shares": 1500, "market_value": 75000,
                    "discretion": "SOLE", "voting_sole": 1500, "voting_shared": None,
                    "voting_none": None, "data_fetched_at": date(2026, 2, 15),
                },
                {
                    "cik": _TEST_CIK, "report_date": _test_date_q2,
                    "filing_date": date(2026, 2, 14), "accession_number": "0000000001-26-000001",
                    "cusip": f"{_PREFIX}C2", "issuer_name": f"{_PREFIX}Issuer2",
                    "asset_class": "PUT", "shares": 300, "market_value": 25000,
                    "discretion": "SOLE", "voting_sole": 300, "voting_shared": None,
                    "voting_none": None, "data_fetched_at": date(2026, 2, 15),
                },
            ]
            for row in rows:
                stmt = pg_insert(Sec13fHoldingModel).values(**row)
                stmt = stmt.on_conflict_do_nothing()
                await session.execute(stmt)

        # fetch_holdings — use staleness_ttl_days=9999 to avoid EDGAR fallback
        # (edgartools may not be installed; we only want to validate the DB read path)
        holdings = await svc.fetch_holdings(
            _TEST_CIK, force_refresh=False, staleness_ttl_days=9999,
        )
        assert len(holdings) >= 2, f"expected >=2 holdings, got {len(holdings)}"
        assert all(isinstance(h, ThirteenFHolding) for h in holdings)

        # get_sector_aggregation -- weights should sum to 1.0
        sectors = await svc.get_sector_aggregation(_TEST_CIK, _test_date_q2)
        assert sectors, "expected non-empty sectors"
        weight_sum = sum(sectors.values())
        assert abs(weight_sum - 1.0) < 0.01, f"sector weights sum {weight_sum} not ~= 1.0"

        # get_concentration_metrics
        metrics = await svc.get_concentration_metrics(_TEST_CIK, _test_date_q2)
        assert "hhi" in metrics, f"expected hhi in metrics, got {list(metrics.keys())}"
        assert "top_10_concentration" in metrics
        assert "position_count" in metrics
        assert metrics["position_count"] >= 2

        # compute_diffs
        diffs = await svc.compute_diffs(_TEST_CIK, _test_date_q1, _test_date_q2)
        assert len(diffs) >= 1, f"expected >=1 diffs, got {len(diffs)}"
        assert all(isinstance(d, ThirteenFDiff) for d in diffs)

    checks.append(("g4_db_roundtrip", check_db_roundtrip))

    return checks


# ---------------------------------------------------------------------------
# Group 5: InstitutionalService — Against Live DB
# ---------------------------------------------------------------------------

def _group5_checks() -> list[tuple[str, Any]]:
    from data_providers.sec.institutional_service import (
        InstitutionalService,
        _classify_filer_type,
    )
    from data_providers.sec.thirteenf_service import ThirteenFService

    thirteenf_svc = ThirteenFService(
        db_session_factory=_get_session,
        rate_check=lambda: None,
    )
    svc = InstitutionalService(
        thirteenf_service=thirteenf_svc,
        db_session_factory=_get_session,
    )
    checks: list[tuple[str, Any]] = []

    async def check_find_investors_invalid_cik():
        r = await svc.find_investors_in_manager("abc")
        assert r.coverage == CoverageType.NO_PUBLIC_SECURITIES
        assert "Invalid CIK" in (r.note or ""), f"expected 'Invalid CIK' in note, got {r.note!r}"
    checks.append(("g5_find_investors_invalid_cik", check_find_investors_invalid_cik))

    async def check_find_investors_not_found():
        r = await svc.find_investors_in_manager("9999999999")
        assert r.coverage == CoverageType.NO_PUBLIC_SECURITIES
    checks.append(("g5_find_investors_not_found", check_find_investors_not_found))

    async def check_fetch_allocations_invalid():
        r = await svc.fetch_allocations("abc", "Fund", "pension")
        assert r == [], f"expected [], got {r}"
    checks.append(("g5_fetch_allocations_invalid", check_fetch_allocations_invalid))

    # _classify_filer_type tests
    def check_classify_endowment():
        assert _classify_filer_type("Harvard Endowment Fund") == "endowment"
    checks.append(("g5_classify_endowment", check_classify_endowment))

    def check_classify_pension():
        assert _classify_filer_type("California Pension System") == "pension"
    checks.append(("g5_classify_pension", check_classify_pension))

    def check_classify_foundation():
        assert _classify_filer_type("Gates Foundation") == "foundation"
    checks.append(("g5_classify_foundation", check_classify_foundation))

    def check_classify_sovereign():
        assert _classify_filer_type("Abu Dhabi Investment Authority") == "sovereign"
    checks.append(("g5_classify_sovereign", check_classify_sovereign))

    def check_classify_insurance():
        assert _classify_filer_type("MetLife Insurance") == "insurance"
    checks.append(("g5_classify_insurance", check_classify_insurance))

    def check_classify_no_match():
        assert _classify_filer_type("Blackrock Capital") is None
    checks.append(("g5_classify_no_match", check_classify_no_match))

    # DB round-trip: insert test data for find_investors_in_manager coverage.
    async def check_find_investors_found():
        """Insert 13F holdings for a manager + institutional allocations → FOUND."""
        _manager_cik = _TEST_CIK  # reuse holdings from group 4
        _filer_cik = _TEST_FILER_CIK
        _cusip = f"{_PREFIX}C1"  # matches what group 4 inserted

        # Insert institutional allocation for the filer holding this CUSIP
        async with _get_session() as session, session.begin():
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            stmt = pg_insert(SecInstitutionalAllocationModel).values(
                filer_cik=_filer_cik,
                filer_name=f"{_PREFIX}Pension Fund",
                filer_type="pension",
                report_date=date(2025, 12, 31),
                target_cusip=_cusip,
                target_issuer=f"{_PREFIX}Issuer1",
                market_value=25000,
                shares=500,
            )
            stmt = stmt.on_conflict_do_nothing()
            await session.execute(stmt)

        r = await svc.find_investors_in_manager(_manager_cik)
        assert r.coverage == CoverageType.FOUND, f"expected FOUND, got {r.coverage}"
        assert len(r.investors) > 0, "expected investors"
    checks.append(("g5_find_investors_found", check_find_investors_found))

    async def check_find_investors_no_holders():
        """Manager has holdings but no institutional filers hold them."""
        # Use a different CIK that has holdings but no allocations
        _orphan_cik = "9999990003"
        _orphan_cusip = f"{_PREFIX}ORPHAN"

        async with _get_session() as session, session.begin():
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            stmt = pg_insert(Sec13fHoldingModel).values(
                cik=_orphan_cik, report_date=date(2025, 12, 31),
                filing_date=date(2026, 2, 14), accession_number="0000000001-26-999999",
                cusip=_orphan_cusip, issuer_name=f"{_PREFIX}OrphanIssuer",
                asset_class="COM", shares=100, market_value=5000,
                discretion="SOLE", voting_sole=100, voting_shared=None,
                voting_none=None, data_fetched_at=date(2026, 2, 15),
            )
            stmt = stmt.on_conflict_do_nothing()
            await session.execute(stmt)

        r = await svc.find_investors_in_manager(_orphan_cik)
        assert r.coverage == CoverageType.PUBLIC_SECURITIES_NO_HOLDERS, (
            f"expected PUBLIC_SECURITIES_NO_HOLDERS, got {r.coverage}"
        )

        # Cleanup orphan
        async with _get_session() as session, session.begin():
            await session.execute(
                delete(Sec13fHoldingModel).where(Sec13fHoldingModel.cik == _orphan_cik),
            )
    checks.append(("g5_find_investors_no_holders", check_find_investors_no_holders))

    return checks


# ---------------------------------------------------------------------------
# Group 6: Rate Limiter Validation
# ---------------------------------------------------------------------------

def _group6_checks() -> list[tuple[str, Any]]:
    checks: list[tuple[str, Any]] = []

    def check_edgar_rate_no_raise():
        check_edgar_rate()
    checks.append(("g6_check_edgar_rate", check_edgar_rate_no_raise))

    def check_iapd_rate_no_raise():
        check_iapd_rate()
    checks.append(("g6_check_iapd_rate", check_iapd_rate_no_raise))

    def check_local_rate_no_raise():
        _check_rate_local("test_validation", 4)
    checks.append(("g6_check_rate_local", check_local_rate_no_raise))

    def check_local_rate_warn_once():
        # Reset warned set for this test
        from data_providers.sec.shared import _fallback_warned
        _fallback_warned.discard("test_validation_warn")
        _check_rate_local("test_validation_warn", 4)
        assert "test_validation_warn" in _fallback_warned
        # Second call should not raise
        _check_rate_local("test_validation_warn", 4)
    checks.append(("g6_check_rate_local_warn_once", check_local_rate_warn_once))

    return checks


# ---------------------------------------------------------------------------
# Group 7: Cross-Service Invariants
# ---------------------------------------------------------------------------

def _group7_checks() -> list[tuple[str, Any]]:
    from data_providers.sec.adv_service import AdvService
    from data_providers.sec.institutional_service import InstitutionalService
    from data_providers.sec.thirteenf_service import ThirteenFService

    checks: list[tuple[str, Any]] = []

    def check_services_accept_factory():
        """All 3 services accept db_session_factory as callable."""
        adv = AdvService(db_session_factory=_get_session)
        assert adv._db_session_factory is _get_session

        tf = ThirteenFService(db_session_factory=_get_session)
        assert tf._db_session_factory is _get_session

        inst = InstitutionalService(thirteenf_service=tf, db_session_factory=_get_session)
        assert inst._db_session_factory is _get_session
    checks.append(("g7_services_accept_factory", check_services_accept_factory))

    def check_institutional_accepts_thirteenf():
        """InstitutionalService.__init__ accepts thirteenf_service — confirming composition."""
        tf = ThirteenFService(db_session_factory=_get_session)
        inst = InstitutionalService(thirteenf_service=tf, db_session_factory=_get_session)
        assert inst._thirteenf is tf
    checks.append(("g7_institutional_composition", check_institutional_accepts_thirteenf))

    async def check_timeout_guard():
        """All public methods return within 5s for invalid/empty inputs."""
        adv = AdvService(db_session_factory=_get_session)
        tf = ThirteenFService(db_session_factory=_get_session, rate_check=lambda: None)
        inst = InstitutionalService(thirteenf_service=tf, db_session_factory=_get_session)

        calls = [
            adv.search_managers(""),
            adv.fetch_manager("abc"),
            adv.fetch_manager_funds("abc"),
            adv.fetch_manager_team("abc"),
            tf.fetch_holdings("abc"),
            tf.compute_diffs("abc", date(2025, 9, 30), date(2025, 12, 31)),
            tf.get_sector_aggregation("abc", date(2025, 12, 31)),
            tf.get_concentration_metrics("abc", date(2025, 12, 31)),
            inst.find_investors_in_manager("abc"),
            inst.fetch_allocations("abc", "Fund", "pension"),
        ]

        for coro in calls:
            try:
                await asyncio.wait_for(coro, timeout=5.0)
            except asyncio.TimeoutError:
                assert False, f"timed out after 5s"
    checks.append(("g7_timeout_guard", check_timeout_guard))

    async def check_no_raise_on_fuzz():
        """No public method raises on invalid input."""
        adv = AdvService(db_session_factory=_get_session)
        tf = ThirteenFService(db_session_factory=_get_session, rate_check=lambda: None)
        inst = InstitutionalService(thirteenf_service=tf, db_session_factory=_get_session)

        fuzz_inputs = [None, "", "abc", "x" * 500]

        for inp in fuzz_inputs:
            # AdvService
            await adv.search_managers(inp or "")
            await adv.fetch_manager(inp or "")
            await adv.fetch_manager_funds(inp or "")
            await adv.fetch_manager_team(inp or "")

            # ThirteenFService
            await tf.fetch_holdings(inp or "")
            await tf.compute_diffs(inp or "", date(2025, 9, 30), date(2025, 12, 31))
            await tf.get_sector_aggregation(inp or "", date(2025, 12, 31))
            await tf.get_concentration_metrics(inp or "", date(2025, 12, 31))

            # InstitutionalService
            await inst.find_investors_in_manager(inp or "")
            await inst.fetch_allocations(inp or "", "Fund", "pension")
    checks.append(("g7_fuzz_no_raise", check_no_raise_on_fuzz))

    return checks


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

async def _cleanup() -> None:
    """Remove all test data created during validation."""
    print("\n  Cleaning up test data...")
    try:
        async with _get_session() as session, session.begin():
            # Order matters: FK constraints
            await session.execute(
                delete(SecInstitutionalAllocationModel).where(
                    SecInstitutionalAllocationModel.filer_cik == _TEST_FILER_CIK,
                ),
            )
            await session.execute(
                delete(Sec13fDiffModel).where(Sec13fDiffModel.cik == _TEST_CIK),
            )
            await session.execute(
                delete(Sec13fHoldingModel).where(Sec13fHoldingModel.cik == _TEST_CIK),
            )
            await session.execute(
                delete(SecManager).where(SecManager.crd_number == _TEST_CRD),
            )
            # Also clean up the orphan CIK from group 5
            await session.execute(
                delete(Sec13fHoldingModel).where(Sec13fHoldingModel.cik == "9999990003"),
            )
        print("  Cleanup complete.")
    except Exception as exc:
        print(f"  \033[91mCleanup failed: {exc}\033[0m")
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def _main() -> int:
    print("=" * 60)
    print("SEC Data Providers — Integration Validation")
    print("=" * 60)

    # Verify DB connectivity first
    print("\n  Checking database connectivity...")
    try:
        async with _engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        print("  Database OK.\n")
    except Exception as exc:
        print(f"\n  \033[91mDatabase connection failed: {exc}\033[0m")
        print("  Ensure `make up && make migrate` has been run.")
        return 1

    groups = [
        ("Group 1: shared.py — CIK Resolution", _group1_checks()),
        ("Group 2: models.py — Dataclass Invariants", _group2_checks()),
        ("Group 3: AdvService — Against Live DB", _group3_checks()),
        ("Group 4: ThirteenFService — Against Live DB", _group4_checks()),
        ("Group 5: InstitutionalService — Against Live DB", _group5_checks()),
        ("Group 6: Rate Limiter Validation", _group6_checks()),
        ("Group 7: Cross-Service Invariants", _group7_checks()),
    ]

    try:
        for group_name, check_list in groups:
            print(f"\n{'-' * 50}")
            print(f"  {group_name}")
            print(f"{'-' * 50}")
            for name, fn in check_list:
                await _run_check(name, fn)
    finally:
        await _cleanup()
        await _engine.dispose()

    # Summary
    total = len(_results)
    passed = sum(1 for r in _results if r.passed)
    failed = total - passed

    print(f"\n{'=' * 60}")
    if failed == 0:
        print(f"  \033[92m{passed}/{total} checks passed. All green.\033[0m")
    else:
        print(f"  \033[91m{passed}/{total} checks passed. {failed} FAILED.\033[0m")
        print("\n  Failed checks:")
        for r in _results:
            if not r.passed:
                print(f"    - {r.name}: {r.detail}")
    print(f"{'=' * 60}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(_main())
    sys.exit(exit_code)
