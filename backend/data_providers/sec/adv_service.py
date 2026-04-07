"""ADV Service — Form ADV data via hybrid IAPD search + bulk CSV ingestion.

The IAPD API only exposes a search endpoint (basic identification).
Detailed data (AUM, fees, private funds, compliance) comes from monthly
bulk CSV downloads published by SEC FOIA. Team bios come from Part 2A
PDF brochures (text extraction via PyMuPDF — SEC requires text-searchable
PDFs for IARD submission since 2010, so OCR is unnecessary).

Async service. Instantiate ONCE in FastAPI lifespan().
"""

from __future__ import annotations

import asyncio
import csv
import io
import re
import zipfile
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.shared.models import SecManager, SecManagerBrochureText, SecManagerFund, SecManagerTeam
from data_providers.sec.models import AdvBrochureSection, AdvFund, AdvManager, AdvTeamMember
from data_providers.sec.shared import (
    SEC_USER_AGENT,
    check_iapd_rate,
    run_in_sec_thread,
)

logger = structlog.get_logger()

_CRD_RE = re.compile(r"^\d{1,10}$")

# IAPD search API — única rota pública documentada
IAPD_SEARCH_URL = "https://api.adviserinfo.sec.gov/search/firm"

# ── Part 2A brochure download ────────────────────────────────────
# reports.adviserinfo.sec.gov serves PDF brochures by CRD number.
_ADV_BROCHURE_URL = "https://reports.adviserinfo.sec.gov/reports/ADV/{crd}/R_0{crd}.pdf"

# ── Brochure section classification ─────────────────────────────
# Map section headings (from ADV Part 2A standard Items) to stable keys.
_SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("advisory_business", re.compile(r"item\s*4.*advisory\s*business", re.IGNORECASE)),
    ("fees_compensation", re.compile(r"item\s*5.*fees\s*and\s*compensation", re.IGNORECASE)),
    ("performance_fees", re.compile(r"item\s*6.*performance.based\s*fees", re.IGNORECASE)),
    ("client_types", re.compile(r"item\s*7.*types\s*of\s*clients", re.IGNORECASE)),
    ("methods_of_analysis", re.compile(r"item\s*8.*methods\s*of\s*analysis", re.IGNORECASE)),
    ("disciplinary_information", re.compile(r"item\s*9.*disciplinary\s*info", re.IGNORECASE)),
    ("other_financial_activities", re.compile(r"item\s*10.*other\s*financial", re.IGNORECASE)),
    ("code_of_ethics", re.compile(r"item\s*11.*code\s*of\s*ethics", re.IGNORECASE)),
    ("brokerage_practices", re.compile(r"item\s*12.*brokerage\s*practices", re.IGNORECASE)),
    ("review_of_accounts", re.compile(r"item\s*13.*review\s*of\s*accounts", re.IGNORECASE)),
    ("client_referrals", re.compile(r"item\s*14.*client\s*referrals", re.IGNORECASE)),
    ("custody", re.compile(r"item\s*15.*custody", re.IGNORECASE)),
    ("investment_discretion", re.compile(r"item\s*16.*investment\s*discretion", re.IGNORECASE)),
    ("voting_client_securities", re.compile(r"item\s*17.*voting\s*client\s*securities", re.IGNORECASE)),
    ("financial_information", re.compile(r"item\s*18.*financial\s*info", re.IGNORECASE)),
    # Common non-numbered sections
    ("investment_philosophy", re.compile(r"investment\s*(philosophy|approach|strategy)", re.IGNORECASE)),
    ("risk_management", re.compile(r"risk\s*management", re.IGNORECASE)),
    ("esg_integration", re.compile(r"\besg\b.*integration|responsible\s*invest", re.IGNORECASE)),
]

# Team extraction patterns (Part 2B brochure supplement)
_TEAM_PERSON_RE = re.compile(
    r"^(?:##?\s*)?([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){1,3})"
    r"(?:[ \t]*,[ \t]*|[ \t]*\n[ \t]*)"
    r"((?:CFA|CFP|CAIA|CPA|MBA|PhD|JD|CIO|CEO|Managing\s+Director|"
    r"Portfolio\s+Manager|Partner|Principal|Analyst|Director|"
    r"Senior\s+Vice\s+President|Vice\s+President|Chief)[^\n]*)",
    re.MULTILINE,
)

_CERTIFICATION_RE = re.compile(r"\b(CFA|CFP|CAIA|CPA|FRM|CIPM)\b")
_EXPERIENCE_RE = re.compile(r"(\d{1,2})\s*(?:\+\s*)?years?\s*(?:of\s*)?(?:experience|in\s*the\s*industry)", re.IGNORECASE)

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
        data_fetched_at=datetime.now(UTC).isoformat(),
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
    PDF brochures (text extraction via PyMuPDF).

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

        # Wrap the IAPD search through the SEC EDGAR provider gate.
        # The circuit opens after five consecutive failures and stays
        # open for 30 s before probing — guards against IAPD edge
        # outages spreading into the user-facing search path.
        from app.core.runtime.gates import get_sec_edgar_gate
        from app.core.runtime.provider_gate import ProviderGateError

        gate = get_sec_edgar_gate()
        try:
            return await gate.call(
                f"iapd_search:{query.strip().lower()}:{limit}",
                lambda: run_in_sec_thread(
                    self._search_managers_sync, query.strip(), limit,
                ),
            )
        except ProviderGateError as exc:
            logger.warning(
                "adv_search_gate_blocked",
                query=query,
                error=str(exc),
            )
            return []
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

        # Download from SEC FOIA via the bulk SEC EDGAR gate. The
        # bulk gate has a 5 minute wall (the FOIA ZIP is multi-MB and
        # SEC's edge serves it slowly) and a more lenient circuit
        # tuned for daily ingestion cadence. Distinct from the
        # interactive gate so a slow bulk download cannot poison the
        # circuit shared with brochure / IAPD search call sites.
        from app.core.runtime.gates import get_sec_edgar_bulk_gate
        from app.core.runtime.provider_gate import ProviderGateError

        logger.info("adv_bulk_download_start")
        gate = get_sec_edgar_bulk_gate()
        try:
            content = await gate.call(
                "adv_foia_bulk_csv",
                lambda: run_in_sec_thread(self._download_foia_csv),
            )
            return content
        except ProviderGateError as exc:
            logger.warning("adv_foia_gate_blocked", error=str(exc))
            return None
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

        now = datetime.now(UTC)

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
            f"Last error: {last_error}",
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
                        row.get("Status") or row.get("Registration Status") or row.get("Firm Type") or ""
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
                    "private_fund_count": _parse_int(row.get("Count of Private Funds - 7B(1)")),
                    "hedge_fund_count": _parse_int(row.get("Total number of Hedge funds")),
                    "pe_fund_count": _parse_int(row.get("Total number of PE funds")),
                    "vc_fund_count": _parse_int(row.get("Total number of VC funds")),
                    "real_estate_fund_count": _parse_int(row.get("Total number of Real Estate funds")),
                    "securitized_fund_count": _parse_int(row.get("Total number of Securitized funds")),
                    "liquidity_fund_count": _parse_int(row.get("Total number of Liquidity funds")),
                    "other_fund_count": _parse_int(row.get("Total number of Other funds")),
                    "total_private_fund_assets": _parse_int(row.get("Total Gross Assets of Private Funds")),
                    "last_adv_filed_at": _parse_date(row.get("Most Recent ADV Filing Date")),
                    "data_fetched_at": datetime.now(UTC),
                },
            )

        if not managers:
            logger.warning("adv_bulk_csv_empty")
            return 0

        # 23 columns × chunk_size must stay under asyncpg's 32767 param limit.
        # Commit per chunk to avoid long-lived transactions (Timescale Cloud timeout).
        chunk_size = 1000
        upserted = 0
        for i in range(0, len(managers), chunk_size):
            chunk = managers[i : i + chunk_size]
            async with self._db_session_factory() as session, session.begin():
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
                        "private_fund_count": stmt.excluded.private_fund_count,
                        "hedge_fund_count": stmt.excluded.hedge_fund_count,
                        "pe_fund_count": stmt.excluded.pe_fund_count,
                        "vc_fund_count": stmt.excluded.vc_fund_count,
                        "real_estate_fund_count": stmt.excluded.real_estate_fund_count,
                        "securitized_fund_count": stmt.excluded.securitized_fund_count,
                        "liquidity_fund_count": stmt.excluded.liquidity_fund_count,
                        "other_fund_count": stmt.excluded.other_fund_count,
                        "total_private_fund_assets": stmt.excluded.total_private_fund_assets,
                        "last_adv_filed_at": stmt.excluded.last_adv_filed_at,
                        "data_fetched_at": stmt.excluded.data_fetched_at,
                    },
                )
                await session.execute(stmt)
                upserted += len(chunk)
            logger.info("adv_bulk_chunk_upserted", chunk=i // chunk_size + 1, upserted=upserted)

        return upserted

    # ── IAPD XML Enrichment ──────────────────────────────────────────

    async def ingest_iapd_xml(self, xml_path: str) -> int:
        """Enrich sec_managers with Form ADV Part 1A data from IAPD XML feed.

        Parses the XML, then batch UPDATEs existing sec_managers rows.
        Only updates rows where crd_number already exists (no INSERT).
        Returns count of managers updated.
        """
        import json

        from data_providers.sec.iapd_xml_parser import parse_iapd_xml

        def _to_date(val: str | None) -> date | None:
            if not val:
                return None
            try:
                return date.fromisoformat(val)
            except (ValueError, TypeError):
                return None

        records = await run_in_sec_thread(parse_iapd_xml, xml_path)
        if not records:
            logger.warning("iapd_xml_empty", xml_path=xml_path)
            return 0

        logger.info("iapd_xml_parsed", xml_path=xml_path, firms=len(records))

        _UPDATE_SQL = text("""
            UPDATE sec_managers SET
                aum_total = COALESCE(:aum_total, aum_total),
                aum_discretionary = COALESCE(:aum_discretionary, aum_discretionary),
                aum_non_discretionary = COALESCE(:aum_non_discretionary, aum_non_discretionary),
                total_accounts = COALESCE(:total_accounts, total_accounts),
                fee_types = CASE WHEN CAST(:fee_types AS jsonb) != '[]' THEN CAST(:fee_types AS jsonb) ELSE fee_types END,
                client_types = CASE WHEN CAST(:client_types AS jsonb) != '{}' THEN CAST(:client_types AS jsonb) ELSE client_types END,
                website = COALESCE(:website, website),
                compliance_disclosures = COALESCE(:compliance_disclosures, compliance_disclosures),
                last_adv_filed_at = COALESCE(:last_adv_filed_at, last_adv_filed_at)
            WHERE crd_number = :crd_number
        """)

        chunk_size = 500
        updated = 0
        for i in range(0, len(records), chunk_size):
            chunk = records[i : i + chunk_size]
            async with self._db_session_factory() as session, session.begin():
                for rec in chunk:
                    result = await session.execute(
                        _UPDATE_SQL,
                        {
                            "crd_number": rec["crd_number"],
                            "aum_total": rec.get("aum_total"),
                            "aum_discretionary": rec.get("aum_discretionary"),
                            "aum_non_discretionary": rec.get("aum_non_discretionary"),
                            "total_accounts": rec.get("total_accounts"),
                            "fee_types": json.dumps(rec.get("fee_types", [])),
                            "client_types": json.dumps(rec.get("client_types", {})),
                            "website": rec.get("website"),
                            "compliance_disclosures": rec.get("compliance_disclosures"),
                            "last_adv_filed_at": _to_date(rec.get("last_adv_filed_at")),
                        },
                    )
                    updated += result.rowcount
            logger.info(
                "iapd_xml_chunk_updated",
                chunk=i // chunk_size + 1,
                updated=updated,
            )

        logger.info("iapd_xml_enrichment_complete", total_updated=updated)
        return updated

    async def build_entity_links(self) -> int:
        """Build sec_entity_links by matching 13F parent CIKs to Registered advisers.

        For each CIK in sec_13f_holdings, find Registered advisers whose
        firm_name shares a significant prefix with the 13F filer's name.
        E.g. "BlackRock, Inc." (13F filer) → "BLACKROCK FUND ADVISORS" (RIA).

        Returns count of links created.
        """
        async with self._db_session_factory() as session, session.begin():
            # Get all 13F filer CIKs and their names from sec_managers
            result = await session.execute(text("""
                SELECT DISTINCT h.cik, m.firm_name
                FROM (SELECT DISTINCT cik FROM sec_13f_holdings) h
                JOIN sec_managers m ON m.cik = h.cik
            """))
            filer_map = {row[0]: row[1] for row in result.fetchall()}

            links_created = 0
            for filer_cik, filer_name in filer_map.items():
                # Extract name prefix for matching (first significant word)
                # "BlackRock, Inc." → "BlackRock"
                # "FRANKLIN RESOURCES INC" → "FRANKLIN"
                prefix = filer_name.split(",")[0].split(" ")[0].strip()
                if len(prefix) < 3:
                    continue

                # Find Registered advisers with matching name prefix
                ria_result = await session.execute(text("""
                    SELECT crd_number, firm_name, cik
                    FROM sec_managers
                    WHERE registration_status = 'Registered'
                    AND firm_name ILIKE :pattern
                    ORDER BY aum_total DESC NULLS LAST
                """), {"pattern": f"{prefix}%"})

                for ria in ria_result.fetchall():
                    stmt = text("""
                        INSERT INTO sec_entity_links
                            (manager_crd, related_cik, relationship, related_name, source, confidence)
                        VALUES (:crd, :cik, 'parent_13f', :name, 'name_match', :conf)
                        ON CONFLICT (manager_crd, related_cik, relationship) DO NOTHING
                    """)
                    await session.execute(stmt, {
                        "crd": ria[0],
                        "cik": filer_cik,
                        "name": filer_name,
                        "conf": 0.8,
                    })
                    links_created += 1

            logger.info("entity_links_built", links_created=links_created)
            return links_created

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
        force_refresh: bool = False,
    ) -> list[AdvTeamMember]:
        """Fetch team from DB. If empty and force_refresh, extract from Part 2A PDF.

        Stale-but-serve: returns DB data immediately if available.
        PyMuPDF text extraction only triggered by force_refresh=True
        when DB is empty.
        """
        if not _validate_crd(crd_number):
            return []

        # Read from DB first (stale-but-serve)
        try:
            async with self._db_session_factory() as session:
                result = await session.execute(
                    select(SecManagerTeam).where(SecManagerTeam.crd_number == crd_number),
                )
                rows = result.scalars().all()
                if rows and not force_refresh:
                    return [
                        AdvTeamMember(
                            crd_number=r.crd_number,
                            person_name=r.person_name,
                            title=r.title,
                            role=r.role,
                            education=r.education,
                            certifications=r.certifications or [],
                            years_experience=r.years_experience,
                            bio_summary=r.bio_summary,
                        )
                        for r in rows
                    ]
        except Exception as exc:
            logger.error("adv_fetch_team_db_failed", crd=crd_number, error=str(exc))

        if not force_refresh:
            return []

        # Extract from Part 2A PDF via PyMuPDF
        try:
            brochure_text = await self._download_and_extract_brochure(crd_number)
            if not brochure_text:
                logger.warning("adv_brochure_empty", crd=crd_number)
                return []

            # Parse team members and brochure sections
            team_members = _parse_team_from_brochure(crd_number, brochure_text)
            sections = _classify_brochure_sections(crd_number, brochure_text)

            # Persist both
            await self._upsert_team(crd_number, team_members)
            if sections:
                await self._upsert_brochure_sections(crd_number, sections)

            return team_members

        except Exception as exc:
            logger.error("adv_fetch_team_extract_failed", crd=crd_number, error=str(exc))
            return []

    async def extract_brochure(
        self,
        crd_number: str,
        *,
        force_refresh: bool = False,
    ) -> list[AdvBrochureSection]:
        """Extract and store brochure text sections for full-text search.

        Reads cached sections from ``sec_manager_brochure_text`` first;
        on miss (or ``force_refresh=True``) downloads the Part 2A PDF
        and runs PyMuPDF text extraction. SEC mandates that all ADV
        Part 2A brochures be text-searchable PDFs (since 2010), so
        OCR is never required and never invoked from this path.
        """
        if not _validate_crd(crd_number):
            return []

        # Check DB first
        if not force_refresh:
            try:
                async with self._db_session_factory() as session:
                    result = await session.execute(
                        select(SecManagerBrochureText).where(
                            SecManagerBrochureText.crd_number == crd_number,
                        ),
                    )
                    rows = result.scalars().all()
                    if rows:
                        return [
                            AdvBrochureSection(
                                crd_number=r.crd_number,
                                section=r.section,
                                content=r.content,
                                filing_date=r.filing_date.isoformat(),
                            )
                            for r in rows
                        ]
            except Exception as exc:
                logger.error("adv_brochure_db_read_failed", crd=crd_number, error=str(exc))

        # PyMuPDF text extraction (DB miss path)
        try:
            brochure_text = await self._download_and_extract_brochure(crd_number)
            if not brochure_text:
                return []

            sections = _classify_brochure_sections(crd_number, brochure_text)
            if sections:
                await self._upsert_brochure_sections(crd_number, sections)

            # Also extract team if not done yet
            team = _parse_team_from_brochure(crd_number, brochure_text)
            if team:
                await self._upsert_team(crd_number, team)

            return sections

        except Exception as exc:
            logger.error("adv_brochure_extract_failed", crd=crd_number, error=str(exc))
            return []

    async def search_brochure_text(
        self,
        query: str,
        *,
        limit: int = 25,
    ) -> list[AdvBrochureSection]:
        """Full-text search across all manager brochure sections.

        Uses PostgreSQL tsvector GIN index. Returns matching sections
        ranked by ts_rank. Example: "ESG integration", "private credit".
        """
        if not query or not query.strip():
            return []

        try:
            async with self._db_session_factory() as session:
                # Use plainto_tsquery for safe user input (no special syntax needed)
                stmt = text("""
                    SELECT crd_number, section, content, filing_date
                    FROM sec_manager_brochure_text
                    WHERE to_tsvector('english', content) @@ plainto_tsquery('english', :query)
                    ORDER BY ts_rank(to_tsvector('english', content), plainto_tsquery('english', :query)) DESC
                    LIMIT :limit
                """)
                result = await session.execute(stmt, {"query": query.strip(), "limit": limit})
                return [
                    AdvBrochureSection(
                        crd_number=row.crd_number,
                        section=row.section,
                        content=row.content,
                        filing_date=row.filing_date.isoformat(),
                    )
                    for row in result.fetchall()
                ]
        except Exception as exc:
            logger.error("adv_brochure_search_failed", query=query, error=str(exc))
            return []

    # ── Part 2A Brochure Text Extraction ────────────────────────

    async def _download_and_extract_brochure(self, crd_number: str) -> str:
        """Get brochure PDF (StorageClient first, then EDGAR) and extract text.

        Storage hierarchy:
          1. StorageClient (R2 prod / local dev) — pre-populated by brochure_download worker
          2. Legacy local path (.data/lake/brochures/{crd}.pdf) — seed script
          3. Download from IAPD → save to StorageClient → extract

        SEC requires all Part 2A brochures to be text-searchable PDF
        (mandatory since 2010). No OCR needed — PyMuPDF text extraction.
        """
        from app.services.storage_client import get_storage_client

        storage = get_storage_client()
        storage_key = f"gold/_global/sec_brochures/{crd_number}.pdf"

        # 1. Try StorageClient (worker-populated)
        try:
            if await storage.exists(storage_key):
                pdf_bytes = await storage.read(storage_key)
                if len(pdf_bytes) > 1024:
                    logger.debug("adv_brochure_from_storage", crd=crd_number)
                    return await asyncio.to_thread(
                        self._extract_text_from_bytes, crd_number, pdf_bytes,
                    )
        except Exception:
            pass  # fall through to legacy/download

        # 2. Try legacy local path (seed script). The actual IAPD
        # download is wrapped in the SEC EDGAR provider gate so a hung
        # or rate-limited brochure server cannot starve unrelated
        # workers — circuit opens after five consecutive failures and
        # cools down for 30 s before probing again.
        from app.core.runtime.gates import get_sec_edgar_gate
        from app.core.runtime.provider_gate import ProviderGateError

        gate = get_sec_edgar_gate()
        try:
            pdf_bytes = await gate.call(
                f"adv_brochure:{crd_number}",
                lambda: run_in_sec_thread(self._resolve_pdf_sync, crd_number),
            )
        except ProviderGateError as exc:
            logger.warning(
                "adv_brochure_gate_blocked",
                crd=crd_number,
                error=str(exc),
            )
            return ""
        if not pdf_bytes:
            return ""

        # Persist to StorageClient for future reads
        try:
            await storage.write(
                storage_key, pdf_bytes, content_type="application/pdf",
            )
        except Exception:
            pass  # non-fatal — extraction still works

        return await asyncio.to_thread(
            self._extract_text_from_bytes, crd_number, pdf_bytes,
        )

    @staticmethod
    def _resolve_pdf_sync(crd_number: str) -> bytes | None:
        """Sync: try legacy local path, then download from IAPD."""
        from pathlib import Path

        brochure_dir = Path(".data/lake/brochures")
        local_path = brochure_dir / f"{crd_number}.pdf"

        if local_path.exists() and local_path.stat().st_size > 1024:
            logger.debug("adv_brochure_from_cache", crd=crd_number)
            return local_path.read_bytes()

        # Download from IAPD and persist to legacy path
        pdf_bytes = AdvService._download_brochure_pdf(crd_number)
        if not pdf_bytes:
            return None
        brochure_dir.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(pdf_bytes)
        return pdf_bytes

    @staticmethod
    def _extract_text_from_bytes(crd_number: str, pdf_bytes: bytes) -> str:
        """Sync PyMuPDF text extraction from raw PDF bytes."""
        import fitz  # pymupdf

        try:
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                pages = [page.get_text("text") for page in doc]
            text_out = "\n\n".join(p for p in pages if p.strip())
            logger.info(
                "adv_brochure_extracted",
                crd=crd_number,
                pages=len(pages),
                chars=len(text_out),
            )
            return text_out
        except Exception as exc:
            logger.warning("adv_brochure_extract_failed", crd=crd_number, error=str(exc))
            return ""

    @staticmethod
    def _download_brochure_pdf(crd_number: str) -> bytes | None:
        """Download brochure PDF from IAPD with retry on 403."""
        import time as _time

        import httpx

        pdf_url = _ADV_BROCHURE_URL.format(crd=crd_number)

        for attempt in range(4):
            check_iapd_rate()
            try:
                resp = httpx.get(
                    pdf_url,
                    headers={"User-Agent": SEC_USER_AGENT},
                    timeout=60.0,
                    follow_redirects=True,
                )
                if resp.status_code == 404:
                    logger.info("adv_brochure_not_found", crd=crd_number)
                    return None
                if resp.status_code == 403:
                    wait = 2 ** attempt * 2
                    logger.warning(
                        "adv_brochure_rate_limited",
                        crd=crd_number,
                        attempt=attempt + 1,
                        wait=wait,
                    )
                    _time.sleep(wait)
                    continue
                resp.raise_for_status()

                if len(resp.content) < 1024:
                    logger.warning("adv_brochure_too_small", crd=crd_number, size=len(resp.content))
                    return None
                return resp.content
            except Exception as exc:
                logger.warning("adv_brochure_download_failed", crd=crd_number, error=str(exc))
                return None

        logger.warning("adv_brochure_max_retries", crd=crd_number)
        return None

    # ── Persist team + brochure sections ─────────────────────────

    async def _upsert_team(
        self,
        crd_number: str,
        members: list[AdvTeamMember],
    ) -> None:
        """Upsert team members to sec_manager_team."""
        if not members:
            return

        values = [
            {
                "crd_number": m.crd_number,
                "person_name": m.person_name,
                "title": m.title,
                "role": m.role,
                "education": m.education,
                "certifications": m.certifications or None,
                "years_experience": m.years_experience,
                "bio_summary": m.bio_summary,
                "data_fetched_at": datetime.now(UTC),
            }
            for m in members
        ]

        async with self._db_session_factory() as session, session.begin():
            stmt = pg_insert(SecManagerTeam).values(values)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_sec_manager_team_crd_person",
                set_={
                    "title": stmt.excluded.title,
                    "role": stmt.excluded.role,
                    "education": stmt.excluded.education,
                    "certifications": stmt.excluded.certifications,
                    "years_experience": stmt.excluded.years_experience,
                    "bio_summary": stmt.excluded.bio_summary,
                    "data_fetched_at": stmt.excluded.data_fetched_at,
                },
            )
            await session.execute(stmt)

    async def _upsert_brochure_sections(
        self,
        crd_number: str,
        sections: list[AdvBrochureSection],
    ) -> None:
        """Upsert brochure text sections to sec_manager_brochure_text."""
        if not sections:
            return

        values = [
            {
                "crd_number": s.crd_number,
                "section": s.section,
                "filing_date": s.filing_date,
                "content": s.content,
            }
            for s in sections
        ]

        async with self._db_session_factory() as session, session.begin():
            for val in values:
                stmt = pg_insert(SecManagerBrochureText).values(val)
                stmt = stmt.on_conflict_do_update(
                    constraint="sec_manager_brochure_text_pkey",
                    set_={"content": stmt.excluded.content},
                )
                await session.execute(stmt)


# ── Brochure text parsing (module-level helpers) ─────────────────


def _classify_brochure_sections(
    crd_number: str,
    full_text: str,
) -> list[AdvBrochureSection]:
    """Split brochure text into classified sections based on ADV Item headings.

    Falls back to storing the full text as a single "full_brochure" section
    if no Item headings are detected.
    """
    today = date.today().isoformat()

    # Try to split by Item headings
    # Find all section boundaries
    boundaries: list[tuple[int, str]] = []
    for section_key, pattern in _SECTION_PATTERNS:
        for m in pattern.finditer(full_text):
            boundaries.append((m.start(), section_key))

    if not boundaries:
        # No structured sections found — store as single block
        if len(full_text.strip()) > 100:
            return [
                AdvBrochureSection(
                    crd_number=crd_number,
                    section="full_brochure",
                    content=full_text.strip(),
                    filing_date=today,
                ),
            ]
        return []

    # Sort by position, extract text between boundaries
    boundaries.sort(key=lambda x: x[0])
    sections: list[AdvBrochureSection] = []
    seen: set[str] = set()

    for i, (start, key) in enumerate(boundaries):
        if key in seen:
            continue  # first match wins for duplicate section names
        seen.add(key)

        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(full_text)
        content = full_text[start:end].strip()

        if len(content) > 50:  # skip near-empty sections
            sections.append(
                AdvBrochureSection(
                    crd_number=crd_number,
                    section=key,
                    content=content,
                    filing_date=today,
                ),
            )

    return sections


def _parse_team_from_brochure(
    crd_number: str,
    full_text: str,
) -> list[AdvTeamMember]:
    """Extract team member names, titles, and certifications from brochure text.

    Uses regex patterns against Part 2B supplement content (typically appended
    to the Part 2A brochure). Returns deduplicated list of team members.
    """
    members: list[AdvTeamMember] = []
    seen_names: set[str] = set()

    for match in _TEAM_PERSON_RE.finditer(full_text):
        name = match.group(1).strip()
        title_raw = match.group(2).strip().rstrip(",.")

        # Deduplicate
        name_key = name.lower()
        if name_key in seen_names:
            continue
        seen_names.add(name_key)

        # Extract certifications from surrounding context
        context_start = max(0, match.start() - 50)
        context_end = min(len(full_text), match.end() + 500)
        context = full_text[context_start:context_end]

        certs = sorted(set(_CERTIFICATION_RE.findall(context)))

        # Extract years of experience
        years: int | None = None
        exp_match = _EXPERIENCE_RE.search(context)
        if exp_match:
            years = int(exp_match.group(1))

        # Build bio summary from next ~300 chars after name+title
        bio_start = match.end()
        bio_end = min(len(full_text), bio_start + 300)
        bio_raw = full_text[bio_start:bio_end].strip()
        # Truncate at paragraph break
        para_break = bio_raw.find("\n\n")
        if para_break > 0:
            bio_raw = bio_raw[:para_break]
        bio = bio_raw.strip() if len(bio_raw) > 20 else None

        members.append(
            AdvTeamMember(
                crd_number=crd_number,
                person_name=name,
                title=title_raw or None,
                role=None,
                education=None,
                certifications=certs,
                years_experience=years,
                bio_summary=bio,
            ),
        )

    return members


# ── Fund Data Availability ───────────────────────────────────────


async def compute_fund_data_availability(
    fund_cik: str,
    fund_universe: str,
    db: Any,
) -> FundDataAvailability:
    """Compute data availability matrix for a fund detail page.

    Queries sec_registered_funds, sec_nport_holdings, sec_fund_style_snapshots,
    and sec_manager_team. Never raises — returns all-False on error.
    """
    from data_providers.sec.models import FundDataAvailability

    try:
        universe: str = "registered" if fund_universe == "registered" else "private"

        # Check holdings
        has_holdings = False
        try:
            r = await db.execute(
                text("SELECT 1 FROM sec_nport_holdings WHERE cik = :cik LIMIT 1"),
                {"cik": fund_cik},
            )
            has_holdings = r.scalar() is not None
        except Exception:
            pass

        # Check NAV history
        has_nav = False
        try:
            r = await db.execute(
                text(
                    "SELECT ticker FROM sec_registered_funds WHERE cik = :cik",
                ),
                {"cik": fund_cik},
            )
            row = r.fetchone()
            if row and row[0]:
                # Ticker exists — check if NAV data was ingested
                r2 = await db.execute(
                    text(
                        "SELECT 1 FROM benchmark_nav WHERE ticker = :t LIMIT 1",
                    ),
                    {"t": row[0]},
                )
                has_nav = r2.scalar() is not None
        except Exception:
            pass

        # Check style analysis
        has_style = False
        try:
            r = await db.execute(
                text(
                    "SELECT 1 FROM sec_fund_style_snapshots WHERE cik = :cik LIMIT 1",
                ),
                {"cik": fund_cik},
            )
            has_style = r.scalar() is not None
        except Exception:
            pass

        # Check portfolio manager
        has_pm = False
        try:
            # Get CRD from registered fund, then check team
            r = await db.execute(
                text(
                    "SELECT crd_number FROM sec_registered_funds WHERE cik = :cik",
                ),
                {"cik": fund_cik},
            )
            row = r.fetchone()
            if row and row[0]:
                r2 = await db.execute(
                    text(
                        "SELECT 1 FROM sec_manager_team WHERE crd_number = :crd LIMIT 1",
                    ),
                    {"crd": row[0]},
                )
                has_pm = r2.scalar() is not None
        except Exception:
            pass

        # Check peer analysis (>= 3 funds with same style_label)
        has_peer = False
        try:
            r = await db.execute(
                text(
                    "SELECT style_label FROM sec_fund_style_snapshots "
                    "WHERE cik = :cik ORDER BY report_date DESC LIMIT 1",
                ),
                {"cik": fund_cik},
            )
            row = r.fetchone()
            if row and row[0]:
                r2 = await db.execute(
                    text(
                        "SELECT COUNT(DISTINCT cik) FROM sec_fund_style_snapshots "
                        "WHERE style_label = :label AND cik != :cik",
                    ),
                    {"label": row[0], "cik": fund_cik},
                )
                count = r2.scalar() or 0
                has_peer = count >= 3
        except Exception:
            pass

        disclosure_note = None
        if universe == "private":
            disclosure_note = "Holdings not publicly available for private funds"

        return FundDataAvailability(
            fund_universe=universe,  # type: ignore[arg-type]
            has_holdings=has_holdings,
            has_nav_history=has_nav,
            has_style_analysis=has_style,
            has_portfolio_manager=has_pm,
            has_peer_analysis=has_peer,
            disclosure_note=disclosure_note,
        )

    except Exception as exc:
        logger.warning("fund_data_availability_failed", cik=fund_cik, error=str(exc))
        from data_providers.sec.models import FundDataAvailability

        return FundDataAvailability(
            fund_universe="private",  # type: ignore[arg-type]
            has_holdings=False,
            has_nav_history=False,
            has_style_analysis=False,
            has_portfolio_manager=False,
            has_peer_analysis=False,
            disclosure_note=None,
        )
