"""Integration tests for ``resolve_fund`` — Branch #1 fix.

These exercise the real Postgres instance. No mocks per Andrei's
standing rule (mocked DB tests drift from prod).

Architecture notes for this file:

* We do NOT reuse ``app.core.db.engine.async_session_factory`` because
  pytest-asyncio's session-scoped loop combined with SQLAlchemy's async
  pool pins the internal futures to whichever task first touches the
  pool — the second test dies with "Future attached to different loop".
* We also avoid an async fixture — the same binding bug bites during
  fixture teardown because the finalizer runs on a different task than
  the fixture body.
* Instead every test is its own self-contained ``async with`` block
  that creates a one-shot ``NullPool`` engine, uses it, disposes it —
  all on the same task.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config.settings import settings
from app.domains.wealth.queries.fund_resolver import resolve_fund


def _sync_dsn() -> str:
    """Strip ssl/sslmode query params — asyncpg rejects them."""
    parsed = urlparse(settings.database_url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs.pop("ssl", None)
    qs.pop("sslmode", None)
    new_qs = "&".join(f"{k}={v[0]}" for k, v in qs.items()) if qs else ""
    return parsed._replace(query=new_qs).geturl()


@asynccontextmanager
async def _fresh_session():  # type: ignore[no-untyped-def]
    """One-shot NullPool engine + session, fully scoped to the caller's
    task. Skips the current test if Postgres is unreachable.
    """
    engine = create_async_engine(_sync_dsn(), poolclass=NullPool)
    try:
        async with engine.connect() as ping:
            await ping.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        pytest.skip(f"postgres not reachable: {exc}")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            try:
                yield session
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------- #
# Unit tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_resolve_fund_class_id_walks_to_cik() -> None:
    """Class_id external_id resolves CIK via sec_fund_classes chain.

    C000000012 (BNY Mellon Appreciation Fund class A) → series S000000008,
    CIK 318478. Stable MV row / stable sec_fund_classes row.
    """
    async with _fresh_session() as db:
        fund = await resolve_fund(db, "C000000012")
        assert fund["universe"] == "registered_us"
        assert fund["cik"] == "318478"
        assert fund["effective_series_id"] == "S000000008"
        # DGAGX itself is missing from instruments_universe but a sibling
        # class DGYGX exists with attributes.sec_cik = 318478 — so the
        # new resolver must still return a non-null instrument_id via
        # the sec_cik fallback (step D.2) or sibling walk (step D.4).
        assert fund["instrument_id"] is not None


@pytest.mark.asyncio
async def test_resolve_fund_series_id_as_external_id() -> None:
    """External_id is an S-prefixed series_id (mv_unified_funds stores
    series-level rows where external_id = series_id).

    The CIK chain's second branch (``sec_fund_classes WHERE series_id
    = :ext``) must fire. We probe a specific row whose series_id maps
    to exactly one distinct CIK in sec_fund_classes — avoiding the 27
    duplicated-CIK rows caused by data quality issues in the source.
    """
    async with _fresh_session() as db:
        row = (
            await db.execute(
                text(
                    """
                    SELECT m.external_id, MIN(f.cik) AS cik
                    FROM mv_unified_funds m
                    JOIN sec_fund_classes f ON f.series_id = m.external_id
                    WHERE m.universe = 'registered_us'
                      AND m.external_id LIKE 'S%'
                    GROUP BY m.external_id
                    HAVING COUNT(DISTINCT f.cik) = 1
                    LIMIT 1
                    """,
                ),
            )
        ).mappings().first()
        if row is None:
            pytest.skip("no S-prefixed registered_us MV row with sec_fund_classes")

        fund = await resolve_fund(db, row["external_id"])
        assert fund["universe"] == "registered_us"
        # Both resolver and probe query hit sec_fund_classes — CIKs match.
        assert fund["cik"] == str(row["cik"])


@pytest.mark.asyncio
async def test_resolve_fund_raw_cik_external_id() -> None:
    """External_id is a bare padded CIK string (e.g. '0000002110').

    These rows exist in mv_unified_funds with universe=registered_us and
    resolve via the ``sec_registered_funds.cik::text = :ext`` branch.
    """
    async with _fresh_session() as db:
        row = (
            await db.execute(
                text(
                    """
                    SELECT m.external_id
                    FROM mv_unified_funds m
                    JOIN sec_registered_funds r ON r.cik = m.external_id
                    WHERE m.universe = 'registered_us'
                      AND m.external_id ~ '^[0-9]+$'
                    LIMIT 1
                    """,
                ),
            )
        ).mappings().first()
        if row is None:
            pytest.skip("no bare-CIK registered_us row in mv_unified_funds")

        fund = await resolve_fund(db, row["external_id"])
        assert fund["universe"] == "registered_us"
        # The chain's third branch must fire → cik == padded external_id.
        assert fund["cik"] == row["external_id"]


@pytest.mark.asyncio
async def test_resolve_fund_ucits_returns_null_cik() -> None:
    """UCITS funds never have a SEC N-PORT CIK."""
    async with _fresh_session() as db:
        row = (
            await db.execute(
                text(
                    "SELECT external_id FROM mv_unified_funds "
                    "WHERE universe = 'ucits_eu' LIMIT 1",
                ),
            )
        ).mappings().first()
        if row is None:
            pytest.skip("no ucits_eu rows in mv_unified_funds")
        fund = await resolve_fund(db, row["external_id"])
        assert fund["universe"] == "ucits_eu"
        assert fund["cik"] is None


@pytest.mark.asyncio
async def test_resolve_fund_private_us_both_null() -> None:
    """private_us UUID external_id: cik and instrument_id both None."""
    async with _fresh_session() as db:
        row = (
            await db.execute(
                text(
                    "SELECT external_id FROM mv_unified_funds "
                    "WHERE universe = 'private_us' LIMIT 1",
                ),
            )
        ).mappings().first()
        if row is None:
            pytest.skip("no private_us rows in mv_unified_funds")
        fund = await resolve_fund(db, row["external_id"])
        assert fund["universe"] == "private_us"
        assert fund["cik"] is None
        assert fund["instrument_id"] is None


@pytest.mark.asyncio
async def test_resolve_fund_unknown_external_id_raises_404() -> None:
    """Regression guard: missing external_id must raise a 404."""
    bogus = f"DOES_NOT_EXIST_{uuid.uuid4().hex}"
    async with _fresh_session() as db:
        with pytest.raises(HTTPException) as exc:
            await resolve_fund(db, bogus)
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_resolve_fund_sibling_class_ticker_fallback() -> None:
    """Step D.4 — when the MV ticker is null, the resolver walks to the
    oldest sibling class in the same series and uses its ticker to find
    an instrument.

    Concretely: C000000012 (DGAGX) is missing from instruments_universe,
    but the sibling class DGYGX (C000053229) is present with
    sec_cik=318478. The resolver must therefore return a non-null
    instrument_id via D.2 (sec_cik) or D.4 (sibling walk).
    """
    async with _fresh_session() as db:
        fund = await resolve_fund(db, "C000000012")
        assert fund["instrument_id"] is not None
        assert fund["effective_series_id"] == "S000000008"


@pytest.mark.asyncio
async def test_resolve_fund_monotonic_superset() -> None:
    """The new resolver must never downgrade a previously non-null binding.

    Sweep a sample of registered_us MV rows whose ticker is already
    present in instruments_universe — the population the OLD resolver
    handled. For each, the NEW resolver must return a non-null
    instrument_id. Guards against accidental regression where the
    rewrite drops a case the shallow lookup used to handle.
    """
    async with _fresh_session() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT m.external_id
                    FROM mv_unified_funds m
                    JOIN instruments_universe iu ON iu.ticker = m.ticker
                    WHERE m.universe = 'registered_us'
                      AND m.ticker IS NOT NULL
                    LIMIT 10
                    """,
                ),
            )
        ).mappings().all()
        if not rows:
            pytest.skip("no registered_us rows with ticker-matched instruments")

        for r in rows:
            fund = await resolve_fund(db, r["external_id"])
            assert fund["instrument_id"] is not None, (
                f"regression: {r['external_id']} had a non-null "
                "instrument_id under the old resolver; new resolver "
                "must not downgrade it"
            )
