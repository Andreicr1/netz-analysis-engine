"""Unit tests for the holdings-based attribution rail (PR-Q4, G3 Fase 2).

Covers the Cenário A path (no sic_gics_mapping): matview reads sector
directly. Tests drive the rail via an injected ``holdings_fetch`` seam
and the raw ``run_holdings_rail`` function with fake DB callables.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from vertical_engines.wealth.attribution import holdings_based
from vertical_engines.wealth.attribution.models import (
    AttributionRequest,
    HoldingsBasedResult,
    RailBadge,
    SectorWeight,
)
from vertical_engines.wealth.attribution.service import (
    _deserialize_result,
    _serialize_result,
    compute_fund_attribution,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeRow:
    def __init__(self, value):
        self._value = value

    def __getitem__(self, _idx):
        return self._value

    def first(self):
        return (self._value,) if self._value is not None else None


class _FakeMappings:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return [dict(r) for r in self._rows]

    def one(self):
        return dict(self._rows[0])


class _FakeResult:
    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def first(self):
        if self._scalar is not None:
            return (self._scalar,)
        if self._rows:
            first = self._rows[0]
            return tuple(first.values()) if isinstance(first, dict) else first
        return None

    def mappings(self):
        return _FakeMappings(self._rows)


class _FakeSession:
    """Scripted async session returning results keyed by SQL fragment."""

    def __init__(self, script: list[tuple[str, _FakeResult]]):
        self._script = list(script)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt).strip()
        self.calls.append((sql, dict(params or {})))
        for frag, result in self._script:
            if frag in sql:
                return result
        return _FakeResult()


def _req(fund_id: UUID | None = None, asof: date | None = None) -> AttributionRequest:
    return AttributionRequest(
        fund_instrument_id=fund_id or uuid4(),
        asof=asof or date(2026, 3, 31),
        lookback_months=60,
        min_months=36,
    )


def _sector_rows(n=3):
    base = [
        {
            "issuer_category": "EC",
            "industry_sector": "Information Technology",
            "aum_usd": 500_000_000.0,
            "weight": 0.50,
            "holdings_count": 120,
        },
        {
            "issuer_category": "DBT",
            "industry_sector": "Financials",
            "aum_usd": 300_000_000.0,
            "weight": 0.30,
            "holdings_count": 45,
        },
        {
            "issuer_category": "EC",
            "industry_sector": "Health Care",
            "aum_usd": 200_000_000.0,
            "weight": 0.20,
            "holdings_count": 32,
        },
    ]
    return base[:n]


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def test_compute_aum_coverage_all_classified():
    sectors = [
        SectorWeight("IT", "EC", 0.5, 100.0, 1),
        SectorWeight("Financials", "DBT", 0.5, 100.0, 1),
    ]
    assert holdings_based.compute_aum_coverage(sectors) == pytest.approx(1.0)


def test_compute_aum_coverage_with_unclassified():
    sectors = [
        SectorWeight("IT", "EC", 0.7, 100.0, 1),
        SectorWeight("Unclassified", "OTHER", 0.3, 100.0, 1),
    ]
    assert holdings_based.compute_aum_coverage(sectors) == pytest.approx(0.7)


def test_compute_aum_coverage_empty_list():
    assert holdings_based.compute_aum_coverage([]) == 0.0


def test_compute_aum_coverage_bounded():
    # Constructed so unclassified > 1 (artificial) — should clamp to [0, 1].
    sectors = [SectorWeight("Other", "OTHER", 1.5, 100.0, 1)]
    coverage = holdings_based.compute_aum_coverage(sectors)
    assert 0.0 <= coverage <= 1.0


def test_run_holdings_rail_no_cik_returns_none():
    """Private funds / UCITS without sec_cik fall through to returns rail."""

    async def no_cik(_db, _iid):
        return None

    session = _FakeSession([])
    result = asyncio.run(
        holdings_based.run_holdings_rail(_req(), session, cik_resolver=no_cik),
    )
    assert result is None


def test_run_holdings_rail_stale_filing():
    async def cik(_db, _iid):
        return "0001234567"

    session = _FakeSession([
        # latest_period_for_cik — nothing within window
        ("MAX(period_of_report)", _FakeResult(scalar=None)),
        # any_row — yes, there are older filings
        ("SELECT 1 FROM mv_nport_sector_attribution", _FakeResult(scalar=1)),
    ])
    result = asyncio.run(
        holdings_based.run_holdings_rail(_req(), session, cik_resolver=cik),
    )
    assert isinstance(result, HoldingsBasedResult)
    assert result.degraded is True
    assert result.degraded_reason == "stale_filing"


def test_run_holdings_rail_no_filing_at_all():
    async def cik(_db, _iid):
        return "0001234567"

    session = _FakeSession([
        ("MAX(period_of_report)", _FakeResult(scalar=None)),
        ("SELECT 1 FROM mv_nport_sector_attribution", _FakeResult(scalar=None)),
    ])
    result = asyncio.run(
        holdings_based.run_holdings_rail(_req(), session, cik_resolver=cik),
    )
    assert result.degraded is True
    assert result.degraded_reason == "no_filing"


def test_run_holdings_rail_happy_path():
    async def cik(_db, _iid):
        return "0001234567"

    session = _FakeSession([
        ("MAX(period_of_report)", _FakeResult(scalar=date(2026, 2, 28))),
        ("SELECT issuer_category", _FakeResult(rows=_sector_rows())),
        # _check_matview_freshness: fresh timestamp
        ("SELECT MAX(last_updated_at)",
         _FakeResult(scalar=datetime.now(timezone.utc))),
    ])
    result = asyncio.run(
        holdings_based.run_holdings_rail(_req(), session, cik_resolver=cik),
    )
    assert result is not None
    assert result.degraded is False
    assert len(result.sectors) == 3
    assert result.coverage_pct == pytest.approx(1.0)
    assert result.confidence == pytest.approx(result.coverage_pct)
    assert result.period_of_report == date(2026, 2, 28)
    assert result.holdings_count == 197


def test_run_holdings_rail_low_coverage_degrades():
    async def cik(_db, _iid):
        return "0001234567"

    # Weights heavy on 'Unclassified' → coverage < 0.80
    heavy_unclassified = [
        {"issuer_category": "OTHER", "industry_sector": "Unclassified",
         "aum_usd": 700.0, "weight": 0.70, "holdings_count": 10},
        {"issuer_category": "EC", "industry_sector": "Information Technology",
         "aum_usd": 300.0, "weight": 0.30, "holdings_count": 5},
    ]
    session = _FakeSession([
        ("MAX(period_of_report)", _FakeResult(scalar=date(2026, 2, 28))),
        ("SELECT issuer_category", _FakeResult(rows=heavy_unclassified)),
        ("SELECT MAX(last_updated_at)",
         _FakeResult(scalar=datetime.now(timezone.utc))),
    ])
    result = asyncio.run(
        holdings_based.run_holdings_rail(_req(), session, cik_resolver=cik),
    )
    assert result.degraded is True
    assert result.degraded_reason == "low_aum_coverage"
    assert result.coverage_pct == pytest.approx(0.30)


def test_run_holdings_rail_stale_matview_logs_warning(caplog):
    async def cik(_db, _iid):
        return "0001234567"

    stale_ts = datetime.now(timezone.utc) - timedelta(days=20)
    session = _FakeSession([
        ("MAX(period_of_report)", _FakeResult(scalar=date(2026, 2, 28))),
        ("SELECT issuer_category", _FakeResult(rows=_sector_rows())),
        ("SELECT MAX(last_updated_at)", _FakeResult(scalar=stale_ts)),
    ])
    result = asyncio.run(
        holdings_based.run_holdings_rail(_req(), session, cik_resolver=cik),
    )
    # Still succeeds — matview staleness is a warning, not a degradation.
    assert result.degraded is False


def test_run_holdings_rail_empty_period_degrades():
    async def cik(_db, _iid):
        return "0001234567"

    session = _FakeSession([
        ("MAX(period_of_report)", _FakeResult(scalar=date(2026, 2, 28))),
        # Period exists in index but returns no rows (corrupt/partial)
        ("SELECT issuer_category", _FakeResult(rows=[])),
    ])
    result = asyncio.run(
        holdings_based.run_holdings_rail(_req(), session, cik_resolver=cik),
    )
    assert result.degraded is True
    assert result.degraded_reason == "empty_matview_period"


def test_run_holdings_rail_idempotent():
    """Two calls with identical request + DB state return equal results."""

    async def cik(_db, _iid):
        return "0001234567"

    def make_session():
        return _FakeSession([
            ("MAX(period_of_report)", _FakeResult(scalar=date(2026, 2, 28))),
            ("SELECT issuer_category", _FakeResult(rows=_sector_rows())),
            ("SELECT MAX(last_updated_at)",
             _FakeResult(scalar=datetime(2026, 4, 20, tzinfo=timezone.utc))),
        ])

    req = _req(fund_id=UUID("12345678-1234-5678-1234-567812345678"))
    r1 = asyncio.run(holdings_based.run_holdings_rail(req, make_session(), cik_resolver=cik))
    r2 = asyncio.run(holdings_based.run_holdings_rail(req, make_session(), cik_resolver=cik))
    assert r1 == r2


def test_run_holdings_rail_sectors_sorted_by_weight():
    async def cik(_db, _iid):
        return "0001234567"

    # Matview query uses ORDER BY weight DESC; our fake returns them in that order.
    session = _FakeSession([
        ("MAX(period_of_report)", _FakeResult(scalar=date(2026, 2, 28))),
        ("SELECT issuer_category", _FakeResult(rows=_sector_rows())),
        ("SELECT MAX(last_updated_at)",
         _FakeResult(scalar=datetime.now(timezone.utc))),
    ])
    result = asyncio.run(
        holdings_based.run_holdings_rail(_req(), session, cik_resolver=cik),
    )
    weights = [s.weight for s in result.sectors]
    assert weights == sorted(weights, reverse=True)


def test_run_holdings_rail_asset_class_fallback_scenario_a():
    """Cenário A: sector is always populated (post-enrichment). Confirm
    the dispatcher surfaces the GICS sector when present."""

    async def cik(_db, _iid):
        return "0001234567"

    rows = [
        {"issuer_category": "EC", "industry_sector": "Information Technology",
         "aum_usd": 1000.0, "weight": 1.0, "holdings_count": 50},
    ]
    session = _FakeSession([
        ("MAX(period_of_report)", _FakeResult(scalar=date(2026, 2, 28))),
        ("SELECT issuer_category", _FakeResult(rows=rows)),
        ("SELECT MAX(last_updated_at)",
         _FakeResult(scalar=datetime.now(timezone.utc))),
    ])
    result = asyncio.run(
        holdings_based.run_holdings_rail(_req(), session, cik_resolver=cik),
    )
    assert result.sectors[0].sector == "Information Technology"


# ---------------------------------------------------------------------------
# Dispatcher priority tests
# ---------------------------------------------------------------------------


def test_dispatcher_uses_holdings_rail_when_available():
    async def holdings_fetch(req, _db):
        return HoldingsBasedResult(
            sectors=(
                SectorWeight("Information Technology", "EC", 0.6, 600.0, 10),
                SectorWeight("Financials", "DBT", 0.4, 400.0, 5),
            ),
            period_of_report=date(2026, 2, 28),
            coverage_pct=1.0,
            confidence=1.0,
            holdings_count=15,
        )

    async def returns_fetch(_req, _db):
        pytest.fail("dispatcher should not call returns rail when holdings win")

    result = asyncio.run(
        compute_fund_attribution(
            _req(),
            db=None,
            returns_fetch=returns_fetch,
            holdings_fetch=holdings_fetch,
        ),
    )
    assert result.badge == RailBadge.RAIL_HOLDINGS
    assert result.holdings_based is not None
    assert result.metadata["n_sectors"] == "2"


def test_dispatcher_falls_through_when_holdings_degraded():
    import numpy as np

    async def holdings_fetch(_req, _db):
        return HoldingsBasedResult(
            sectors=(),
            period_of_report=None,
            coverage_pct=0.0,
            confidence=0.0,
            holdings_count=0,
            degraded=True,
            degraded_reason="no_filing",
        )

    rng = np.random.default_rng(42)
    r_fund = rng.normal(0.005, 0.02, 48)
    r_styles = rng.normal(0.004, 0.02, (48, 2))

    async def returns_fetch(_req, _db):
        return r_fund, r_styles, ("SPY", "AGG")

    result = asyncio.run(
        compute_fund_attribution(
            _req(),
            db=None,
            returns_fetch=returns_fetch,
            holdings_fetch=holdings_fetch,
        ),
    )
    assert result.badge == RailBadge.RAIL_RETURNS


def test_dispatcher_falls_through_when_holdings_none():
    import numpy as np

    async def holdings_fetch(_req, _db):
        return None  # no CIK — private fund

    rng = np.random.default_rng(7)
    r_fund = rng.normal(0.005, 0.02, 48)
    r_styles = rng.normal(0.004, 0.02, (48, 2))

    async def returns_fetch(_req, _db):
        return r_fund, r_styles, ("SPY", "AGG")

    result = asyncio.run(
        compute_fund_attribution(
            _req(),
            db=None,
            returns_fetch=returns_fetch,
            holdings_fetch=holdings_fetch,
        ),
    )
    assert result.badge == RailBadge.RAIL_RETURNS


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


def test_serialize_holdings_result_roundtrip():
    from vertical_engines.wealth.attribution.models import FundAttributionResult

    fund_id = UUID("12345678-1234-5678-1234-567812345678")
    holdings = HoldingsBasedResult(
        sectors=(
            SectorWeight("Information Technology", "EC", 0.6, 600.0, 10),
            SectorWeight("Financials", "DBT", 0.4, 400.0, 5),
        ),
        period_of_report=date(2026, 2, 28),
        coverage_pct=1.0,
        confidence=1.0,
        holdings_count=15,
    )
    result = FundAttributionResult(
        fund_instrument_id=fund_id,
        asof=date(2026, 3, 31),
        badge=RailBadge.RAIL_HOLDINGS,
        holdings_based=holdings,
        metadata={"n_sectors": "2"},
    )
    encoded = _serialize_result(result)
    decoded = _deserialize_result(encoded)
    assert decoded.badge == RailBadge.RAIL_HOLDINGS
    assert decoded.holdings_based is not None
    assert len(decoded.holdings_based.sectors) == 2
    assert decoded.holdings_based.sectors[0].sector == "Information Technology"
    assert decoded.holdings_based.period_of_report == date(2026, 2, 28)


def test_serialize_handles_none_holdings():
    from vertical_engines.wealth.attribution.models import FundAttributionResult

    fund_id = UUID("12345678-1234-5678-1234-567812345678")
    result = FundAttributionResult(
        fund_instrument_id=fund_id,
        asof=date(2026, 3, 31),
        badge=RailBadge.RAIL_NONE,
        reason="no_data",
    )
    encoded = _serialize_result(result)
    decoded = _deserialize_result(encoded)
    assert decoded.holdings_based is None
    assert decoded.badge == RailBadge.RAIL_NONE


# ---------------------------------------------------------------------------
# DD ch.4 copy invariants
# ---------------------------------------------------------------------------


def test_dd_ch4_holdings_copy_no_raw_jargon():
    """Sanitised render must not leak N-PORT issuer codes or quant terms."""

    from vertical_engines.wealth.dd_report.chapters import _render_attribution_block

    evidence = {
        "attribution": {
            "badge": "RAIL_HOLDINGS",
            "holdings_based": {
                "sectors": [
                    {"sector": "CORP", "weight": 0.40,
                     "issuer_category": "DBT", "aum_usd": 400.0,
                     "holdings_count": 20},
                    {"sector": "UST", "weight": 0.30,
                     "issuer_category": "DBT", "aum_usd": 300.0,
                     "holdings_count": 10},
                    {"sector": "Information Technology", "weight": 0.30,
                     "issuer_category": "EC", "aum_usd": 300.0,
                     "holdings_count": 15},
                ],
                "coverage_pct": 1.0,
            },
        },
    }
    out = "\n".join(_render_attribution_block(evidence))
    # Sanitised copy must replace raw N-PORT codes.
    assert "CORP" not in out
    assert "UST" not in out
    # But the enriched GICS sector passes through.
    assert "Information Technology" in out
    assert "Corporate" in out
    assert "US Treasury" in out
    assert "Portfolio coverage" in out


def test_dd_ch4_holdings_badge_copy():
    from vertical_engines.wealth.dd_report.chapters import _render_attribution_block

    evidence = {
        "attribution": {
            "badge": "RAIL_HOLDINGS",
            "holdings_based": {
                "sectors": [{"sector": "Financials", "weight": 1.0,
                             "issuer_category": "DBT", "aum_usd": 1000.0,
                             "holdings_count": 1}],
                "coverage_pct": 1.0,
            },
        },
    }
    out = "\n".join(_render_attribution_block(evidence))
    assert "HIGH CONFIDENCE" in out
    assert "position-level" in out


def test_dd_ch4_caps_sector_list_at_eleven():
    from vertical_engines.wealth.dd_report.chapters import _render_attribution_block

    sectors = [
        {"sector": f"Sector{i}", "weight": 1 / 15, "issuer_category": "EC",
         "aum_usd": 100.0, "holdings_count": 1}
        for i in range(15)
    ]
    evidence = {
        "attribution": {
            "badge": "RAIL_HOLDINGS",
            "holdings_based": {"sectors": sectors, "coverage_pct": 1.0},
        },
    }
    out = "\n".join(_render_attribution_block(evidence))
    # 11 rendered; 12..14 omitted
    assert "Sector10" in out
    assert "Sector11" not in out
