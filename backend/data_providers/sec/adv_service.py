"""ADV Service — Form ADV data via hybrid IAPD search + bulk CSV ingestion.

The IAPD API only exposes a search endpoint (basic identification).
Detailed data (AUM, fees, private funds, compliance) comes from monthly
bulk CSV downloads published by SEC FOIA. Team bios come from Part 2A
PDF brochures (OCR via Mistral — deferred to M2).

Async service. Instantiate ONCE in FastAPI lifespan().
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import datetime, timezone
from typing import Any, Callable

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.shared.models import SecManager, SecManagerFund
from data_providers.sec.models import AdvFund, AdvManager, AdvTeamMember
from data_providers.sec.shared import (
    SEC_USER_AGENT,
    check_iapd_rate,
    run_in_sec_thread,
)

logger = structlog.get_logger()

_CRD_RE = re.compile(r"^\d{1,10}$")

# IAPD search API — única rota pública documentada
IAPD_SEARCH_URL = "https://api.adviserinfo.sec.gov/search/firm"

# Bulk ZIP — known URLs with fallback (SEC filename pattern is not deterministic).
# DD in ia{MM}{DD}{YY}.zip varies by month — no reliable formula.
# We try known recent URLs in order; callers can also pass a local csv_path.
_ADV_FOIA_BASE = (
    "https://www.sec.gov/files/investment/data/"
    "information-about-registered-investment-advisers-"
    "exempt-reporting-advisers"
)

# Other path variant seen on SEC site
_ADV_FOIA_BASE_ALT = (
    "https://www.sec.gov/files/investment/data/other/"
    "information-about-registered-investment-advisers-"
    "exempt-reporting-advisers"
)


def _validate_crd(crd: str) -> bool:
    """Validate CRD number format: 1-10 digits."""
    return bool(_CRD_RE.match(crd))


def _parse_iapd_hit(hit: dict[str, Any]) -> AdvManager | None:
    """Parse a single IAPD search result into an AdvManager.

    IAPD search returns only basic identification — no AUM, fees, or funds.
    """
    source = hit.get("_source", hit)

    crd = str(source.get("firm_source_id", "") or "").strip()
    if not _validate_crd(crd):
        return None

    firm_name = (source.get("firm_name") or "").strip()
    if not firm_name:
        return None

    sec_number = source.get("firm_ia_sec_number")
    scope = source.get("firm_ia_scope")  # ACTIVE / INACTIVE

    # Address comes as a JSON string in some responses
    state: str | None = None
    country: str | None = None
    address_raw = source.get("firm_ia_address_details")
    if address_raw:
        try:
            import json as _json

            if isinstance(address_raw, str):
                addr = _json.loads(address_raw)
            else:
                addr = address_raw
            state = addr.get("state")
            country = addr.get("country")
        except Exception:
            pass

    return AdvManager(
        crd_number=crd,
        cik=None,  # IAPD does not return CIK
        firm_name=firm_name,
        sec_number=sec_number,
        registration_status=scope,
        aum_total=None,
        aum_discretionary=None,
        aum_non_discretionary=None,
        total_accounts=None,
        fee_types=None,
        client_types=None,
        state=state,
        country=country,
        website=None,
        compliance_disclosures=None,
        last_adv_filed_at=None,
        data_fetched_at=datetime.now(timezone.utc).isoformat(),
    )


def _parse_int(val: Any) -> int | None:
    """Parse integer from CSV value, returning None on failure."""
    if val is None or val == "":
        return None
    try:
        return int(float(str(val).replace(",", "").strip()))
    except (ValueError, TypeError):
        return None


def _parse_date(val: Any) -> str | None:
    """Parse date string from CSV, returning ISO format or None."""
    if not val or not str(val).strip():
        return None
    raw = str(val).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


class AdvService:
    """Form ADV data service — hybrid IAPD search + bulk CSV + PDF reports.

    The IAPD API only exposes a search endpoint (basic identification).
    Detailed data (AUM, fees, private funds, compliance) comes from monthly
    bulk CSV downloads published by SEC FOIA. Team bios come from Part 2A
    PDF brochures (OCR via Mistral).

    Async service. Lifecycle: Instantiate ONCE in FastAPI lifespan().
    """

    def __init__(
        self,
        db_session_factory: Callable[..., Any],
    ) -> None:
        self._db_session_factory = db_session_factory

    # ── IAPD Search ─────────────────────────────────────────────────

    async def search_managers(
        self,
        query: str,
        *,
        limit: int = 25,
    ) -> list[AdvManager]:
        """Search IAPD by firm name. Returns basic identification only.

        Does NOT return AUM or fees — those require bulk CSV ingestion.
        Rate limited at 2 req/s. Never raises.
        """
        if not query or not query.strip():
            return []

        try:
            results = await run_in_sec_thread(
                self._search_managers_sync,
                query.strip(),
                limit,
            )
            return results
        except Exception as exc:
            logger.error(
                "adv_search_failed",
                query=query,
                error=str(exc),
            )
            return []

    def _search_managers_sync(
        self,
        query: str,
        limit: int,
    ) -> list[AdvManager]:
        """Synchronous IAPD search — runs in SEC thread pool."""
        import httpx

        check_iapd_rate()

        resp = httpx.get(
            IAPD_SEARCH_URL,
            params={
                "query": query,
                "hl": "true",
                "nrows": str(min(limit, 100)),
                "start": "0",
                "wt": "json",
            },
            headers={"User-Agent": SEC_USER_AGENT},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()

        hits = data.get("hits", {}).get("hits", [])
        managers: list[AdvManager] = []
        for hit in hits:
            parsed = _parse_iapd_hit(hit)
            if parsed:
                managers.append(parsed)

        logger.info(
            "adv_search_complete",
            query=query,
            results=len(managers),
        )
        return managers

    # ── Bulk CSV Ingestion ──────────────────────────────────────────

    async def ingest_bulk_adv(
        self,
        csv_path: str | None = None,
    ) -> int:
        """Ingest Form ADV data from monthly SEC FOIA bulk CSV.

        If csv_path points to a ZIP, extracts the CSV inside.
        If csv_path is None, downloads the latest from SEC FOIA.
        Upserts to sec_managers and sec_manager_funds.
        Returns count of managers upserted. Never raises.
        """
        try:
            csv_content = await self._load_csv_content(csv_path)
            if csv_content is None:
                return 0

            count = await self._upsert_from_csv(csv_content)
            logger.info("adv_bulk_ingest_complete", managers_upserted=count)
            return count
        except Exception as exc:
            logger.error(
                "adv_bulk_ingest_failed",
                csv_path=csv_path,
                error=str(exc),
            )
            return 0

    async def _load_csv_content(self, csv_path: str | None) -> str | None:
        """Load CSV content from file path or download from SEC FOIA.

        Returns raw CSV text or None on failure.
        """
        if csv_path:
            return await run_in_sec_thread(self._read_csv_file, csv_path)

        # Download from SEC FOIA
        logger.info("adv_bulk_download_start")
        try:
            content = await run_in_sec_thread(self._download_foia_csv)
            return content
        except Exception as exc:
            logger.error("adv_foia_download_failed", error=str(exc))
            return None

    @staticmethod
    def _read_csv_file(path: str) -> str:
        """Read CSV from local file, extracting from ZIP if needed."""
        if path.lower().endswith(".zip"):
            with zipfile.ZipFile(path, "r") as zf:
                csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if not csv_names:
                    raise ValueError(f"No CSV file found in ZIP: {path}")
                # Use the largest CSV (main ADV data vs Schedule D)
                csv_names.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
                with zf.open(csv_names[0]) as f:
                    return f.read().decode("utf-8", errors="replace")

        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()

    @staticmethod
    def _download_foia_csv() -> str:
        """Download latest Form ADV bulk ZIP from SEC FOIA.

        The filename pattern ia{MM}{DD}{YY}.zip has a non-deterministic DD
        that varies by month. We generate candidate URLs for the current
        month and 3 prior months using common DD values (01, 02, 03), trying
        both known base path variants on sec.gov.

        Falls back to a hardcoded list of known-good URLs if generated
        candidates all 404.
        """
        import httpx

        now = datetime.now(timezone.utc)

        # Generate candidate URLs: current month + 3 prior, DD in {01,02,03}
        candidate_urls: list[str] = []
        for delta in range(4):
            m = now.month - delta
            y = now.year
            while m <= 0:
                m += 12
                y -= 1
            mm = str(m).zfill(2)
            yy = str(y)[-2:]
            for dd in ("01", "02", "03"):
                fname = f"ia{mm}{dd}{yy}.zip"
                candidate_urls.append(f"{_ADV_FOIA_BASE}/{fname}")
                candidate_urls.append(f"{_ADV_FOIA_BASE_ALT}/{fname}")

        # Hardcoded known-good URLs as final fallback
        candidate_urls.extend([
            f"{_ADV_FOIA_BASE_ALT}/ia020226.zip",
            f"{_ADV_FOIA_BASE}/ia010226.zip",
            f"{_ADV_FOIA_BASE}/ia120125.zip",
        ])

        last_error: Exception | None = None
        for zip_url in candidate_urls:
            try:
                logger.info("adv_foia_trying_url", url=zip_url)
                resp = httpx.get(
                    zip_url,
                    headers={"User-Agent": SEC_USER_AGENT},
                    timeout=120.0,
                    follow_redirects=True,
                )
                if resp.status_code == 404:
                    logger.debug("adv_foia_url_not_found", url=zip_url)
                    continue
                resp.raise_for_status()

                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    csv_names = [
                        n for n in zf.namelist() if n.lower().endswith(".csv")
                    ]
                    if not csv_names:
                        raise ValueError("No CSV in downloaded FOIA ZIP")
                    csv_names.sort(
                        key=lambda n: zf.getinfo(n).file_size, reverse=True,
                    )
                    with zf.open(csv_names[0]) as f:
                        content = f.read().decode("utf-8", errors="replace")
                        logger.info(
                            "adv_foia_downloaded",
                            url=zip_url,
                            csv_file=csv_names[0],
                            size_kb=len(content) // 1024,
                        )
                        return content

            except Exception as exc:
                last_error = exc
                logger.warning(
                    "adv_foia_url_failed", url=zip_url, error=str(exc),
                )
                continue

        raise ValueError(
            f"No valid ADV ZIP found. Tried {len(candidate_urls)} URLs. "
            f"Last error: {last_error}"
        )

    async def _upsert_from_csv(self, csv_content: str) -> int:
        """Parse CSV and upsert managers + funds to database.

        Form ADV CSV uses question-number columns:
        - Q5F2A = discretionary AUM
        - Q5F2C = total AUM
        - Q5F2B = non-discretionary AUM
        - TtlEmp = total employees
        """
        reader = csv.DictReader(io.StringIO(csv_content))

        managers: list[dict[str, Any]] = []
        for row in reader:
            crd = str(row.get("CRD Number", "") or row.get("Organization CRD#", "") or "").strip()
            if not _validate_crd(crd):
                continue

            firm_name = (
                row.get("Primary Business Name", "") or row.get("Legal Name", "") or ""
            ).strip()
            if not firm_name:
                continue

            aum_disc = _parse_int(row.get("Q5F2A"))
            aum_non_disc = _parse_int(row.get("Q5F2B"))
            aum_total = _parse_int(row.get("Q5F2C"))
            if aum_total is None and aum_disc is not None:
                aum_total = (aum_disc or 0) + (aum_non_disc or 0)

            managers.append(
                {
                    "crd_number": crd,
                    "firm_name": firm_name,
                    "sec_number": (row.get("SEC#") or row.get("SEC Number") or "").strip() or None,
                    "registration_status": (
                        row.get("Status") or row.get("Registration Status") or ""
                    ).strip()
                    or None,
                    "aum_total": aum_total,
                    "aum_discretionary": aum_disc,
                    "aum_non_discretionary": aum_non_disc,
                    "total_accounts": _parse_int(row.get("Q5F2(f)")),
                    "state": (row.get("Main Office State") or row.get("State") or "").strip()
                    or None,
                    "country": (row.get("Main Office Country") or row.get("Country") or "").strip()
                    or None,
                    "website": (row.get("Website") or "").strip() or None,
                    "compliance_disclosures": _parse_int(row.get("Q11")),
                    "last_adv_filed_at": _parse_date(row.get("Most Recent ADV Filing Date")),
                    "data_fetched_at": datetime.now(timezone.utc),
                }
            )

        if not managers:
            logger.warning("adv_bulk_csv_empty")
            return 0

        # Upsert in chunks of 2000
        chunk_size = 2000
        upserted = 0
        async with self._db_session_factory() as session, session.begin():
            for i in range(0, len(managers), chunk_size):
                chunk = managers[i : i + chunk_size]
                stmt = pg_insert(SecManager).values(chunk)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["crd_number"],
                    set_={
                        "firm_name": stmt.excluded.firm_name,
                        "sec_number": stmt.excluded.sec_number,
                        "registration_status": stmt.excluded.registration_status,
                        "aum_total": stmt.excluded.aum_total,
                        "aum_discretionary": stmt.excluded.aum_discretionary,
                        "aum_non_discretionary": stmt.excluded.aum_non_discretionary,
                        "total_accounts": stmt.excluded.total_accounts,
                        "state": stmt.excluded.state,
                        "country": stmt.excluded.country,
                        "website": stmt.excluded.website,
                        "compliance_disclosures": stmt.excluded.compliance_disclosures,
                        "last_adv_filed_at": stmt.excluded.last_adv_filed_at,
                        "data_fetched_at": stmt.excluded.data_fetched_at,
                    },
                )
                await session.execute(stmt)
                upserted += len(chunk)

        return upserted

    # ── DB Read (Stale-but-serve) ───────────────────────────────────

    async def fetch_manager(
        self,
        crd_number: str,
        *,
        force_refresh: bool = False,  # noqa: ARG002 — reserved for M2
        staleness_ttl_days: int = 7,  # noqa: ARG002 — reserved for M2
    ) -> AdvManager | None:
        """Return manager from DB. Does NOT call IAPD API.

        Data populated by ingest_bulk_adv() (monthly worker).
        Returns None if manager not in DB. Never raises.
        """
        if not _validate_crd(crd_number):
            logger.warning("adv_fetch_invalid_crd", crd=crd_number)
            return None

        try:
            async with self._db_session_factory() as session:
                result = await session.execute(
                    select(SecManager).where(SecManager.crd_number == crd_number),
                )
                row = result.scalar_one_or_none()
                if row is None:
                    return None

                return AdvManager(
                    crd_number=row.crd_number,
                    cik=row.cik,
                    firm_name=row.firm_name,
                    sec_number=row.sec_number,
                    registration_status=row.registration_status,
                    aum_total=row.aum_total,
                    aum_discretionary=row.aum_discretionary,
                    aum_non_discretionary=row.aum_non_discretionary,
                    total_accounts=row.total_accounts,
                    fee_types=row.fee_types,
                    client_types=row.client_types,
                    state=row.state,
                    country=row.country,
                    website=row.website,
                    compliance_disclosures=row.compliance_disclosures,
                    last_adv_filed_at=(
                        row.last_adv_filed_at.isoformat() if row.last_adv_filed_at else None
                    ),
                    data_fetched_at=(
                        row.data_fetched_at.isoformat() if row.data_fetched_at else None
                    ),
                )
        except Exception as exc:
            logger.error(
                "adv_fetch_manager_failed",
                crd=crd_number,
                error=str(exc),
            )
            return None

    async def fetch_manager_funds(
        self,
        crd_number: str,
    ) -> list[AdvFund]:
        """Return Schedule D funds from DB (populated by bulk ingestion).

        Never raises.
        """
        if not _validate_crd(crd_number):
            return []

        try:
            async with self._db_session_factory() as session:
                result = await session.execute(
                    select(SecManagerFund).where(SecManagerFund.crd_number == crd_number),
                )
                rows = result.scalars().all()
                return [
                    AdvFund(
                        crd_number=r.crd_number,
                        fund_name=r.fund_name,
                        fund_id=r.fund_id,
                        gross_asset_value=r.gross_asset_value,
                        fund_type=r.fund_type,
                        is_fund_of_funds=r.is_fund_of_funds,
                        investor_count=r.investor_count,
                    )
                    for r in rows
                ]
        except Exception as exc:
            logger.error(
                "adv_fetch_funds_failed",
                crd=crd_number,
                error=str(exc),
            )
            return []

    async def fetch_manager_team(
        self,
        crd_number: str,
        *,
        force_refresh: bool = False,  # noqa: ARG002 — reserved for M2
    ) -> list[AdvTeamMember]:
        """Fetch team from DB. Stub in M1 — returns empty list.

        # TODO: Part 2A PDF OCR — download brochure from
        # reports.adviserinfo.sec.gov and extract via Mistral OCR.
        # Requires Mistral pipeline integration (M2 scope).
        """
        if not _validate_crd(crd_number):
            return []

        logger.info(
            "adv_fetch_team_stub",
            crd=crd_number,
            note="Team extraction requires Part 2A PDF OCR (M2). "
            "Callers expecting team bios will receive empty list.",
        )
        return []
