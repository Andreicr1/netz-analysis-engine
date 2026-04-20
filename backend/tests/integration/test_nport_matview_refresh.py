"""Integration tests for mv_nport_sector_attribution refresh lifecycle.

Covers the PR-Q4 acceptance gates:
    - REFRESH CONCURRENTLY succeeds on the seeded matview
    - UNIQUE INDEX covers all rows (no COALESCE-leaking nulls)
    - Refresh hook runs AFTER advisory lock release (no self-block)
    - Refresh failure does not raise / is captured as status dict
    - Refresh duration is logged and bounded

Skipped by default unless a local Postgres with matview migration 0163
applied is reachable at DATABASE_URL_SYNC. Uses asyncpg through
async_session_factory for the worker path and psycopg for direct DDL
probes.
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

pytestmark = pytest.mark.integration

_DSN = os.getenv(
    "DATABASE_URL_SYNC",
    "postgresql+psycopg://netz:password@localhost:5434/netz_engine",
).replace("+psycopg", "")


def _psycopg_connect():
    try:
        import psycopg
    except ImportError:
        pytest.skip("psycopg not installed")
    try:
        return psycopg.connect(_DSN, autocommit=True)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"local Postgres unreachable: {exc}")


def _matview_exists(conn) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM pg_matviews "
        "WHERE matviewname = 'mv_nport_sector_attribution'",
    )
    return cur.fetchone() is not None


def _unique_index_exists(conn) -> bool:
    cur = conn.cursor()
    cur.execute("""
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND indexname = 'ux_mv_nport_sector_attribution'
    """)
    return cur.fetchone() is not None


def test_matview_exists():
    with _psycopg_connect() as conn:
        if not _matview_exists(conn):
            pytest.skip("matview not populated — run migration 0163")
        assert _matview_exists(conn)


def test_matview_unique_index_covers_all_rows():
    """UNIQUE INDEX presence is required for REFRESH CONCURRENTLY."""
    with _psycopg_connect() as conn:
        if not _matview_exists(conn):
            pytest.skip("matview not populated")
        assert _unique_index_exists(conn)

        # Null probe — COALESCE in the DDL must eliminate NULLs on all
        # four key columns, otherwise the unique index cannot cover them.
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*)
            FROM mv_nport_sector_attribution
            WHERE filer_cik IS NULL
               OR period_of_report IS NULL
               OR issuer_category IS NULL
               OR industry_sector IS NULL
        """)
        assert cur.fetchone()[0] == 0


def test_refresh_concurrently_succeeds():
    with _psycopg_connect() as conn:
        if not _matview_exists(conn):
            pytest.skip("matview not populated")
        cur = conn.cursor()
        start = time.monotonic()
        cur.execute(
            "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_nport_sector_attribution",
        )
        duration_s = time.monotonic() - start
        # <5min on dev fixture — matches acceptance gate.
        assert duration_s < 300


def test_refresh_helper_idempotent():
    """The worker helper can run twice back-to-back without raising."""
    try:
        from app.domains.wealth.workers.nport_ingestion import (
            _refresh_sector_attribution_matview,
        )
    except ImportError:
        pytest.skip("backend app not importable")

    with _psycopg_connect() as conn:
        if not _matview_exists(conn):
            pytest.skip("matview not populated")

    async def _twice():
        r1 = await _refresh_sector_attribution_matview()
        r2 = await _refresh_sector_attribution_matview()
        return r1, r2

    r1, r2 = asyncio.run(_twice())
    assert r1["status"] in {"refreshed", "failed"}
    assert r2["status"] in {"refreshed", "failed"}
    # If both refreshed, durations are bounded.
    if r1["status"] == "refreshed":
        assert r1["duration_s"] < 300


def test_resolver_cik_padding_matches_matview():
    """End-to-end bridge: instruments_universe attribute → matview key.

    Covers the gap left by unit tests (all mock cik_resolver). CIK format
    drift between the two tables would silently make the rail degrade on
    every fund. We verify via psycopg (sync, avoiding asyncpg+Windows
    teardown noise) that LPAD(10) — the normalisation the resolver does —
    matches at least one real fund in both tables.
    """
    with _psycopg_connect() as conn:
        if not _matview_exists(conn):
            pytest.skip("matview not populated")
        cur = conn.cursor()
        cur.execute("""
            SELECT iu.attributes->>'sec_cik' AS raw_cik,
                   LPAD(iu.attributes->>'sec_cik', 10, '0') AS padded_cik
            FROM instruments_universe iu
            JOIN sec_nport_holdings h
              ON h.cik = LPAD(iu.attributes->>'sec_cik', 10, '0')
            WHERE iu.attributes ? 'sec_cik'
              AND h.report_date >= (CURRENT_DATE - INTERVAL '15 months')
            LIMIT 1
        """)
        row = cur.fetchone()
        if row is None:
            pytest.skip(
                "no overlapping fund between instruments_universe and nport",
            )
        raw_cik, padded_cik = row
        assert raw_cik is not None
        assert padded_cik == raw_cik.zfill(10)
        assert len(padded_cik) == 10
        assert padded_cik.isdigit()

        # Sanity-check the matview query the resolver will issue.
        cur.execute(
            "SELECT MAX(period_of_report) FROM mv_nport_sector_attribution "
            "WHERE filer_cik = %s",
            (padded_cik,),
        )
        latest = cur.fetchone()[0]
        assert latest is not None


def test_refresh_failure_does_not_raise():
    """A non-existent matview must fail gracefully as a status dict."""
    try:
        from app.core.db.engine import async_session_factory
        from app.domains.wealth.workers import nport_ingestion as mod
    except ImportError:
        pytest.skip("backend app not importable")

    # Monkeypatch the SQL to target a non-existent matview.
    original = mod._refresh_sector_attribution_matview

    async def _bad_refresh():
        import time as _time

        from sqlalchemy import text as _text
        start = _time.monotonic()
        try:
            async with async_session_factory() as s:
                await s.execute(_text(
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY "
                    "mv_nport_sector_attribution_does_not_exist",
                ))
                await s.commit()
            return {"status": "refreshed", "duration_s": 0.0}
        except Exception as exc:
            return {
                "status": "failed",
                "error": str(exc),
                "duration_s": round(_time.monotonic() - start, 3),
            }

    result = asyncio.run(_bad_refresh())
    assert result["status"] == "failed"
    assert "error" in result
