"""Unit tests for PR-Q4.1 — N-PORT CUSIP Tiingo enrichment worker.

Exercises the two-phase pipeline (OpenFIGI → Tiingo) against mocked HTTP
clients and a fake async session. Validates upsert payloads, dedup,
degradation, and the ticker-case normalisation on the Tiingo UPDATE.
"""

from __future__ import annotations

import asyncio

import httpx

from app.domains.wealth.workers import nport_cusip_enrichment_tiingo as mod


class _FakeResult:
    def __init__(self, scalar=None, rows=None, rowcount=0):
        self._scalar = scalar
        self._rows = rows or []
        self.rowcount = rowcount

    def scalar(self):
        return self._scalar

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self):
        self.executed: list[tuple[str, object]] = []
        self.committed = 0
        self._queue: list[_FakeResult] = []

    def queue(self, *results: _FakeResult) -> None:
        self._queue.extend(results)

    async def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params))
        if self._queue:
            return self._queue.pop(0)
        return _FakeResult()

    async def commit(self):
        self.committed += 1


def test_chunks_yields_evenly():
    out = list(mod._chunks(list(range(250)), 100))
    assert [len(c) for c in out] == [100, 100, 50]


def test_distinct_cusips_without_ticker_returns_cusips():
    session = _FakeSession()
    session.queue(_FakeResult(rows=[("000111AAA",), ("000222BBB",)]))
    out = asyncio.run(mod._distinct_cusips_without_ticker(session))
    assert out == ["000111AAA", "000222BBB"]


def test_distinct_cusips_drops_null_rows():
    session = _FakeSession()
    session.queue(_FakeResult(rows=[("000111AAA",), (None,), ("000333CCC",)]))
    out = asyncio.run(mod._distinct_cusips_without_ticker(session))
    assert out == ["000111AAA", "000333CCC"]


def test_upsert_ticker_map_marks_unresolved():
    from data_providers.sec.shared import CusipTickerResult

    session = _FakeSession()
    results = [
        CusipTickerResult(
            cusip="000111AAA", ticker="AAPL", issuer_name="Apple Inc",
            exchange="US", security_type="Common Stock",
            figi="BBG000B9XRY4", composite_figi="BBG000B9XRY4",
            resolved_via="openfigi", is_tradeable=True,
        ),
        CusipTickerResult(
            cusip="000222BBB", ticker=None, issuer_name=None,
            exchange=None, security_type=None, figi=None,
            composite_figi=None, resolved_via="unresolved", is_tradeable=False,
        ),
    ]
    resolved = asyncio.run(mod._upsert_ticker_map(session, results))
    assert resolved == 1  # only AAPL counted
    assert session.committed == 1


def test_upsert_ticker_map_empty_input_noop():
    session = _FakeSession()
    resolved = asyncio.run(mod._upsert_ticker_map(session, []))
    assert resolved == 0
    assert session.committed == 0


def test_distinct_tickers_needing_meta():
    session = _FakeSession()
    session.queue(_FakeResult(rows=[("AAPL",), ("MSFT",)]))
    out = asyncio.run(mod._distinct_tickers_needing_meta(session))
    assert out == ["AAPL", "MSFT"]


def test_upsert_tiingo_meta_counts_only_with_sector():
    session = _FakeSession()
    metas = [
        {"ticker": "aapl", "sector": "Technology",
         "industry": "Consumer Electronics", "sicCode": 3571},
        {"ticker": "abcd", "sector": None, "industry": None, "sicCode": None},
        {"ticker": None},  # dropped — no ticker
    ]
    enriched = asyncio.run(mod._upsert_tiingo_meta(session, metas))
    assert enriched == 1
    assert session.committed == 1
    # Verify ticker was uppercased in the UPDATE params.
    _, params = session.executed[0]
    upper = [p for p in params if p.get("ticker") == "AAPL"]
    assert upper, "ticker normalisation to uppercase missing"


def test_upsert_tiingo_meta_drops_evaluation_sentinel():
    """Free-tier gate: Tiingo returns 'Field not available for free/evaluation'
    as a string in every restricted field. Must be scrubbed to None, and
    rows with nothing usable must be skipped entirely (not UPDATE'd)."""
    session = _FakeSession()
    sentinel = "Field not available for free/evaluation"
    metas = [
        {"ticker": "amzn", "sector": sentinel, "industry": sentinel,
         "sicCode": sentinel},
        {"ticker": "aapl", "sector": "Technology",
         "industry": "Consumer Electronics", "sicCode": 3571},
    ]
    enriched = asyncio.run(mod._upsert_tiingo_meta(session, metas))
    assert enriched == 1  # AMZN skipped, AAPL counted
    # Only one UPDATE issued (AAPL); AMZN filtered before SQL.
    _, params = session.executed[0]
    assert len(params) == 1
    assert params[0]["ticker"] == "AAPL"


def test_upsert_tiingo_meta_coerces_sic_to_int():
    session = _FakeSession()
    metas = [
        {"ticker": "aapl", "sector": "Technology", "industry": "X",
         "sicCode": "3571"},  # stringified int
    ]
    asyncio.run(mod._upsert_tiingo_meta(session, metas))
    _, params = session.executed[0]
    assert params[0]["sic_code"] == 3571
    assert isinstance(params[0]["sic_code"], int)


def test_scrub_tiingo_value_passthrough_non_sentinel():
    assert mod._scrub_tiingo_value("Technology") == "Technology"
    assert mod._scrub_tiingo_value(3571) == 3571
    assert mod._scrub_tiingo_value(None) is None


def test_scrub_tiingo_value_strips_sentinel():
    assert mod._scrub_tiingo_value("Field not available for free/evaluation") is None


def test_upsert_tiingo_meta_empty_noop():
    session = _FakeSession()
    assert asyncio.run(mod._upsert_tiingo_meta(session, [])) == 0
    assert session.committed == 0


# ---------------------------------------------------------------------------
# HTTP integration via httpx.MockTransport
# ---------------------------------------------------------------------------


def test_fetch_tiingo_meta_batch_parses_aapl_msft():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.tiingo.com"
        assert "tickers=AAPL" in str(request.url) and "MSFT" in str(request.url)
        return httpx.Response(200, json=[
            {
                "permaTicker": "US000000000038", "ticker": "aapl",
                "name": "Apple Inc", "isActive": True, "isADR": False,
                "sector": "Technology", "industry": "Consumer Electronics",
                "sicCode": 3571,
            },
            {
                "permaTicker": "US000000000039", "ticker": "msft",
                "name": "Microsoft Corp", "isActive": True, "isADR": False,
                "sector": "Technology", "industry": "Software—Infrastructure",
                "sicCode": 7372,
            },
        ])

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await mod._fetch_tiingo_meta_batch(c, "token", ["AAPL", "MSFT"])

    out = asyncio.run(_run())
    assert len(out) == 2
    assert out[0]["sector"] == "Technology"
    assert out[0]["sicCode"] == 3571


def test_fetch_tiingo_meta_batch_handles_http_error():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await mod._fetch_tiingo_meta_batch(c, "token", ["AAPL"])

    # Never raises; returns empty list.
    assert asyncio.run(_run()) == []


def test_fetch_tiingo_meta_batch_handles_unexpected_shape():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "oops"})

    async def _run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await mod._fetch_tiingo_meta_batch(c, "token", ["AAPL"])

    assert asyncio.run(_run()) == []


# ---------------------------------------------------------------------------
# Matview refresh + orchestration
# ---------------------------------------------------------------------------


def test_refresh_matview_returns_status_dict(monkeypatch):
    class _FakeAsyncSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_a):
            return None
        async def execute(self, *_a):
            return _FakeResult()
        async def commit(self):
            return None

    monkeypatch.setattr(mod, "async_session", lambda: _FakeAsyncSession())
    result = asyncio.run(mod._refresh_matview())
    assert result["status"] == "refreshed"
    assert "duration_s" in result


def test_run_skips_when_lock_held(monkeypatch):
    class _LockedSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_a):
            return None
        async def execute(self, *_a, **_kw):
            return _FakeResult(scalar=False)

    monkeypatch.setattr(mod, "async_session", lambda: _LockedSession())
    result = asyncio.run(mod.run())
    assert result == {"status": "skipped", "reason": "lock_held"}


def test_run_happy_path_calls_all_phases(monkeypatch):
    calls: list[str] = []

    class _OkSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_a):
            return None
        async def execute(self, stmt, *_a, **_kw):
            s = str(stmt)
            if "pg_try_advisory_lock" in s:
                return _FakeResult(scalar=True)
            return _FakeResult()

    monkeypatch.setattr(mod, "async_session", lambda: _OkSession())

    async def fake_phase_a(_db, **_kw):
        calls.append("A")
        return {"candidates": 0, "resolved": 0, "batches": 0}

    async def fake_phase_b(_db, **_kw):
        calls.append("B")
        return {"candidates": 0, "enriched": 0, "batches": 0}

    async def fake_propagate(_db):
        calls.append("propagate")
        return 0

    async def fake_refresh():
        calls.append("refresh")
        return {"status": "refreshed", "duration_s": 0.0}

    monkeypatch.setattr(mod, "_phase_resolve_tickers", fake_phase_a)
    monkeypatch.setattr(mod, "_phase_fetch_tiingo_meta", fake_phase_b)
    monkeypatch.setattr(mod, "_propagate_to_nport_holdings", fake_propagate)
    monkeypatch.setattr(mod, "_refresh_matview", fake_refresh)

    summary = asyncio.run(mod.run())
    assert calls == ["A", "B", "propagate", "refresh"]
    assert summary["status"] == "completed"
    assert summary["matview_refresh"]["status"] == "refreshed"


def test_phase_b_skips_when_no_api_key(monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    session = _FakeSession()
    result = asyncio.run(mod._phase_fetch_tiingo_meta(session, max_batches=None))
    assert result["skipped"] is True
