"""Resolve a Discovery ``external_id`` to the tenant-scoped instrument.

Discovery's Col2 rows carry ``external_id`` (the ``mv_unified_funds``
primary key — a class_id/series_id/CIK/UUID/ISIN depending on the
universe branch). Downstream analytics — DD reports, risk metrics,
fact sheets — are keyed by the Wealth ``instrument_id`` catalog UUID
AND by fund CIK for SEC N-PORT holdings.

``resolve_fund`` walks the three-step chain used by the Screener's
proven resolver (``screener.py::_resolve_cik``) and adds an
instrument_id fallback ladder so umbrella-trust share classes — whose
MV row has no ticker or whose ticker does not match the only ETF
instrument the org has imported — still snap to the right instrument.

The bridge always returns:

* ``effective_series_id`` — the canonical ``S…`` identifier, even when
  the MV row stores a ``C…`` class_id. Passed to holdings queries so
  cross-series umbrella trusts do not melt into a single top-25.
* ``cik`` — None for ``ucits_eu`` / ``private_us``, a real CIK for
  registered_us / ETF / BDC / MMF.
* ``instrument_id`` — None if the global catalog has no matching
  instrument yet (caller renders empty payload + disclosure flag).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def resolve_fund(db: AsyncSession, external_id: str) -> dict[str, Any]:
    """Resolve a Discovery external_id → fund binding.

    Returns ``{external_id, universe, name, ticker, series_id,
    effective_series_id, instrument_id, cik}``. Never mutates DB.

    Steps:
        A. Fetch the MV row (404 if missing).
        B. Compute ``effective_series_id`` — MV.series_id, else walk
           ``class_id → sec_fund_classes.series_id``.
        C. Compute ``cik`` via the Screener's 3-step chain plus
           ETF/BDC/MMF future-proofing. ``None`` for UCITS/private.
        D. Compute ``instrument_id`` via layered fallback
           (ticker → sec_cik → series_id → sibling ticker → ISIN).
    """
    mv_row = (
        await db.execute(
            text(
                """
                SELECT external_id, universe, ticker, series_id, name
                FROM mv_unified_funds
                WHERE external_id = :id
                LIMIT 1
                """,
            ),
            {"id": external_id},
        )
    ).mappings().first()
    if mv_row is None:
        raise HTTPException(status_code=404, detail=f"fund {external_id} not found")

    universe: str = mv_row["universe"]
    mv_series_id: str | None = mv_row["series_id"]
    mv_ticker: str | None = mv_row["ticker"]

    # Step B — effective_series_id
    effective_series_id: str | None = mv_series_id
    if effective_series_id is None:
        effective_series_id = (
            await db.execute(
                text(
                    "SELECT series_id FROM sec_fund_classes "
                    "WHERE class_id = :id LIMIT 1",
                ),
                {"id": external_id},
            )
        ).scalar_one_or_none()

    # Step C — cik by universe branch
    cik: str | None = None
    if universe == "registered_us":
        cik = (
            await db.execute(
                text(
                    """
                    SELECT COALESCE(
                        (SELECT cik::text FROM sec_fund_classes
                            WHERE class_id  = :ext LIMIT 1),
                        (SELECT cik::text FROM sec_fund_classes
                            WHERE series_id = :ext LIMIT 1),
                        (SELECT cik::text FROM sec_registered_funds
                            WHERE cik::text = :ext LIMIT 1),
                        (SELECT cik::text FROM sec_etfs
                            WHERE series_id = :sid LIMIT 1),
                        (SELECT cik::text FROM sec_bdcs
                            WHERE series_id = :sid LIMIT 1),
                        (SELECT cik::text FROM sec_money_market_funds
                            WHERE series_id = :sid LIMIT 1)
                    ) AS cik
                    """,
                ),
                {"ext": external_id, "sid": effective_series_id},
            )
        ).scalar_one_or_none()

    # Step D — instrument_id fallback ladder
    instrument_id: str | None = None

    # D.1 — match on MV ticker (only when non-null)
    if mv_ticker:
        instrument_id = (
            await db.execute(
                text(
                    "SELECT instrument_id::text FROM instruments_universe "
                    "WHERE ticker = :ticker LIMIT 1",
                ),
                {"ticker": mv_ticker},
            )
        ).scalar_one_or_none()

    # D.2 — match on CIK via identity resolver (with legacy fallback)
    if instrument_id is None and cik is not None:
        from data_providers.identity.resolver import by_cik

        ids = await by_cik(db, cik)
        if ids:
            instrument_id = str(ids[0])
        else:
            # Legacy fallback: attributes->>'sec_cik'
            instrument_id = (
                await db.execute(
                    text(
                        "SELECT instrument_id::text FROM instruments_universe "
                        "WHERE attributes->>'sec_cik' = :cik LIMIT 1",
                    ),
                    {"cik": cik},
                )
            ).scalar_one_or_none()

    # D.3 — match on series_id attribute
    if instrument_id is None and effective_series_id is not None:
        instrument_id = (
            await db.execute(
                text(
                    "SELECT instrument_id::text FROM instruments_universe "
                    "WHERE attributes->>'series_id' = :sid LIMIT 1",
                ),
                {"sid": effective_series_id},
            )
        ).scalar_one_or_none()

    # D.4 — sibling ticker walk (oldest sibling with a ticker)
    if instrument_id is None and effective_series_id is not None:
        instrument_id = (
            await db.execute(
                text(
                    """
                    SELECT instrument_id::text FROM instruments_universe
                    WHERE ticker = (
                        SELECT ticker FROM sec_fund_classes
                        WHERE series_id = :sid AND ticker IS NOT NULL
                        ORDER BY perf_inception_date ASC NULLS LAST
                        LIMIT 1
                    )
                    LIMIT 1
                    """,
                ),
                {"sid": effective_series_id},
            )
        ).scalar_one_or_none()

    # D.5 — UCITS ISIN fallback (external_id is the ISIN)
    if instrument_id is None and universe == "ucits_eu":
        instrument_id = (
            await db.execute(
                text(
                    "SELECT instrument_id::text FROM instruments_universe "
                    "WHERE attributes->>'isin' = :isin LIMIT 1",
                ),
                {"isin": external_id},
            )
        ).scalar_one_or_none()

    # D.6 — private US: never attempts an instrument match
    if universe == "private_us":
        instrument_id = None

    return {
        "external_id": external_id,
        "universe": universe,
        "name": mv_row["name"],
        "ticker": mv_ticker,
        "series_id": mv_series_id,
        "effective_series_id": effective_series_id,
        "instrument_id": instrument_id,
        "cik": cik,
    }
