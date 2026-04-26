"""ESMA data provider models — frozen dataclasses for all ESMA data types.

Fully standalone: zero imports from ``app.*``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ── ESMA Manager ─────────────────────────────────────────────────


@dataclass(frozen=True)
class EsmaManager:
    """European fund manager from ESMA Register."""

    esma_id: str
    lei: str | None
    company_name: str
    country: str | None
    authorization_status: str | None
    fund_count: int | None
    sec_crd_number: str | None = None
    data_fetched_at: str | None = None


# ── ESMA Fund ────────────────────────────────────────────────────


@dataclass(frozen=True)
class EsmaFund:
    """UCITS fund legal entity from ESMA Register.

    Natural PK on LEI (20-char Legal Entity Identifier).
    The Register's "ISIN" field actually stores LEIs for UCITS funds.
    Real ISINs live in ``EsmaSecurity`` (FIRDS FULINS_C).
    """

    lei: str
    fund_name: str
    esma_manager_id: str
    domicile: str | None
    fund_type: str | None
    host_member_states: list[str] = field(default_factory=list)
    yahoo_ticker: str | None = None
    ticker_resolved_at: str | None = None
    data_fetched_at: str | None = None


# ── ISIN Resolution ──────────────────────────────────────────────


@dataclass(frozen=True)
class IsinResolution:
    """Result of ISIN → Yahoo Finance ticker resolution via OpenFIGI."""

    isin: str
    yahoo_ticker: str | None
    exchange: str | None
    resolved_via: str  # "openfigi" | "unresolved"
    is_tradeable: bool
