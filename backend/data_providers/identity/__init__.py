"""Canonical instrument identity resolver.

Single source of truth for CIK/CUSIP/ticker/ISIN/FIGI lookups.
All callsites that previously did:
    raw.zfill(10) / lstrip('0') / LTRIM(cik, '0') / attributes->>'sec_cik'
must call into this module instead.
"""

from backend.data_providers.identity.resolver import (
    CikIdentity,
    CusipIdentity,
    InstrumentIdentity,
    by_cik,
    by_ciks_many,
    by_cusip,
    by_isin,
    by_series_class,
    by_ticker,
    resolve_cik,
    resolve_cusip,
    resolve_full,
    resolve_many_ciks,
    resolve_many_full,
)

__all__ = [
    "CikIdentity",
    "CusipIdentity",
    "InstrumentIdentity",
    "by_cik",
    "by_ciks_many",
    "by_cusip",
    "by_isin",
    "by_series_class",
    "by_ticker",
    "resolve_cik",
    "resolve_cusip",
    "resolve_full",
    "resolve_many_ciks",
    "resolve_many_full",
]
