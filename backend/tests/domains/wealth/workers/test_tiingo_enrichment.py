"""Tests for tiingo_enrichment worker.

Covers:
- String normalization (smart quotes, NFC, empty, control chars).
- HTTP fetch behaviour (401/404, 429 circuit breaker, transient retry).
- SQL driver behaviour (candidate query filters, UPDATE per instrument, idempotency).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import patch

import httpx
import pytest

from app.domains.wealth.workers import tiingo_enrichment as mod

# ── Normalization ─────────────────────────────────────────────────────


class TestNormalizeDescription:
    def test_normalize_description_smart_quotes(self) -> None:
        raw = "It\x92s a \x93growth\x94 fund \x96 long\x97term."
        out = mod.normalize_description(raw)
        assert out == 'It\'s a "growth" fund - long--term.'

    def test_normalize_description_nfc(self) -> None:
        decomposed = "caf\u0065\u0301 bond fund"
        composed = "caf\u00e9 bond fund"
        assert mod.normalize_description(decomposed) == composed
        assert mod.normalize_description(composed) == composed

    def test_normalize_description_empty(self) -> None:
        assert mod.normalize_description("") == ""
        assert mod.normalize_description(None) == ""
        assert mod.normalize_description("   ") == ""

    def test_normalize_description_control_chars(self) -> None:
        raw = "Fund\x00 desc\x07ription\nwith\ttabs"
        out = mod.normalize_description(raw)
        assert "\x00" not in out
        assert "\x07" not in out
        assert "\n" in out
        assert "\t" in out
        assert out.startswith("Fund")


# ── HTTP fetch + circuit breaker ──────────────────────────────────────


def _client_with_handler(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestFetchMeta:
    def test_worker_handles_tiingo_401(self) -> None:
        calls = {"n": 0}
        breaker = mod._CircuitBreaker(threshold=30)

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(401, json={"detail": "unauthorized"})

        with _client_with_handler(handler) as client:
            outcome, meta = mod._fetch_meta(client, "fake-key", "SPY", breaker)

        assert outcome == mod._TiingoFetchOutcome.NOT_FOUND
        assert meta.description == ""
        assert calls["n"] == 1  # 401 short-circuits — no retry.
        assert breaker.total_429s == 0

    def test_worker_handles_tiingo_429_feeds_circuit_breaker(self) -> None:
        breaker = mod._CircuitBreaker(threshold=30)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"detail": "rate limited"})

        with _client_with_handler(handler) as client:
            outcome, _ = mod._fetch_meta(client, "fake-key", "SPY", breaker)

        assert outcome == mod._TiingoFetchOutcome.RATE_LIMITED
        # 429 does NOT retry — single call, one breaker tick.
        assert breaker.total_429s == 1

    def test_transient_error_retries_then_gives_up(self, monkeypatch) -> None:
        monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
        breaker = mod._CircuitBreaker(threshold=30)

        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(503)

        with _client_with_handler(handler) as client:
            outcome, _ = mod._fetch_meta(client, "fake-key", "SPY", breaker)

        assert outcome == mod._TiingoFetchOutcome.TRANSIENT_ERROR
        assert calls["n"] == mod._TRANSIENT_RETRY_ATTEMPTS

    def test_200_captures_start_end_dates(self) -> None:
        breaker = mod._CircuitBreaker(threshold=30)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "ticker": "spy",
                    "description": "SPDR S&P 500 ETF Trust.",
                    "startDate": "1993-01-29",
                    "endDate": "2026-04-14",
                },
            )

        with _client_with_handler(handler) as client:
            outcome, meta = mod._fetch_meta(client, "fake-key", "SPY", breaker)

        assert outcome == mod._TiingoFetchOutcome.OK
        assert meta.description == "SPDR S&P 500 ETF Trust."
        assert meta.start_date == "1993-01-29"
        assert meta.end_date == "2026-04-14"


class TestCircuitBreaker:
    def test_threshold_triggers_abort(self) -> None:
        breaker = mod._CircuitBreaker(threshold=3)
        for _ in range(2):
            breaker.record_429()
        assert not breaker.should_abort()
        breaker.record_429()
        assert breaker.should_abort()

    def test_success_resets_consecutive_counter(self) -> None:
        breaker = mod._CircuitBreaker(threshold=3)
        breaker.record_429()
        breaker.record_429()
        breaker.record_success()
        breaker.record_429()
        assert not breaker.should_abort()  # Streak broken — 2 < 3.
        assert breaker.total_429s == 3     # But cumulative keeps counting.


# ── Worker-level behaviour ─────────────────────────────────────────────


class _FakeResult:
    def __init__(
        self,
        rows: list[dict] | None = None,
        scalar_value=True,
        rowcount: int = 0,
    ):
        self._rows = rows or []
        self._scalar = scalar_value
        self.rowcount = rowcount

    def mappings(self):
        class _Mappings:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return self._rows

        return _Mappings(self._rows)

    def scalar(self):
        return self._scalar


class _FakeSession:
    def __init__(self, candidate_rows: list[dict] | None = None, rowcount: int = 1):
        self._rows = candidate_rows or []
        self._rowcount = rowcount
        self.executed: list[tuple[str, dict]] = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed.append((sql, dict(params) if params else {}))
        if "pg_try_advisory_lock" in sql:
            return _FakeResult(scalar_value=True)
        if "pg_advisory_unlock" in sql:
            return _FakeResult(scalar_value=True)
        lower = sql.lower()
        if lower.lstrip().startswith("select") and "from instruments_universe" in lower:
            return _FakeResult(rows=self._rows)
        if "update instruments_universe" in lower:
            return _FakeResult(rowcount=self._rowcount)
        return _FakeResult()

    async def commit(self):
        self.commits += 1


def _patch_session(rows: list[dict] | None = None, rowcount: int = 1):
    session = _FakeSession(candidate_rows=rows, rowcount=rowcount)

    @asynccontextmanager
    async def factory():
        yield session

    return session, patch.object(mod, "async_session", factory)


@pytest.fixture(autouse=True)
def _fake_api_key(monkeypatch):
    monkeypatch.setattr(mod.settings, "tiingo_api_key", "test-key")


@pytest.fixture(autouse=True)
def _no_pacing_sleep(monkeypatch):
    """Tests don't need the 1s per-request pacing — skip all sleeps."""
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)


@pytest.fixture
def _patch_http_client(monkeypatch):
    def _install(handler):
        def _factory() -> httpx.Client:
            return httpx.Client(transport=httpx.MockTransport(handler))

        monkeypatch.setattr(mod, "_build_http_client", _factory)

    return _install


class TestCandidateQuery:
    @pytest.mark.asyncio
    async def test_candidate_query_filters_and_orders(self, _patch_http_client) -> None:
        _patch_http_client(lambda r: httpx.Response(200, json={"description": "x"}))

        session, ctx = _patch_session()
        with ctx:
            await mod.run_tiingo_enrichment()

        selects = [
            sql for sql, _ in session.executed
            if "from instruments_universe" in sql.lower() and sql.lstrip().lower().startswith("select")
        ]
        assert len(selects) == 1  # Single candidate query — no CIK/solo split.
        sql = selects[0]
        assert "TICKER IS NOT NULL" in sql.upper()
        assert "30 days" in sql
        assert "ORDER BY instrument_id" in sql  # Deterministic checkpoint order.


class TestWorkerIntegration:
    @pytest.mark.asyncio
    async def test_successful_fetch_persists_description_and_dates(self, _patch_http_client) -> None:
        _patch_http_client(
            lambda r: httpx.Response(
                200,
                json={
                    "description": "Equity index fund.",
                    "startDate": "1976-08-31",
                    "endDate": "2026-04-14",
                },
            )
        )

        iid = str(uuid.uuid4())
        session, ctx = _patch_session(rows=[{"instrument_id": iid, "ticker": "VFINX"}])
        with ctx:
            stats = await mod.run_tiingo_enrichment()

        assert stats["candidates"] == 1
        assert stats["processed"] == 1
        assert stats["with_description"] == 1
        updates = [sql for sql, _ in session.executed if "update instruments_universe" in sql.lower()]
        assert len(updates) == 1
        sql = updates[0]
        assert "||" in sql
        for key in (
            "tiingo_description",
            "tiingo_description_updated_at",
            "tiingo_start_date",
            "tiingo_end_date",
        ):
            assert key in sql
        # The UPDATE WHERE clause scopes to a single instrument.
        assert "instrument_id = CAST(:iid AS uuid)" in sql

    @pytest.mark.asyncio
    async def test_empty_description_still_writes_timestamp(self, _patch_http_client) -> None:
        _patch_http_client(lambda r: httpx.Response(200, json={"description": ""}))

        iid = str(uuid.uuid4())
        session, ctx = _patch_session(rows=[{"instrument_id": iid, "ticker": "XYZ"}])
        with ctx:
            stats = await mod.run_tiingo_enrichment()

        assert stats["empty_description"] == 1
        updates = [sql for sql, _ in session.executed if "update instruments_universe" in sql.lower()]
        assert len(updates) == 1

    @pytest.mark.asyncio
    async def test_rate_limit_skips_write(self, _patch_http_client) -> None:
        _patch_http_client(lambda r: httpx.Response(429, json={"detail": "rate limited"}))

        iid = str(uuid.uuid4())
        session, ctx = _patch_session(rows=[{"instrument_id": iid, "ticker": "ANY"}])
        with ctx:
            stats = await mod.run_tiingo_enrichment()

        assert stats["rate_limited"] == 1
        assert stats["processed"] == 0
        # No UPDATE fires — row stays unprocessed for next TTL cycle.
        updates = [sql for sql, _ in session.executed if "update instruments_universe" in sql.lower()]
        assert updates == []

    @pytest.mark.asyncio
    async def test_circuit_breaker_aborts_early(self, _patch_http_client, monkeypatch) -> None:
        """If every candidate 429s, the breaker should stop the loop before completion."""
        monkeypatch.setattr(mod, "_CONSECUTIVE_429_CIRCUIT_BREAKER", 2)
        monkeypatch.setattr(mod, "_INCREMENTAL_COMMIT_EVERY", 2)

        _patch_http_client(lambda r: httpx.Response(429))

        rows = [{"instrument_id": str(uuid.uuid4()), "ticker": f"T{i}"} for i in range(10)]
        session, ctx = _patch_session(rows=rows)
        with ctx:
            stats = await mod.run_tiingo_enrichment()

        assert stats["aborted_early"] is True
        assert stats["rate_limited"] >= 2
        assert stats["processed"] == 0  # Never wrote anything.


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_worker_idempotent(self, _patch_http_client) -> None:
        _patch_http_client(lambda r: httpx.Response(200, json={"description": "Stable."}))

        iid = str(uuid.uuid4())
        rows = [{"instrument_id": iid, "ticker": "SPY"}]

        session1, ctx1 = _patch_session(rows=rows)
        with ctx1:
            stats1 = await mod.run_tiingo_enrichment()

        session2, ctx2 = _patch_session(rows=rows)
        with ctx2:
            stats2 = await mod.run_tiingo_enrichment()

        assert stats1["processed"] == stats2["processed"] == 1
        updates1 = [s for s, _ in session1.executed if "update instruments_universe" in s.lower()]
        updates2 = [s for s, _ in session2.executed if "update instruments_universe" in s.lower()]
        assert len(updates1) == 1
        assert len(updates2) == 1


class TestGuards:
    @pytest.mark.asyncio
    async def test_no_api_key_short_circuits(self, monkeypatch) -> None:
        monkeypatch.setattr(mod.settings, "tiingo_api_key", "")
        stats = await mod.run_tiingo_enrichment()
        assert stats == {"status": "skipped", "reason": "no_api_key"}

    @pytest.mark.asyncio
    async def test_lock_held_short_circuits(self, monkeypatch) -> None:
        class _LockedSession:
            async def execute(self, stmt, params=None):
                if "pg_try_advisory_lock" in str(stmt):
                    return _FakeResult(scalar_value=False)
                return _FakeResult(scalar_value=True)

            async def commit(self):
                pass

        @asynccontextmanager
        async def factory():
            yield _LockedSession()

        monkeypatch.setattr(mod, "async_session", factory)
        stats = await mod.run_tiingo_enrichment()
        assert stats == {"status": "skipped", "reason": "lock_held"}

    @pytest.mark.asyncio
    async def test_empty_candidate_set_returns_zero_stats(self, _patch_http_client) -> None:
        _patch_http_client(lambda r: httpx.Response(200, json={"description": "x"}))

        session, ctx = _patch_session(rows=[])
        with ctx:
            stats = await mod.run_tiingo_enrichment()

        assert stats["candidates"] == 0
        assert stats["processed"] == 0
