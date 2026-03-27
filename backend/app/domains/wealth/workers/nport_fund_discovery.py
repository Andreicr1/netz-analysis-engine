"""N-PORT fund discovery worker — populates sec_registered_funds from EDGAR.

Usage:
    python -m app.domains.wealth.workers.nport_fund_discovery

Discovers registered funds (mutual funds, ETFs) that file N-PORT, filters by
AUM >= $50M, resolves adviser CIK → CRD, and upserts into sec_registered_funds.

GLOBAL TABLE: No organization_id, no RLS.
Advisory lock ID = 900_024.
"""

import asyncio
from xml.etree import ElementTree

import structlog
from sqlalchemy import text

from app.core.db.engine import async_session_factory as async_session

logger = structlog.get_logger()
NPORT_DISCOVERY_LOCK_ID = 900_024
AUM_THRESHOLD_USD = 50_000_000
_UPSERT_CHUNK_SIZE = 200
_STALENESS_DAYS = 35


async def run_nport_fund_discovery() -> dict:
    """Discover registered funds filing N-PORT and populate sec_registered_funds."""
    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({NPORT_DISCOVERY_LOCK_ID})")
        )
        if not lock_result.scalar():
            logger.warning("nport_fund_discovery already running (advisory lock not acquired)")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            from data_providers.sec.shared import (
                SEC_USER_AGENT,
                resolve_crd_from_adviser_cik,
                run_in_sec_thread,
            )

            # Step 1: Get existing CIKs and their last fetch dates
            existing_result = await db.execute(
                text("SELECT cik, data_fetched_at FROM sec_registered_funds")
            )
            existing = {
                row[0]: row[1]
                for row in existing_result.all()
            }

            # Step 2: Discover N-PORT filers via EDGAR EFTS
            discovered_ciks = await run_in_sec_thread(
                _discover_nport_filers, SEC_USER_AGENT
            )

            if not discovered_ciks:
                logger.info("nport_discovery_no_filers")
                return {"status": "completed", "discovered": 0, "upserted": 0}

            logger.info("nport_discovery_filers_found", total=len(discovered_ciks))

            # Step 3: Filter to CIKs needing refresh
            from datetime import datetime, timedelta, timezone

            cutoff = datetime.now(timezone.utc) - timedelta(days=_STALENESS_DAYS)
            ciks_to_process = []
            for cik in discovered_ciks:
                fetched = existing.get(cik)
                if fetched is None or fetched < cutoff:
                    ciks_to_process.append(cik)

            if not ciks_to_process:
                logger.info("nport_discovery_all_fresh", existing=len(existing))
                return {"status": "completed", "discovered": len(discovered_ciks), "upserted": 0}

            logger.info("nport_discovery_processing", to_process=len(ciks_to_process))

            # Step 4: Fetch N-PORT headers and build fund records
            upserted = 0
            errors = 0
            below_threshold = 0
            batch: list[dict] = []

            for cik in ciks_to_process:
                try:
                    fund_data = await run_in_sec_thread(
                        _fetch_nport_header, cik, SEC_USER_AGENT
                    )
                    if fund_data is None:
                        continue

                    total_assets = fund_data.get("total_assets")
                    cik_exists = cik in existing

                    # AUM filter
                    if total_assets is not None and total_assets < AUM_THRESHOLD_USD:
                        if cik_exists:
                            # Mark as below threshold
                            await db.execute(
                                text(
                                    "UPDATE sec_registered_funds "
                                    "SET aum_below_threshold = TRUE, data_fetched_at = now() "
                                    "WHERE cik = :cik"
                                ),
                                {"cik": cik},
                            )
                            await db.commit()
                            below_threshold += 1
                        continue

                    # Resolve CRD
                    adviser_cik = fund_data.get("adviser_cik")
                    crd_number = None
                    if adviser_cik:
                        crd_number = await resolve_crd_from_adviser_cik(
                            adviser_cik, db,
                            adviser_name=fund_data.get("adviser_name"),
                        )

                    batch.append({
                        "cik": cik,
                        "crd_number": crd_number,
                        "fund_name": fund_data.get("fund_name", f"Fund {cik}"),
                        "fund_type": fund_data.get("fund_type", "mutual_fund"),
                        "ticker": fund_data.get("ticker"),
                        "series_id": fund_data.get("series_id"),
                        "class_id": fund_data.get("class_id"),
                        "total_assets": total_assets,
                        "total_shareholder_accounts": fund_data.get("total_shareholder_accounts"),
                    })

                    # Flush in chunks
                    if len(batch) >= _UPSERT_CHUNK_SIZE:
                        count = await _upsert_batch(db, batch)
                        upserted += count
                        batch.clear()

                except Exception as exc:
                    errors += 1
                    logger.warning("nport_discovery_cik_failed", cik=cik, error=str(exc))

            # Flush remaining batch
            if batch:
                count = await _upsert_batch(db, batch)
                upserted += count

            summary = {
                "status": "completed",
                "discovered": len(discovered_ciks),
                "processed": len(ciks_to_process),
                "upserted": upserted,
                "below_threshold": below_threshold,
                "errors": errors,
            }
            logger.info("nport_fund_discovery_complete", **summary)
            return summary

        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({NPORT_DISCOVERY_LOCK_ID})")
            )


def _discover_nport_filers(user_agent: str) -> list[str]:
    """Discover unique CIKs that file N-PORT via EDGAR full-text search.

    Uses the EFTS search endpoint with pagination (max 10,000 results).
    Sync, rate-limited. Returns deduplicated CIK list.
    """
    import time

    import httpx

    from data_providers.sec.shared import check_edgar_rate

    ciks: set[str] = set()

    # EDGAR EFTS full-text search — paginate to get all N-PORT filers
    # Max 10,000 results (EFTS hard limit), 100 per page
    page_size = 100
    max_pages = 100  # 100 * 100 = 10,000

    for page_idx in range(max_pages):
        try:
            check_edgar_rate()
            start = page_idx * page_size
            resp = httpx.get(
                "https://efts.sec.gov/LATEST/search-index",
                params={
                    "q": '"NPORT-P"',
                    "dateRange": "custom",
                    "startdt": "2024-01-01",
                    "forms": "NPORT-P",
                    "from": str(start),
                    "size": str(page_size),
                },
                headers={"User-Agent": user_agent},
                timeout=30.0,
            )
            if resp.status_code != 200:
                logger.warning("nport_efts_page_failed", status=resp.status_code, page=page_idx)
                break

            data = resp.json()
            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                break

            for hit in hits:
                source = hit.get("_source", {})
                for c in source.get("ciks") or []:
                    ciks.add(str(c).zfill(10))

            total = data.get("hits", {}).get("total", {})
            total_value = total.get("value", 0) if isinstance(total, dict) else int(total or 0)

            if start + page_size >= total_value or start + page_size >= 10000:
                break

            time.sleep(0.15)
        except Exception as exc:
            logger.warning("nport_efts_page_error", page=page_idx, error=str(exc))
            break

    logger.info("nport_efts_discovery_done", ciks_from_efts=len(ciks))

    # Supplement: EDGAR company search Atom feed (different index, catches stragglers)
    try:
        check_edgar_rate()
        resp = httpx.get(
            "https://www.sec.gov/cgi-bin/browse-edgar",
            params={
                "action": "getcompany",
                "type": "NPORT-P",
                "dateb": "",
                "owner": "include",
                "count": "100",
                "search_text": "",
                "output": "atom",
            },
            headers={"User-Agent": user_agent},
            timeout=30.0,
        )
        if resp.status_code == 200:
            root = ElementTree.fromstring(resp.text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns):
                cik_elem = entry.find(".//atom:cik", ns)
                if cik_elem is not None and cik_elem.text:
                    ciks.add(cik_elem.text.strip().zfill(10))
    except Exception as exc:
        logger.debug("nport_browse_discovery_failed", error=str(exc))

    return sorted(ciks)


def _fetch_nport_header(cik: str, user_agent: str) -> dict | None:
    """Fetch latest N-PORT filing header for a CIK. Sync, rate-limited.

    Step 1: submissions JSON for fund name, SIC, fund type.
    Step 2: N-PORT filing index → primary_doc XML → totalAssets + adviser info.
    Returns dict with fund metadata or None if no N-PORT found.
    """
    import httpx

    from data_providers.sec.shared import check_edgar_rate

    check_edgar_rate()

    try:
        # Step 1: Get submissions JSON for the CIK
        resp = httpx.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers={"User-Agent": user_agent},
            timeout=15.0,
        )
        if resp.status_code != 200:
            return None

        data = resp.json()
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])

        # Find latest N-PORT filing
        nport_idx = None
        for i, form in enumerate(forms):
            if form in ("NPORT-P", "NPORT-P/A"):
                nport_idx = i
                break

        if nport_idx is None:
            return None

        fund_name = data.get("name", f"Fund {cik}")
        sic = data.get("sic", "")
        sic_desc = data.get("sicDescription", "").lower()
        fund_type = "mutual_fund"
        if "etf" in fund_name.lower() or "exchange traded" in sic_desc:
            fund_type = "etf"
        elif "closed" in sic_desc or sic == "6726":
            fund_type = "closed_end"

        # Extract ticker from submissions JSON — tickers array at top level
        tickers_list = data.get("tickers", [])
        ticker = None
        if tickers_list:
            # Pick first non-empty ticker
            for t in tickers_list:
                val = t.get("ticker") if isinstance(t, dict) else t
                if val and isinstance(val, str) and val.strip():
                    ticker = val.strip().upper()
                    break

        result: dict = {
            "fund_name": fund_name,
            "fund_type": fund_type,
            "ticker": ticker,
            "total_assets": None,
            "total_shareholder_accounts": None,
            "series_id": None,
            "class_id": None,
            "adviser_cik": None,
            "adviser_name": None,
        }

        # Step 2: Fetch N-PORT XML for totalAssets + adviser info
        if accessions and nport_idx < len(accessions):
            accession_raw = accessions[nport_idx]
            accession_nodash = accession_raw.replace("-", "")
            primary_doc = primary_docs[nport_idx] if nport_idx < len(primary_docs) else None

            if primary_doc:
                check_edgar_rate()
                try:
                    xml_url = (
                        f"https://www.sec.gov/Archives/edgar/data/"
                        f"{cik.lstrip('0') or '0'}/{accession_nodash}/{primary_doc}"
                    )
                    xml_resp = httpx.get(
                        xml_url,
                        headers={"User-Agent": user_agent},
                        timeout=30.0,
                    )
                    if xml_resp.status_code == 200:
                        _parse_nport_xml(xml_resp.text, result)
                except Exception as exc:
                    logger.debug("nport_xml_fetch_failed", cik=cik, error=str(exc))

            # Step 3: If no ticker yet, extract from filing header SGML
            # (umbrella funds have tickers per series/class in the header)
            if not result.get("ticker"):
                check_edgar_rate()
                try:
                    header_url = (
                        f"https://www.sec.gov/Archives/edgar/data/"
                        f"{cik.lstrip('0') or '0'}/{accession_nodash}/"
                        f"{accession_raw}-index-headers.html"
                    )
                    hdr_resp = httpx.get(
                        header_url,
                        headers={"User-Agent": user_agent},
                        timeout=15.0,
                    )
                    if hdr_resp.status_code == 200:
                        _parse_series_class_header(hdr_resp.text, result)
                except Exception as exc:
                    logger.debug("nport_header_sgml_failed", cik=cik, error=str(exc))

        return result

    except Exception as exc:
        logger.debug("nport_header_fetch_failed", cik=cik, error=str(exc))
        return None


def _parse_nport_xml(xml_text: str, result: dict) -> None:
    """Extract totalAssets, adviser info, series/class from N-PORT XML."""
    try:
        # N-PORT XML uses a namespace — handle both with and without
        root = ElementTree.fromstring(xml_text)

        # Try to find elements with namespace prefix or without
        ns_map = {"n": "http://www.sec.gov/edgar/nport"}

        def _find(tag: str) -> str | None:
            # Try with namespace
            elem = root.find(f".//{{{ns_map['n']}}}{tag}")
            if elem is not None and elem.text:
                return elem.text.strip()
            # Try without namespace
            elem = root.find(f".//{tag}")
            if elem is not None and elem.text:
                return elem.text.strip()
            return None

        # totalAssets (in genInfo or generalInfo)
        total_assets = _find("totAssets") or _find("totalAssets") or _find("netAssets")
        if total_assets:
            try:
                result["total_assets"] = int(float(total_assets))
            except (ValueError, TypeError):
                pass

        # Adviser info
        adviser_name = _find("adviserName") or _find("name")
        if adviser_name and len(adviser_name) > 2:
            result["adviser_name"] = adviser_name

        adviser_cik_val = _find("adviserFileNumber") or _find("adviserCIK")
        if adviser_cik_val:
            # Clean up — could be file number like 801-XXXXX
            digits = "".join(c for c in adviser_cik_val if c.isdigit())
            if digits:
                result["adviser_cik"] = digits.zfill(10)

        # Series / class
        series = _find("seriesId")
        if series:
            result["series_id"] = series
        class_id = _find("classId")
        if class_id:
            result["class_id"] = class_id

    except Exception as exc:
        logger.debug("nport_xml_parse_failed", error=str(exc))


async def _upsert_batch(db: object, batch: list[dict]) -> int:
    """Upsert a batch of fund records into sec_registered_funds."""
    if not batch:
        return 0

    count = 0
    for record in batch:
        try:
            await db.execute(  # type: ignore[union-attr]
                text("""
                    INSERT INTO sec_registered_funds
                        (cik, crd_number, fund_name, fund_type, ticker, series_id, class_id,
                         total_assets, total_shareholder_accounts, aum_below_threshold,
                         data_fetched_at)
                    VALUES
                        (:cik, :crd_number, :fund_name, :fund_type, :ticker, :series_id, :class_id,
                         :total_assets, :total_shareholder_accounts, FALSE, now())
                    ON CONFLICT (cik) DO UPDATE SET
                        crd_number = EXCLUDED.crd_number,
                        fund_name = EXCLUDED.fund_name,
                        fund_type = EXCLUDED.fund_type,
                        ticker = COALESCE(EXCLUDED.ticker, sec_registered_funds.ticker),
                        series_id = COALESCE(EXCLUDED.series_id, sec_registered_funds.series_id),
                        class_id = COALESCE(EXCLUDED.class_id, sec_registered_funds.class_id),
                        total_assets = EXCLUDED.total_assets,
                        total_shareholder_accounts = EXCLUDED.total_shareholder_accounts,
                        aum_below_threshold = FALSE,
                        data_fetched_at = now()
                """),
                record,
            )
            count += 1
        except Exception as exc:
            logger.warning("nport_upsert_failed", cik=record.get("cik"), error=str(exc))

    await db.commit()  # type: ignore[union-attr]
    return count


def _parse_series_class_header(sgml_text: str, result: dict) -> None:
    """Extract first series ticker from EDGAR filing header SGML.

    The ``-index-headers.html`` file contains SERIES-AND-CLASSES-CONTRACTS-DATA
    with tickers per class.  We grab the first ticker found as representative.
    Also populates series_id and class_id if not already set.
    """
    import re

    # Extract first SERIES-ID
    if not result.get("series_id"):
        m = re.search(r"<SERIES-ID>\s*(\S+)", sgml_text)
        if m:
            result["series_id"] = m.group(1).strip()

    # Extract first CLASS-CONTRACT-ID
    if not result.get("class_id"):
        m = re.search(r"<CLASS-CONTRACT-ID>\s*(\S+)", sgml_text)
        if m:
            result["class_id"] = m.group(1).strip()

    # Extract first CLASS-CONTRACT-TICKER-SYMBOL
    m = re.search(r"<CLASS-CONTRACT-TICKER-SYMBOL>\s*(\S+)", sgml_text)
    if m:
        ticker = m.group(1).strip().upper()
        if ticker and len(ticker) <= 10:
            result["ticker"] = ticker


if __name__ == "__main__":
    asyncio.run(run_nport_fund_discovery())
