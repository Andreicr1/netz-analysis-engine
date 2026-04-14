"""Tests for tiingo_enrichment worker.

Covers:
- String normalization (smart quotes, NFC, empty, control chars).
- HTTP retry behaviour (401 short-circuits, 429 retries with backoff).
- SQL driver behaviour (filters, JSONB merge, idempotency) via mocked session.
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
        # "é" can be expressed as U+0065 + U+0301 (decomposed) or U+00E9 (composed).
        decomposed = "caf\u0065\u0301 bond fund"
        composed = "caf\u00e9 bond fund"
        assert mod.normalize_description(decomposed) == composed
        # Composed input should round-trip unchanged.
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


# ── HTTP fetch + retry ─────────────────────────────────────────────────


def _client_with_handler(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestFetchDescription:
    def test_worker_handles_tiingo_401(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(401, json={"detail": "unauthorized"})

        with _client_with_handler(handler) as client:
            outcome, desc = mod._fetch_description(client, "fake-key", "SPY")

        assert outcome == mod._TiingoFetchOutcome.NOT_FOUND
        assert desc == ""
        # 401 must short-circuit — no retries.
        assert calls["n"] == 1

    def test_worker_handles_tiingo_429_with_retry(self, monkeypatch) -> None:
        # Avoid waiting 2+4+... seconds during the test.
        monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] < 3:
                return httpx.Response(429, json={"detail": "rate limited"})
            return httpx.Response(
                200,
                json={"ticker": "spy", "description": "Recovered after retry."},
            )

        with _client_with_handler(handler) as client:
            outcome, desc = mod._fetch_description(client, "fake-key", "SPY")

        assert outcome == mod._TiingoFetchOutcome.OK
        assert desc == "Recovered after retry."
        assert calls["n"] == 3

    def test_fetch_description_retry_exhausted(self, monkeypatch) -> None:
        monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        with _client_with_handler(handler) as client:
            outcome, desc = mod._fetch_description(client, "fake-key", "SPY")

        assert outcome == mod._TiingoFetchOutcome.RETRY_EXHAUSTED
        assert desc == ""


# ── Worker-level behaviour ─────────────────────────────────────────────


class _FakeResult:
    def __init__(self, rows: list[dict] | None = None, scalar_value=True):
        self._rows = rows or []
        self._scalar = scalar_value

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
    """Records executed SQL + params. Models just enough of AsyncSession."""

    def __init__(self, rows: list[dict]):
        self._rows = rows
        self.executed: list[tuple[str, dict]] = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed.append((sql, dict(params) if params else {}))
        if "pg_try_advisory_lock" in sql:
            return _FakeResult(scalar_value=True)
        if "pg_advisory_unlock" in sql:
            return _FakeResult(scalar_value=True)
        if sql.lstrip().upper().startswith("SELECT") or "from instruments_universe" in sql.lower():
            return _FakeResult(rows=self._rows)
        return _FakeResult()

    async def commit(self):
        self.commits += 1


def _patch_session(rows: list[dict]):
    session = _FakeSession(rows)

    @asynccontextmanager
    async def factory():
        yield session

    return session, patch.object(mod, "async_session", factory)


def _mock_tiingo_response(desc: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ticker": "x", "description": desc})

    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _fake_api_key(monkeypatch):
    monkeypatch.setattr(mod.settings, "tiingo_api_key", "test-key")


@pytest.fixture
def _patch_http_client(monkeypatch):
    """Replace _build_http_client so every call gets an httpx MockTransport."""

    def _install(handler):
        def _factory() -> httpx.Client:
            return httpx.Client(transport=httpx.MockTransport(handler))

        monkeypatch.setattr(mod, "_build_http_client", _factory)

    return _install


class TestRunTiingoEnrichment:
    @pytest.mark.asyncio
    async def test_worker_skips_instruments_without_ticker(self, _patch_http_client) -> None:
        """The candidate query embeds ``ticker IS NOT NULL`` — ensure we rely on it."""
        _patch_http_client(lambda r: httpx.Response(200, json={"description": "x"}))

        session, ctx = _patch_session(rows=[])  # DB enforces NULL filter — worker sees 0 rows.
        with ctx:
            stats = await mod.run_tiingo_enrichment()

        assert stats["candidates"] == 0
        assert stats["processed"] == 0
        # Confirm the WHERE clause is present in the emitted SQL so the
        # filter can't silently regress in a future refactor.
        select_stmts = [sql for sql, _ in session.executed if "from instruments_universe" in sql.lower()]
        assert select_stmts
        assert "TICKER IS NOT NULL" in select_stmts[0].upper()

    @pytest.mark.asyncio
    async def test_worker_skips_recent_descriptions(self, _patch_http_client) -> None:
        """Candidate query must bound staleness with the 30-day TTL."""
        _patch_http_client(lambda r: httpx.Response(200, json={"description": "x"}))

        session, ctx = _patch_session(rows=[])
        with ctx:
            await mod.run_tiingo_enrichment()

        select_stmts = [sql for sql, _ in session.executed if "from instruments_universe" in sql.lower()]
        assert select_stmts
        assert "30 days" in select_stmts[0]

    @pytest.mark.asyncio
    async def test_worker_preserves_other_attributes(self, _patch_http_client) -> None:
        """UPDATE must use ``attributes || jsonb_build_object(...)`` — never overwrite."""
        _patch_http_client(lambda r: httpx.Response(200, json={"description": "Equity fund."}))

        iid = str(uuid.uuid4())
        session, ctx = _patch_session(rows=[{"instrument_id": iid, "ticker": "SPY"}])
        with ctx:
            stats = await mod.run_tiingo_enrichment()

        assert stats["processed"] == 1
        update_stmts = [sql for sql, _ in session.executed if "UPDATE instruments_universe" in sql]
        assert update_stmts
        sql = update_stmts[0]
        assert "||" in sql  # JSONB merge, not assignment
        assert "jsonb_build_object" in sql
        assert "tiingo_description" in sql
        assert "tiingo_description_updated_at" in sql

    @pytest.mark.asyncio
    async def test_worker_persists_empty_description(self, _patch_http_client) -> None:
        """Empty descriptions still write the timestamp to prevent weekly re-fetching."""
        _patch_http_client(lambda r: httpx.Response(200, json={"description": ""}))

        iid = str(uuid.uuid4())
        session, ctx = _patch_session(rows=[{"instrument_id": iid, "ticker": "XYZ"}])
        with ctx:
            stats = await mod.run_tiingo_enrichment()

        assert stats["empty_description"] == 1
        assert stats["processed"] == 1

    @pytest.mark.asyncio
    async def test_worker_idempotent(self, _patch_http_client) -> None:
        """Running twice against the same candidate set yields the same writes and no duplication."""
        _patch_http_client(lambda r: httpx.Response(200, json={"description": "Stable fund."}))

        iid = str(uuid.uuid4())
        rows = [{"instrument_id": iid, "ticker": "SPY"}]

        session1, ctx1 = _patch_session(rows=rows)
        with ctx1:
            stats1 = await mod.run_tiingo_enrichment()

        session2, ctx2 = _patch_session(rows=rows)
        with ctx2:
            stats2 = await mod.run_tiingo_enrichment()

        assert stats1["processed"] == stats2["processed"] == 1
        # Both runs should emit exactly one UPDATE — rerun doesn't produce duplicate statements.
        updates1 = [s for s, _ in session1.executed if "UPDATE instruments_universe" in s]
        updates2 = [s for s, _ in session2.executed if "UPDATE instruments_universe" in s]
        assert len(updates1) == 1
        assert len(updates2) == 1


class TestRunTiingoEnrichmentGuards:
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

        session = _LockedSession()

        @asynccontextmanager
        async def factory():
            yield session

        monkeypatch.setattr(mod, "async_session", factory)
        stats = await mod.run_tiingo_enrichment()
        assert stats == {"status": "skipped", "reason": "lock_held"}
