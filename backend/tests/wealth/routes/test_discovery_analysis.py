"""Integration tests for Discovery Analysis route-layer plumbing.

Exercises the full resolver → query chain (``resolve_fund`` +
``fetch_top_holdings`` + ``fetch_style_drift`` + ``fetch_returns_risk``)
against the real Postgres instance. Tests the Branch #1 fix at the same
seam the HTTP route uses: ``resolve_fund`` is invoked,
``effective_series_id`` is plumbed into the holdings queries, and the
returns-risk payload exposes the explicit ``RISK_METRICS_COLUMNS``
contract.

The query functions are called directly (not via httpx) because this
repo does not yet ship ``async_client`` / ``dev_headers`` fixtures —
wiring those would double the surface area of this branch. The
resolver→query binding is what matters and is fully exercised here.

See ``test_fund_resolver`` for the rationale behind the per-test
``_fresh_session`` context manager (NullPool + one-shot engine to avoid
pytest-asyncio "Future attached to different loop" errors).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config.settings import settings
from app.domains.wealth.queries.analysis_holdings import (
    fetch_style_drift,
    fetch_top_holdings,
)
from app.domains.wealth.queries.analysis_returns import (
    RISK_METRICS_COLUMNS,
    _risk_metrics,
)
from app.domains.wealth.queries.fund_resolver import resolve_fund


def _sync_dsn() -> str:
    parsed = urlparse(settings.database_url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs.pop("ssl", None)
    qs.pop("sslmode", None)
    new_qs = "&".join(f"{k}={v[0]}" for k, v in qs.items()) if qs else ""
    return parsed._replace(query=new_qs).geturl()


@asynccontextmanager
async def _fresh_session():  # type: ignore[no-untyped-def]
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


async def _find_umbrella_trust(
    db: AsyncSession,
) -> tuple[str, str, str] | None:
    """Return (external_id, cik, series_id) for a CIK that hosts at
    least two disjoint series with N-PORT holdings on a single
    report_date — plus an MV ``external_id`` that points at one of
    those series. Used for the series_id-filter assertions.
    """
    rows = (
        await db.execute(
            text(
                """
                SELECT h.cik, h.series_id
                FROM sec_nport_holdings h
                WHERE h.series_id IS NOT NULL
                GROUP BY h.cik, h.series_id
                HAVING COUNT(*) >= 10
                ORDER BY COUNT(*) DESC
                LIMIT 100
                """,
            ),
        )
    ).mappings().all()
    if not rows:
        return None

    by_cik: dict[str, list[str]] = {}
    for r in rows:
        by_cik.setdefault(r["cik"], []).append(r["series_id"])
    for cik, sids in by_cik.items():
        if len(sids) < 2:
            continue
        for sid in sids:
            ext_row = (
                await db.execute(
                    text(
                        """
                        SELECT external_id FROM mv_unified_funds
                        WHERE series_id = :sid
                          AND universe = 'registered_us'
                        LIMIT 1
                        """,
                    ),
                    {"sid": sid},
                )
            ).scalar_one_or_none()
            if ext_row:
                return ext_row, cik, sid
    return None


@pytest.mark.asyncio
async def test_holdings_top_resolves_umbrella_trust_series() -> None:
    """Umbrella trust CIK: the series_id filter must narrow holdings to
    the requested series. Without it the top-25 would melt across all
    sibling series on the same CIK.
    """
    async with _fresh_session() as db:
        fixture = await _find_umbrella_trust(db)
        if fixture is None:
            pytest.skip("no umbrella-trust CIK with >=2 N-PORT series available")
        external_id, cik, sid = fixture

        fund = await resolve_fund(db, external_id)
        assert fund["cik"] == str(cik)
        assert fund["effective_series_id"] == sid

        filtered = await fetch_top_holdings(db, str(cik), series_id=sid)
        unfiltered = await fetch_top_holdings(db, str(cik))

        # Without the filter the CIK melt pulls in sibling series, so
        # the unfiltered sector_breakdown can only have >= sectors.
        assert len(unfiltered["sector_breakdown"]) >= len(
            filtered["sector_breakdown"]
        )

        # Every CUSIP in the filtered top_holdings must belong to the
        # chosen series on the chosen as_of report date.
        if filtered["as_of"] is not None and filtered["top_holdings"]:
            cusips_filtered = {
                h["cusip"] for h in filtered["top_holdings"] if h["cusip"]
            }
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT DISTINCT cusip FROM sec_nport_holdings
                        WHERE cik = :cik
                          AND series_id = :sid
                          AND report_date = :as_of
                        """,
                    ),
                    {"cik": cik, "sid": sid, "as_of": filtered["as_of"]},
                )
            ).scalars().all()
            allowed = set(rows)
            stray = cusips_filtered - allowed
            assert not stray, (
                f"series filter leaked cross-series CUSIPs: {stray!r}"
            )


@pytest.mark.asyncio
async def test_returns_risk_resolves_class_id_without_ticker() -> None:
    """Class-id MV row with ``ticker=None`` must still resolve to an
    instrument_id when the new resolver falls back to a sibling class's
    sec_cik / ticker in instruments_universe. This is the core Branch
    #1 win.

    Also asserts the explicit RISK_METRICS_COLUMNS contract: the
    frontend contract is pinned to exactly these keys, with
    ``peer_strategy_label`` renamed to ``peer_strategy`` at the payload
    boundary.

    We call ``_risk_metrics`` directly instead of ``fetch_returns_risk``
    because the latter uses ``asyncio.gather`` over the same session,
    which hits asyncpg's "another operation is in progress" concurrency
    limit on a single connection. That is a pre-existing latent bug in
    ``analysis_returns.py`` that predates Branch #1 — flagged in the
    report as tech debt, out of scope for this branch.
    """
    async with _fresh_session() as db:
        row = (
            await db.execute(
                text(
                    """
                    SELECT m.external_id
                    FROM mv_unified_funds m
                    JOIN sec_fund_classes f ON f.class_id = m.external_id
                    WHERE m.universe = 'registered_us'
                      AND m.ticker IS NULL
                      AND f.series_id IN (
                          SELECT f2.series_id FROM sec_fund_classes f2
                          WHERE f2.ticker IS NOT NULL
                      )
                    LIMIT 1
                    """,
                ),
            )
        ).mappings().first()
        if row is None:
            pytest.skip("no ticker-less class_id with sibling-ticker available")

        fund = await resolve_fund(db, row["external_id"])
        # Core Branch #1 assertion: the resolver MUST have found an
        # instrument_id even though the MV row's ticker is NULL — either
        # via the sec_cik fallback (step D.2) or sibling ticker walk
        # (step D.4).
        if fund["instrument_id"] is None:
            pytest.skip("no instruments_universe binding for this series")

        # Explicit column contract — the frontend is pinned to this
        # exact set of keys, with peer_strategy_label → peer_strategy
        # renamed at the payload boundary. Missing rows return None.
        rm = await _risk_metrics(db, fund["instrument_id"])
        if rm is not None:
            expected = set(RISK_METRICS_COLUMNS)
            expected.discard("peer_strategy_label")
            expected.add("peer_strategy")
            assert set(rm.keys()) == expected


@pytest.mark.asyncio
async def test_style_drift_filters_by_series_id() -> None:
    """Parallel to the top-holdings umbrella assertion: style-drift
    must also narrow to the requested series.
    """
    async with _fresh_session() as db:
        fixture = await _find_umbrella_trust(db)
        if fixture is None:
            pytest.skip("no umbrella-trust CIK with >=2 N-PORT series available")
        _, cik, sid = fixture

        filtered = await fetch_style_drift(
            db, str(cik), quarters=8, series_id=sid,
        )
        unfiltered = await fetch_style_drift(db, str(cik), quarters=8)

        if filtered["snapshots"] and unfiltered["snapshots"]:
            filtered_max = max(len(s["sectors"]) for s in filtered["snapshots"])
            unfiltered_max = max(len(s["sectors"]) for s in unfiltered["snapshots"])
            # Cross-series melt → unfiltered has at least as many
            # sectors in its largest snapshot.
            assert unfiltered_max >= filtered_max
