"""Institutional Service — 13F reverse lookup for institutional investor allocations.

Discovers institutional filers via EFTS keyword search, delegates 13F parsing
to ``ThirteenFService`` (zero duplication), and persists allocations to
``sec_institutional_allocations``.

Coverage: managers with US-registered securities (BDCs, REITs, master funds,
hybrid funds with public sleeve).  Direct private credit deals and purely
offshore structures without a US master do not appear in 13F holdings.

Async service.  Rate limit: shared EDGAR rate limiter (8 req/s).
Lifecycle: Instantiate ONCE in FastAPI lifespan().
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.shared.models import Sec13fHolding as Sec13fHoldingModel
from app.shared.models import (
    SecInstitutionalAllocation as SecInstitutionalAllocationModel,
)
from data_providers.sec.models import (
    CoverageType,
    InstitutionalAllocation,
    InstitutionalOwnershipResult,
)
from data_providers.sec.shared import (
    SEC_USER_AGENT,
    check_edgar_rate,
    resolve_cik,
    run_in_sec_thread,
)

logger = structlog.get_logger()

_CIK_RE = re.compile(r"^\d{1,10}$")

# Upsert chunk size (asyncpg parameter limit).
_CHUNK_SIZE = 2000

# EFTS search endpoint for 13F filer discovery.
_EFTS_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

# Keywords for institutional filer discovery.
_INSTITUTIONAL_KEYWORDS = ["endowment", "pension", "foundation", "sovereign", "insurance"]

# filer_type classification from entity name.
_FILER_TYPE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("endowment", re.compile(r"\bendowment\b", re.IGNORECASE)),
    ("pension", re.compile(r"\bpension\b|\bretirement\b", re.IGNORECASE)),
    ("foundation", re.compile(r"\bfoundation\b", re.IGNORECASE)),
    ("sovereign", re.compile(r"\bsovereign\b|\binvestment authority\b", re.IGNORECASE)),
    ("insurance", re.compile(r"\binsurance\b|\bassurance\b|\blife\b", re.IGNORECASE)),
]

# Feeder→master look-through keywords.
_FEEDER_SUFFIXES_RE = re.compile(
    r"\b(feeder|offshore|cayman|ltd|limited|international)\b",
    re.IGNORECASE,
)
_MASTER_KEYWORDS_RE = re.compile(
    r"\b(master|lp|llc)\b",
    re.IGNORECASE,
)


def _validate_cik(cik: str) -> bool:
    """Validate CIK format: 1-10 digits."""
    return bool(_CIK_RE.match(cik))


def _classify_filer_type(name: str) -> str | None:
    """Classify institutional filer type from entity name keywords.

    Logs WARNING if name matches multiple types (ambiguous).
    Returns None if no match.
    """
    matches: list[str] = []
    for filer_type, pattern in _FILER_TYPE_PATTERNS:
        if pattern.search(name):
            matches.append(filer_type)

    if len(matches) == 0:
        return None
    if len(matches) == 1:
        return matches[0]

    # Ambiguous — multiple type matches
    logger.warning(
        "institutional_filer_type_ambiguous",
        filer_name=name[:100],
        matched_types=matches,
        selected=matches[0],
    )
    return matches[0]


class InstitutionalService:
    """13F reverse lookup — institutional investor allocations.

    Async service for filer discovery (EFTS search), delegates to
    ThirteenFService for actual 13F parsing.

    Coverage: managers with US-registered securities (BDCs, REITs, master funds,
    hybrid funds with public sleeve).  Direct private credit deals and purely
    offshore structures without a US master do not appear in 13F holdings.

    Rate limit: shared EDGAR rate limiter (8 req/s).
    """

    def __init__(
        self,
        thirteenf_service: Any,
        db_session_factory: Callable[..., Any],
    ) -> None:
        self._thirteenf = thirteenf_service
        self._db_session_factory = db_session_factory

    # ── Public API (DB-only reads) ───────────────────────────────────

    async def read_investors_in_manager(
        self,
        manager_cik: str,
    ) -> InstitutionalOwnershipResult:
        """DB-only version of find_investors_in_manager. Never calls EDGAR.

        Skips the feeder→master look-through heuristic (which calls edgartools).
        Use this in hot paths (DD report, routes). Data is populated by the
        ``sec_13f_ingestion`` background worker.
        """
        if not _validate_cik(manager_cik):
            return InstitutionalOwnershipResult(
                manager_cik=manager_cik,
                coverage=CoverageType.NO_PUBLIC_SECURITIES,
                investors=[],
                note="Invalid CIK format.",
            )

        try:
            manager_cusips = await self._get_manager_cusips(manager_cik)
            if not manager_cusips:
                return InstitutionalOwnershipResult(
                    manager_cik=manager_cik,
                    coverage=CoverageType.NO_PUBLIC_SECURITIES,
                    investors=[],
                    note="No 13F holdings found in database.",
                )

            allocations = await self._query_institutional_holders(manager_cusips)
            if not allocations:
                return InstitutionalOwnershipResult(
                    manager_cik=manager_cik,
                    coverage=CoverageType.PUBLIC_SECURITIES_NO_HOLDERS,
                    investors=[],
                    note="Manager has public securities but no institutional holders in database.",
                )

            return InstitutionalOwnershipResult(
                manager_cik=manager_cik,
                coverage=CoverageType.FOUND,
                investors=allocations,
            )
        except Exception as exc:
            logger.error(
                "institutional_read_investors_failed",
                manager_cik=manager_cik,
                error=str(exc),
            )
            return InstitutionalOwnershipResult(
                manager_cik=manager_cik,
                coverage=CoverageType.NO_PUBLIC_SECURITIES,
                investors=[],
                note=f"DB lookup failed: {exc}",
            )

    # ── Public API (may call EDGAR — workers only) ────────────────

    async def discover_institutional_filers(
        self,
        *,
        filer_types: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, str]]:
        """Search EFTS for institutional 13F filers by keyword.

        Keywords: "endowment", "pension", "foundation", "sovereign", "insurance".
        Returns list of ``{cik, filer_name, filer_type}`` dicts.
        ``filer_type`` classified from entity name keywords — WARNING on ambiguous.
        Never raises.
        """
        keywords = filer_types or _INSTITUTIONAL_KEYWORDS
        try:
            results = await run_in_sec_thread(
                self._search_efts_filers, keywords, limit,
            )
            return results
        except Exception as exc:
            logger.error(
                "institutional_discover_failed",
                error=str(exc),
            )
            return []

    async def fetch_allocations(
        self,
        filer_cik: str,
        filer_name: str,
        filer_type: str,
        *,
        quarters: int = 4,
        force_refresh: bool = False,
    ) -> list[InstitutionalAllocation]:
        """Fetch 13F holdings for an institutional filer and persist as allocations.

        Delegates to ThirteenFService.fetch_holdings() — no duplication of parsing logic.
        Maps ThirteenFHolding -> InstitutionalAllocation with filer context attached.
        Upserts to sec_institutional_allocations.
        Never raises.
        """
        if not _validate_cik(filer_cik):
            logger.warning("institutional_invalid_cik", cik=filer_cik)
            return []

        try:
            # Delegate 13F parsing to ThirteenFService
            holdings = await self._thirteenf.fetch_holdings(
                filer_cik,
                quarters=quarters,
                force_refresh=force_refresh,
            )
            if not holdings:
                logger.info(
                    "institutional_no_holdings",
                    filer_cik=filer_cik,
                    filer_name=filer_name,
                )
                return []

            # Map to InstitutionalAllocation
            allocations = [
                InstitutionalAllocation(
                    filer_cik=filer_cik,
                    filer_name=filer_name,
                    filer_type=filer_type,
                    report_date=h.report_date,
                    target_cusip=h.cusip,
                    target_issuer=h.issuer_name,
                    market_value=h.market_value,
                    shares=h.shares,
                )
                for h in holdings
            ]

            # Persist
            await self._upsert_allocations(allocations)
            logger.info(
                "institutional_allocations_fetched",
                filer_cik=filer_cik,
                count=len(allocations),
            )
            return allocations
        except Exception as exc:
            logger.error(
                "institutional_fetch_allocations_failed",
                filer_cik=filer_cik,
                error=str(exc),
            )
            return []

    async def find_investors_in_manager(
        self,
        manager_cik: str,
    ) -> InstitutionalOwnershipResult:
        """Reverse lookup: which institutions hold securities of this manager?

        3-way coverage detection:
        - NO_PUBLIC_SECURITIES: manager has no 13F filings on EDGAR
        - PUBLIC_SECURITIES_NO_HOLDERS: manager has filings but no institutional holders
        - FOUND: institutional holders found

        Includes feeder→master look-through heuristic (best-effort).
        Never raises.
        """
        if not _validate_cik(manager_cik):
            logger.warning("institutional_find_invalid_cik", cik=manager_cik)
            return InstitutionalOwnershipResult(
                manager_cik=manager_cik,
                coverage=CoverageType.NO_PUBLIC_SECURITIES,
                investors=[],
                note="Invalid CIK format.",
            )

        try:
            return await self._find_investors_internal(manager_cik)
        except Exception as exc:
            logger.error(
                "institutional_find_investors_failed",
                manager_cik=manager_cik,
                error=str(exc),
            )
            return InstitutionalOwnershipResult(
                manager_cik=manager_cik,
                coverage=CoverageType.NO_PUBLIC_SECURITIES,
                investors=[],
                note=f"Lookup failed: {exc}",
            )

    # ── Internal Logic ─────────────────────────────────────────────

    async def _find_investors_internal(
        self,
        manager_cik: str,
    ) -> InstitutionalOwnershipResult:
        """Core logic for find_investors_in_manager without exception handling."""
        # Step 1: Check if manager has any 13F holdings in DB (proxy for public securities)
        manager_cusips = await self._get_manager_cusips(manager_cik)

        if not manager_cusips:
            # Try feeder→master look-through before giving up
            master_result = await self._try_feeder_master_lookthrough(manager_cik)
            if master_result is not None:
                return master_result

            logger.info(
                "institutional_no_public_securities",
                manager_cik=manager_cik,
                note="No 13F holdings found. Manager may operate via direct deals, "
                     "offshore feeders without US master, or below $100M AUM threshold.",
            )
            return InstitutionalOwnershipResult(
                manager_cik=manager_cik,
                coverage=CoverageType.NO_PUBLIC_SECURITIES,
                investors=[],
                note="No 13F filings found. Manager may operate via direct deals, "
                     "offshore feeders without US master, or below $100M AUM threshold.",
            )

        # Step 2: Query sec_institutional_allocations for CUSIPs held by this manager
        allocations = await self._query_institutional_holders(manager_cusips)

        if not allocations:
            return InstitutionalOwnershipResult(
                manager_cik=manager_cik,
                coverage=CoverageType.PUBLIC_SECURITIES_NO_HOLDERS,
                investors=[],
                note="Manager has public securities but no institutional 13F filers "
                     "hold them in tracked portfolios.",
            )

        return InstitutionalOwnershipResult(
            manager_cik=manager_cik,
            coverage=CoverageType.FOUND,
            investors=allocations,
        )

    async def _get_manager_cusips(self, manager_cik: str) -> set[str]:
        """Get CUSIPs associated with a manager's 13F holdings from DB."""
        try:
            async with self._db_session_factory() as session:
                stmt = (
                    select(Sec13fHoldingModel.cusip)
                    .where(Sec13fHoldingModel.cik == manager_cik)
                    .distinct()
                )
                result = await session.execute(stmt)
                return {row[0] for row in result.all()}
        except Exception as exc:
            logger.error(
                "institutional_get_cusips_failed",
                manager_cik=manager_cik,
                error=str(exc),
            )
            return set()

    async def _query_institutional_holders(
        self,
        target_cusips: set[str],
    ) -> list[InstitutionalAllocation]:
        """Query sec_institutional_allocations for holders of the given CUSIPs."""
        if not target_cusips:
            return []

        try:
            async with self._db_session_factory() as session:
                stmt = (
                    select(SecInstitutionalAllocationModel)
                    .where(
                        SecInstitutionalAllocationModel.target_cusip.in_(target_cusips),
                    )
                    .order_by(
                        SecInstitutionalAllocationModel.report_date.desc(),
                        SecInstitutionalAllocationModel.market_value.desc().nullslast(),
                    )
                )
                result = await session.execute(stmt)
                rows = result.scalars().all()

                return [
                    InstitutionalAllocation(
                        filer_cik=r.filer_cik,
                        filer_name=r.filer_name,
                        filer_type=r.filer_type,
                        report_date=r.report_date.isoformat(),
                        target_cusip=r.target_cusip,
                        target_issuer=r.target_issuer,
                        market_value=r.market_value,
                        shares=r.shares,
                    )
                    for r in rows
                ]
        except Exception as exc:
            logger.error(
                "institutional_query_holders_failed",
                cusip_count=len(target_cusips),
                error=str(exc),
            )
            return []

    async def _try_feeder_master_lookthrough(
        self,
        manager_cik: str,
    ) -> InstitutionalOwnershipResult | None:
        """Best-effort feeder→master look-through heuristic.

        When a manager has no 13F holdings, check if entity name suggests a
        feeder structure (offshore, Cayman, Ltd).  If so, attempt CIK resolution
        on a stripped base name to find a potential US master fund.

        Returns an InstitutionalOwnershipResult if a master is found and has
        holders, or None to fall through to NO_PUBLIC_SECURITIES.
        Non-blocking — never raises.
        """
        try:
            # Fetch the manager's 13F company name from EDGAR
            company_name = await run_in_sec_thread(
                self._get_company_name_sync, manager_cik,
            )
            if not company_name:
                return None

            # Check for feeder-like keywords
            if not _FEEDER_SUFFIXES_RE.search(company_name):
                return None

            # Strip feeder suffixes to derive a base entity name
            base_name = _FEEDER_SUFFIXES_RE.sub(" ", company_name).strip()
            base_name = re.sub(r"\s+", " ", base_name).strip()

            if len(base_name) < 3:
                return None

            logger.info(
                "institutional_feeder_master_attempt",
                manager_cik=manager_cik,
                original_name=company_name,
                base_name=base_name,
            )

            # Resolve CIK for potential master fund
            resolution = resolve_cik(base_name)
            if not resolution.cik or resolution.cik == manager_cik:
                return None

            master_cik = resolution.cik
            logger.info(
                "institutional_feeder_master_resolved",
                manager_cik=manager_cik,
                master_cik=master_cik,
                master_name=resolution.company_name,
                method=resolution.method,
            )

            # Check if the master has CUSIPs
            master_cusips = await self._get_manager_cusips(master_cik)
            if not master_cusips:
                return None

            # Query institutional holders of the master
            allocations = await self._query_institutional_holders(master_cusips)
            if not allocations:
                return InstitutionalOwnershipResult(
                    manager_cik=manager_cik,
                    coverage=CoverageType.PUBLIC_SECURITIES_NO_HOLDERS,
                    investors=[],
                    note=f"Feeder→master look-through: master CIK {master_cik} "
                         f"({resolution.company_name}) has public securities but "
                         f"no institutional holders found.",
                )

            return InstitutionalOwnershipResult(
                manager_cik=manager_cik,
                coverage=CoverageType.FOUND,
                investors=allocations,
                note=f"Feeder→master look-through: holdings via master CIK {master_cik} "
                     f"({resolution.company_name}).",
            )
        except Exception as exc:
            logger.debug(
                "institutional_feeder_master_failed",
                manager_cik=manager_cik,
                error=str(exc),
            )
            return None

    @staticmethod
    def _get_company_name_sync(cik: str) -> str | None:
        """Get company name from edgartools. Sync — runs in SEC thread pool."""
        try:
            from edgar import Company
            company = Company(cik)
            if hasattr(company, "not_found") and company.not_found:
                return None
            return getattr(company, "name", None)
        except Exception:
            return None

    # ── EFTS Filer Discovery (sync, runs in SEC thread pool) ──────

    def _search_efts_filers(
        self,
        keywords: list[str],
        limit: int,
    ) -> list[dict[str, str]]:
        """Search EFTS for 13F filers matching institutional keywords.

        Sync — called via run_in_sec_thread.
        """
        import httpx

        query = " OR ".join(f'"{kw}"' for kw in keywords)

        check_edgar_rate()

        try:
            resp = httpx.get(
                _EFTS_SEARCH_URL,
                params={
                    "q": query,
                    "forms": "13F-HR",
                    "dateRange": "custom",
                    "startdt": "2020-01-01",
                },
                headers={"User-Agent": SEC_USER_AGENT},
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("institutional_efts_search_failed", error=str(exc))
            return []

        hits = data.get("hits", {}).get("hits", [])
        seen_ciks: set[str] = set()
        results: list[dict[str, str]] = []

        for hit in hits:
            if len(results) >= limit:
                break

            source = hit.get("_source", {})
            # EFTS uses "ciks" (list) not "cik" (scalar)
            ciks_list = source.get("ciks") or []
            cik_raw = ciks_list[0] if ciks_list else source.get("entity_id")
            # display_names includes CIK suffix — strip it
            raw_names = source.get("display_names") or []
            raw_name = raw_names[0] if raw_names else ""
            filer_name = re.sub(r"\s*\(CIK \d+\)\s*$", "", raw_name).strip()

            if not cik_raw or not filer_name:
                continue

            cik = str(cik_raw).zfill(10)
            if cik in seen_ciks:
                continue
            seen_ciks.add(cik)

            filer_type = _classify_filer_type(filer_name)

            results.append({
                "cik": cik,
                "filer_name": filer_name.strip(),
                "filer_type": filer_type or "unknown",
            })

        logger.info(
            "institutional_efts_discovery_complete",
            keywords=keywords,
            results=len(results),
        )
        return results

    # ── DB Upsert ──────────────────────────────────────────────────

    async def _upsert_allocations(
        self,
        allocations: list[InstitutionalAllocation],
    ) -> None:
        """Bulk upsert allocations to sec_institutional_allocations. Chunks at 2000."""
        rows = [
            {
                "filer_cik": a.filer_cik,
                "filer_name": a.filer_name,
                "filer_type": a.filer_type,
                "report_date": date.fromisoformat(a.report_date),
                "target_cusip": a.target_cusip,
                "target_issuer": a.target_issuer,
                "market_value": a.market_value,
                "shares": a.shares,
            }
            for a in allocations
        ]

        async with self._db_session_factory() as session, session.begin():
            for i in range(0, len(rows), _CHUNK_SIZE):
                chunk = rows[i : i + _CHUNK_SIZE]
                stmt = pg_insert(SecInstitutionalAllocationModel).values(chunk)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_sec_inst_alloc_filer_date_cusip",
                    set_={
                        "filer_name": stmt.excluded.filer_name,
                        "filer_type": stmt.excluded.filer_type,
                        "target_issuer": stmt.excluded.target_issuer,
                        "market_value": stmt.excluded.market_value,
                        "shares": stmt.excluded.shares,
                    },
                )
                await session.execute(stmt)
