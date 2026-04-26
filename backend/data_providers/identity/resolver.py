"""Canonical instrument identity resolver.

Single source of truth for CIK/CUSIP/ticker/ISIN/FIGI lookups.
All callsites that previously did:
    raw.zfill(10) / lstrip('0') / LTRIM(cik, '0') / attributes->>'sec_cik'
must call into this module instead.

Resolver reads from the pre-computed ``instrument_identity`` table.
One indexed query per lookup class — no N+1.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CikIdentity:
    padded: str | None
    unpadded: str | None

    def candidates(self) -> tuple[str, ...]:
        """Return all non-None CIK forms for query use."""
        return tuple(c for c in (self.padded, self.unpadded) if c)


@dataclass(frozen=True)
class CusipIdentity:
    cusip_8: str | None
    cusip_9: str | None

    def candidates(self) -> tuple[str, ...]:
        return tuple(c for c in (self.cusip_8, self.cusip_9) if c)


@dataclass(frozen=True)
class InstrumentIdentity:
    instrument_id: UUID
    cik: CikIdentity
    cusip: CusipIdentity
    sec_series_id: str | None
    sec_class_id: str | None
    sec_crd: str | None
    sec_private_fund_id: str | None
    isin: str | None
    sedol: str | None
    figi: str | None
    ticker: str | None
    ticker_exchange: str | None
    mic: str | None
    lei: str | None
    esma_manager_id: str | None
    resolution_status: str
    conflict_state: dict
    last_resolved_at: datetime | None
    sources: dict[str, dict]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SELECT_ALL = """
    SELECT instrument_id, cik_padded, cik_unpadded,
           sec_series_id, sec_class_id, sec_crd, sec_private_fund_id,
           cusip_8, cusip_9, isin, sedol, figi,
           ticker, ticker_exchange, mic,
           lei, esma_manager_id,
           resolution_status::TEXT, conflict_state, last_resolved_at,
           identity_sources
    FROM instrument_identity
"""


def _row_to_identity(row) -> InstrumentIdentity:
    return InstrumentIdentity(
        instrument_id=row.instrument_id,
        cik=CikIdentity(padded=row.cik_padded, unpadded=row.cik_unpadded),
        cusip=CusipIdentity(cusip_8=row.cusip_8, cusip_9=row.cusip_9),
        sec_series_id=row.sec_series_id,
        sec_class_id=row.sec_class_id,
        sec_crd=row.sec_crd,
        sec_private_fund_id=row.sec_private_fund_id,
        isin=row.isin,
        sedol=row.sedol,
        figi=row.figi,
        ticker=row.ticker,
        ticker_exchange=row.ticker_exchange,
        mic=row.mic,
        lei=row.lei,
        esma_manager_id=row.esma_manager_id,
        resolution_status=row.resolution_status,
        conflict_state=row.conflict_state or {},
        last_resolved_at=row.last_resolved_at,
        sources=row.identity_sources or {},
    )


def _normalize_cik(cik: str) -> tuple[str, str]:
    """Normalize CIK to (padded_10, unpadded) regardless of input form."""
    stripped = cik.lstrip("0") or "0"
    padded = stripped.zfill(10)
    return padded, stripped


# ---------------------------------------------------------------------------
# Forward lookups
# ---------------------------------------------------------------------------


async def resolve_cik(db: AsyncSession, instrument_id: UUID) -> CikIdentity:
    """Return CIK identity for a single instrument."""
    result = await db.execute(
        text(
            "SELECT cik_padded, cik_unpadded FROM instrument_identity "
            "WHERE instrument_id = :iid"
        ),
        {"iid": instrument_id},
    )
    row = result.first()
    if row is None:
        return CikIdentity(padded=None, unpadded=None)
    return CikIdentity(padded=row.cik_padded, unpadded=row.cik_unpadded)


async def resolve_cusip(db: AsyncSession, instrument_id: UUID) -> CusipIdentity:
    """Return CUSIP identity for a single instrument."""
    result = await db.execute(
        text(
            "SELECT cusip_8, cusip_9 FROM instrument_identity "
            "WHERE instrument_id = :iid"
        ),
        {"iid": instrument_id},
    )
    row = result.first()
    if row is None:
        return CusipIdentity(cusip_8=None, cusip_9=None)
    return CusipIdentity(cusip_8=row.cusip_8, cusip_9=row.cusip_9)


async def resolve_full(
    db: AsyncSession, instrument_id: UUID
) -> InstrumentIdentity | None:
    """Return full identity for a single instrument, or None if not found."""
    result = await db.execute(
        text(f"{_SELECT_ALL} WHERE instrument_id = :iid"),
        {"iid": instrument_id},
    )
    row = result.first()
    if row is None:
        return None
    return _row_to_identity(row)


# ---------------------------------------------------------------------------
# Reverse lookups — all return list[UUID], empty list on miss
# ---------------------------------------------------------------------------


async def by_cik(db: AsyncSession, cik: str) -> list[UUID]:
    """Find instruments by CIK (accepts padded or unpadded)."""
    padded, unpadded = _normalize_cik(cik)
    result = await db.execute(
        text(
            "SELECT instrument_id FROM instrument_identity "
            "WHERE cik_padded = :padded OR cik_unpadded = :unpadded"
        ),
        {"padded": padded, "unpadded": unpadded},
    )
    return [row.instrument_id for row in result.fetchall()]


async def by_cusip(db: AsyncSession, cusip: str) -> list[UUID]:
    """Find instruments by CUSIP (8 or 9 digit)."""
    if len(cusip) == 9:
        result = await db.execute(
            text(
                "SELECT instrument_id FROM instrument_identity "
                "WHERE cusip_9 = :cusip"
            ),
            {"cusip": cusip},
        )
    elif len(cusip) == 8:
        result = await db.execute(
            text(
                "SELECT instrument_id FROM instrument_identity "
                "WHERE cusip_8 = :cusip"
            ),
            {"cusip": cusip},
        )
    else:
        # Try both
        result = await db.execute(
            text(
                "SELECT instrument_id FROM instrument_identity "
                "WHERE cusip_8 = :cusip OR cusip_9 = :cusip"
            ),
            {"cusip": cusip},
        )
    return [row.instrument_id for row in result.fetchall()]


async def by_ticker(
    db: AsyncSession, ticker: str, mic: str | None = None
) -> list[UUID]:
    """Find instruments by ticker, optionally filtered by MIC."""
    if mic:
        result = await db.execute(
            text(
                "SELECT instrument_id FROM instrument_identity "
                "WHERE ticker = :ticker AND mic = :mic"
            ),
            {"ticker": ticker, "mic": mic},
        )
    else:
        result = await db.execute(
            text(
                "SELECT instrument_id FROM instrument_identity "
                "WHERE ticker = :ticker"
            ),
            {"ticker": ticker},
        )
    return [row.instrument_id for row in result.fetchall()]


async def by_isin(db: AsyncSession, isin: str) -> list[UUID]:
    """Find instruments by ISIN."""
    result = await db.execute(
        text(
            "SELECT instrument_id FROM instrument_identity WHERE isin = :isin"
        ),
        {"isin": isin},
    )
    return [row.instrument_id for row in result.fetchall()]


async def by_series_class(
    db: AsyncSession,
    series_id: str,
    class_id: str | None = None,
) -> list[UUID]:
    """Find instruments by SEC series_id, optionally filtered by class_id."""
    if class_id:
        result = await db.execute(
            text(
                "SELECT instrument_id FROM instrument_identity "
                "WHERE sec_series_id = :sid AND sec_class_id = :cid"
            ),
            {"sid": series_id, "cid": class_id},
        )
    else:
        result = await db.execute(
            text(
                "SELECT instrument_id FROM instrument_identity "
                "WHERE sec_series_id = :sid"
            ),
            {"sid": series_id},
        )
    return [row.instrument_id for row in result.fetchall()]


# ---------------------------------------------------------------------------
# Bulk variants
# ---------------------------------------------------------------------------


async def resolve_many_full(
    db: AsyncSession,
    instrument_ids: list[UUID],
) -> dict[UUID, InstrumentIdentity]:
    """Resolve full identity for multiple instruments in one query."""
    if not instrument_ids:
        return {}
    result = await db.execute(
        text(f"{_SELECT_ALL} WHERE instrument_id = ANY(:ids)"),
        {"ids": instrument_ids},
    )
    return {row.instrument_id: _row_to_identity(row) for row in result.fetchall()}


async def resolve_many_ciks(
    db: AsyncSession,
    instrument_ids: list[UUID],
) -> dict[UUID, CikIdentity]:
    """Resolve CIK identity for multiple instruments in one query."""
    if not instrument_ids:
        return {}
    result = await db.execute(
        text(
            "SELECT instrument_id, cik_padded, cik_unpadded "
            "FROM instrument_identity WHERE instrument_id = ANY(:ids)"
        ),
        {"ids": instrument_ids},
    )
    return {
        row.instrument_id: CikIdentity(
            padded=row.cik_padded, unpadded=row.cik_unpadded
        )
        for row in result.fetchall()
    }


async def by_ciks_many(
    db: AsyncSession, ciks: list[str]
) -> dict[str, list[UUID]]:
    """Reverse lookup multiple CIKs at once. Returns {cik_input: [instrument_ids]}."""
    if not ciks:
        return {}

    # Normalize all CIKs to padded form for lookup
    padded_map: dict[str, str] = {}  # padded -> original input
    padded_list: list[str] = []
    for cik in ciks:
        padded, _ = _normalize_cik(cik)
        padded_map[padded] = cik
        padded_list.append(padded)

    result = await db.execute(
        text(
            "SELECT instrument_id, cik_padded FROM instrument_identity "
            "WHERE cik_padded = ANY(:padded_list)"
        ),
        {"padded_list": padded_list},
    )

    out: dict[str, list[UUID]] = {cik: [] for cik in ciks}
    for row in result.fetchall():
        original = padded_map.get(row.cik_padded)
        if original is not None:
            out[original].append(row.instrument_id)
    return out
