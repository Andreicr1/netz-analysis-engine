"""Tests for WMJ-007 (PR-Q156) — SCD as-of upper bound in holdings rail SQL.

Verifies that ``latest_period_for_cik`` enforces ``period_of_report <= asof``
so backdated attribution requests never pick up filings that post-date the
analysis date.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from vertical_engines.wealth.attribution import holdings_based
from vertical_engines.wealth.attribution.models import AttributionRequest

# ---------------------------------------------------------------------------
# Fakes — reuse pattern from test_attribution_holdings.py
# ---------------------------------------------------------------------------


class _FakeMappings:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return [dict(r) for r in self._rows]


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


def _req(asof: date | None = None) -> AttributionRequest:
    return AttributionRequest(
        fund_instrument_id=uuid4(),
        asof=asof or date(2026, 3, 31),
        lookback_months=60,
        min_months=36,
    )


# ---------------------------------------------------------------------------
# Test 1: latest_period_for_cik respects asof upper bound
# ---------------------------------------------------------------------------


def test_latest_period_respects_asof_upper_bound():
    """With asof=2026-01-15 and periods [2025-09-30, 2025-12-31, 2026-03-31],
    the function must return 2025-12-31 (the latest period <= asof), NOT
    2026-03-31 which would be a future filing relative to the analysis date.

    The _FakeSession matches on SQL fragments. When the SQL contains
    ``<= :asof`` (the new bound), we return 2025-12-31 — the correct
    point-in-time answer. This confirms that the SQL branch with the
    asof clause is being executed.
    """
    # The fake session sees the asof-bounded SQL and returns the correct period.
    session = _FakeSession([
        ("period_of_report <= :asof", _FakeResult(scalar=date(2025, 12, 31))),
    ])

    period = asyncio.run(
        holdings_based.latest_period_for_cik(
            session,
            "0001234567",
            not_before=date(2025, 6, 1),
            asof=date(2026, 1, 15),
        )
    )

    assert period == date(2025, 12, 31)

    # Verify that the SQL included the asof parameter
    assert len(session.calls) == 1
    _sql, params = session.calls[0]
    assert params["asof"] == date(2026, 1, 15)
    assert params["not_before"] == date(2025, 6, 1)


# ---------------------------------------------------------------------------
# Test 2: latest_period_for_cik without asof returns absolute latest (backward compat)
# ---------------------------------------------------------------------------


def test_latest_period_no_asof_returns_absolute_latest():
    """When asof is None (backward compat), the function returns the absolute
    latest period — 2026-03-31 — without any upper bound filtering.
    """
    session = _FakeSession([
        ("MAX(period_of_report)", _FakeResult(scalar=date(2026, 3, 31))),
    ])

    period = asyncio.run(
        holdings_based.latest_period_for_cik(
            session,
            "0001234567",
            not_before=None,
            asof=None,
        )
    )

    assert period == date(2026, 3, 31)

    # Verify that no asof parameter was passed
    _sql, params = session.calls[0]
    assert "asof" not in params


# ---------------------------------------------------------------------------
# Test 3: run_holdings_rail passes asof to latest_period_for_cik
# ---------------------------------------------------------------------------


def test_run_holdings_rail_passes_asof_to_latest_period():
    """Verify that run_holdings_rail calls latest_period_for_cik with
    asof=request.asof, not omitting it."""
    asof_date = date(2026, 1, 15)

    async def fake_cik(_db, _iid):
        return "0001234567"

    session = _FakeSession([
        ("MAX(period_of_report)", _FakeResult(scalar=date(2025, 12, 31))),
        ("SELECT issuer_category", _FakeResult(rows=[
            {
                "issuer_category": "EC",
                "industry_sector": "Information Technology",
                "aum_usd": 1_000_000.0,
                "weight": 1.0,
                "holdings_count": 50,
            },
        ])),
        ("SELECT MAX(last_updated_at)",
         _FakeResult(scalar=datetime.now(timezone.utc))),
    ])

    with patch.object(
        holdings_based,
        "latest_period_for_cik",
        new_callable=AsyncMock,
        return_value=date(2025, 12, 31),
    ) as mock_latest:
        asyncio.run(
            holdings_based.run_holdings_rail(
                _req(asof=asof_date),
                session,
                cik_resolver=fake_cik,
            )
        )

        mock_latest.assert_called_once()
        call_kwargs = mock_latest.call_args
        # asof must be passed as keyword arg matching request.asof
        assert call_kwargs.kwargs.get("asof") == asof_date or (
            # Also accept positional: (db, cik, not_before=..., asof=...)
            len(call_kwargs.args) >= 3 and call_kwargs.kwargs.get("asof") == asof_date
        )
        # Verify via the keyword args explicitly
        assert call_kwargs.kwargs["asof"] == asof_date


# ---------------------------------------------------------------------------
# Test 4: defense-in-depth guard rejects period > asof
# ---------------------------------------------------------------------------


def test_defense_in_depth_rejects_future_period():
    """Even if the SQL somehow returns a period > request.asof (e.g. corrupt
    matview or race condition), the guard in run_holdings_rail must treat
    it as no-valid-filing and degrade gracefully."""

    async def fake_cik(_db, _iid):
        return "0001234567"

    asof_date = date(2025, 12, 31)
    future_period = date(2026, 3, 31)

    # Simulate SQL returning a future period (bug scenario)
    with patch.object(
        holdings_based,
        "latest_period_for_cik",
        new_callable=AsyncMock,
        return_value=future_period,
    ):
        session = _FakeSession([
            # any_row check — yes, older filings exist
            ("SELECT 1 FROM mv_nport_sector_attribution", _FakeResult(scalar=1)),
        ])
        result = asyncio.run(
            holdings_based.run_holdings_rail(
                _req(asof=asof_date),
                session,
                cik_resolver=fake_cik,
            )
        )

    assert result is not None
    assert result.degraded is True
    assert result.degraded_reason == "stale_filing"
