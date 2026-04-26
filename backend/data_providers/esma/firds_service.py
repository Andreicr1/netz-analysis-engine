"""ESMA FIRDS FULINS_C downloader and parser.

Downloads the daily FIRDS Full Instrument Reference Data for Collective
Investment Vehicles (CFI prefix "C") and stream-parses the XML to extract
ISIN ↔ LEI mappings.

Fully standalone: zero imports from ``app.*``.

XML structure (ISO 20022 auth.017.001.02):
  BizData > Pyld > Document > FinInstrmRptgRefDataRpt > RefData
    RefData/FinInstrmGnlAttrbts/Id          → ISIN (12 chars)
    RefData/FinInstrmGnlAttrbts/FullNm      → instrument full name
    RefData/FinInstrmGnlAttrbts/ClssfctnTp  → CFI code (6 chars)
    RefData/FinInstrmGnlAttrbts/NtnlCcy     → currency (ISO 4217)
    RefData/Issr                             → issuer LEI (20 chars)
    RefData/TradgVnRltdAttrbts/Id           → MIC code

Usage::

    async with FirdsService() as svc:
        async for instrument in svc.iter_instruments(lei_filter=known_leis):
            print(instrument.isin, instrument.lei)
"""
from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from xml.etree.ElementTree import iterparse

import httpx
import structlog

logger = structlog.get_logger()

# ── Constants ────────────────────────────────────────────────────

FIRDS_SOLR_URL = (
    "https://registers.esma.europa.eu/solr/esma_registers_firds_files/select"
)

# Direct download pattern (fallback if Solr discovery fails)
FIRDS_DIRECT_URL = "https://firds.esma.europa.eu/firds/FULINS_C_{date}_01of01.zip"

# ISIN format: 2 letter country + 9 alphanumeric + 1 check digit
_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

# LEI format: 20 alphanumeric characters
_LEI_RE = re.compile(r"^[A-Z0-9]{20}$")

# XML namespace — the tag prefix varies by ESMA schema version.
# We strip namespaces during parsing to avoid fragile coupling.


@dataclass(frozen=True)
class FirdsInstrument:
    """Single instrument from FIRDS FULINS_C."""

    isin: str
    lei: str
    full_name: str
    cfi_code: str | None
    currency: str | None
    mic: str | None


# ── Service ──────────────────────────────────────────────────────


class FirdsService:
    """Download and parse ESMA FIRDS FULINS_C data.

    Usage::

        async with FirdsService() as svc:
            url = await svc.find_latest_fulins_c_url()
            data = await svc.download_zip(url)
            for inst in svc.parse_xml(data, lei_filter=known_leis):
                ...
    """

    def __init__(self, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._external_client = http_client is not None
        self._client = http_client or httpx.AsyncClient(
            timeout=300.0,  # large file download
            follow_redirects=True,
        )

    async def __aenter__(self) -> FirdsService:
        return self

    async def __aexit__(self, *exc: object) -> None:
        if not self._external_client:
            await self._client.aclose()

    async def find_latest_fulins_c_url(self, lookback_days: int = 7) -> str:
        """Discover the latest FULINS_C file URL via ESMA Solr API.

        Falls back to direct URL construction if Solr discovery fails.
        """
        today = date.today()

        # Try Solr discovery first
        for days_ago in range(lookback_days):
            target_date = today - timedelta(days=days_ago)
            date_str = target_date.strftime("%Y-%m-%d")

            try:
                params = {
                    "q": "*",
                    "fq": [
                        f"publication_date:[{date_str}T00:00:00Z TO {date_str}T23:59:59Z]",
                        "file_name:FULINS_C*",
                    ],
                    "fl": "file_name,download_link",
                    "wt": "json",
                    "rows": "10",
                }
                resp = await self._client.get(FIRDS_SOLR_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
                docs = data.get("response", {}).get("docs", [])

                if docs:
                    # Prefer the 01of01 file (or first available)
                    for doc in docs:
                        dl = doc.get("download_link")
                        if dl:
                            logger.info(
                                "firds.url_discovered",
                                url=dl,
                                date=date_str,
                            )
                            return str(dl)
            except Exception as exc:
                logger.debug("firds.solr_lookup_failed", date=date_str, error=str(exc))

        # Fallback: direct URL for most recent weekday
        for days_ago in range(lookback_days):
            target_date = today - timedelta(days=days_ago)
            if target_date.weekday() < 5:  # Mon-Fri
                url = FIRDS_DIRECT_URL.format(date=target_date.strftime("%Y%m%d"))
                logger.info("firds.using_direct_url", url=url)
                return url

        # Last resort: today's date
        url = FIRDS_DIRECT_URL.format(date=today.strftime("%Y%m%d"))
        return url

    async def download_zip(self, url: str) -> bytes:
        """Download FIRDS ZIP file into memory.

        FULINS_C is typically 50-150 MB compressed. For a seed script
        running on a dev machine, in-memory download is acceptable.
        """
        logger.info("firds.download_starting", url=url)
        resp = await self._client.get(url)
        resp.raise_for_status()
        size_mb = len(resp.content) / (1024 * 1024)
        logger.info("firds.download_complete", size_mb=f"{size_mb:.1f}")
        return resp.content

    def parse_xml(
        self,
        zip_data: bytes,
        *,
        lei_filter: set[str] | None = None,
    ) -> Iterator[FirdsInstrument]:
        """Stream-parse FIRDS FULINS_C XML from ZIP bytes.

        Yields FirdsInstrument for each valid record. Uses iterparse
        for constant memory usage regardless of file size.

        Args:
            zip_data: Raw ZIP file bytes.
            lei_filter: If provided, only yield instruments whose LEI
                is in this set. Dramatically reduces output for large files.

        """
        # Extract XML from ZIP
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            xml_names = [n for n in zf.namelist() if n.endswith(".xml")]
            if not xml_names:
                logger.error("firds.no_xml_in_zip")
                return

            xml_name = xml_names[0]
            logger.info("firds.parsing_xml", filename=xml_name)

            with zf.open(xml_name) as xml_file:
                yield from self._iterparse_refdata(xml_file, lei_filter=lei_filter)

    def _iterparse_refdata(
        self,
        xml_file: io.BufferedIOBase,
        *,
        lei_filter: set[str] | None = None,
    ) -> Iterator[FirdsInstrument]:
        """Low-level iterparse of RefData elements."""
        count = 0
        yielded = 0

        for event, elem in iterparse(xml_file, events=("end",)):
            # Strip namespace to get local tag name
            tag = _strip_ns(elem.tag)

            if tag != "RefData":
                continue

            count += 1
            instrument = _extract_instrument(elem)
            # Free memory immediately
            elem.clear()

            if instrument is None:
                continue

            if lei_filter is not None and instrument.lei not in lei_filter:
                continue

            yielded += 1
            yield instrument

            if yielded % 10000 == 0:
                logger.info("firds.parse_progress", yielded=yielded, scanned=count)

        logger.info(
            "firds.parse_complete",
            total_scanned=count,
            total_yielded=yielded,
        )


# ── Parsing Helpers ──────────────────────────────────────────────


def _strip_ns(tag: str) -> str:
    """Strip XML namespace prefix: '{ns}Tag' → 'Tag'."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _find_recursive(elem: object, local_name: str) -> object | None:
    """Find first descendant element matching local tag name (ignoring namespace)."""
    # Use the element's iter method to search all descendants
    for child in elem:  # type: ignore[union-attr]
        child_tag = _strip_ns(child.tag)
        if child_tag == local_name:
            return child
        # Recurse one level into sub-elements
        for grandchild in child:
            gc_tag = _strip_ns(grandchild.tag)
            if gc_tag == local_name:
                return grandchild
    return None


def _get_text(elem: object, local_name: str) -> str | None:
    """Get text of a descendant element by local tag name."""
    found = _find_recursive(elem, local_name)
    if found is not None and hasattr(found, "text") and found.text:
        return found.text.strip()
    return None


def _get_mic_from_trading_venue(ref_data: object) -> str | None:
    """Extract MIC from TradgVnRltdAttrbts/Id inside a RefData element."""
    trading_venue = _find_recursive(ref_data, "TradgVnRltdAttrbts")
    if trading_venue is not None:
        return _get_text(trading_venue, "Id")
    return None


def _extract_instrument(ref_data: object) -> FirdsInstrument | None:
    """Extract a FirdsInstrument from a RefData XML element."""
    isin = _get_text(ref_data, "Id")
    lei = _get_text(ref_data, "Issr")

    if not isin or not lei:
        return None

    isin = isin.strip().upper()
    lei = lei.strip().upper()

    # Validate formats
    if not _ISIN_RE.match(isin):
        return None
    if not _LEI_RE.match(lei):
        return None

    # MIC lives at TradgVnRltdAttrbts/Id — extract from that container
    # to avoid picking up the top-level FinInstrmGnlAttrbts/Id (ISIN).
    mic = _get_mic_from_trading_venue(ref_data)

    return FirdsInstrument(
        isin=isin,
        lei=lei,
        full_name=_get_text(ref_data, "FullNm") or "",
        cfi_code=_get_text(ref_data, "ClssfctnTp"),
        currency=_get_text(ref_data, "NtnlCcy"),
        mic=mic,
    )
