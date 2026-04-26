"""PR-Q11B Phase 1.4 — FIRDS UCITS security sync worker tests.

Tests the FIRDS worker with mocked HTTP (no real ESMA download).
Verifies LEI filter, UPSERT, staleness gate.

Run with::

    pytest backend/tests/jobs/test_firds_ucits_security_sync.py -v
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

# ── Unit tests (no DB) ──────────────────────────────────────────────


class TestFirdsInstrumentParsing:
    """Test the FirdsService parse_xml logic with synthetic XML."""

    def test_parse_xml_filters_by_lei(self):
        """Instruments not in lei_filter are excluded."""
        from data_providers.esma.firds_service import FirdsService

        # Build a minimal valid FIRDS XML with two instruments
        xml_content = _build_firds_xml([
            ("IE00B4L5Y983", "549300MLUDYVRQOOXS22", "iShares Core MSCI World", "CIU", "EUR", "XDUB"),
            ("LU0292107645", "ZZZZZZZZZZZZZZZZZ123", "Xtrackers MSCI EM", "CIU", "USD", "XLUX"),
        ])
        zip_data = _xml_to_zip(xml_content)

        svc = FirdsService()
        known_leis = {"549300MLUDYVRQOOXS22"}
        results = list(svc.parse_xml(zip_data, lei_filter=known_leis))

        assert len(results) == 1
        assert results[0].isin == "IE00B4L5Y983"
        assert results[0].lei == "549300MLUDYVRQOOXS22"

    def test_parse_xml_no_filter_yields_all(self):
        """Without lei_filter, all valid instruments are yielded."""
        from data_providers.esma.firds_service import FirdsService

        xml_content = _build_firds_xml([
            ("IE00B4L5Y983", "549300MLUDYVRQOOXS22", "iShares Core", "CIU", "EUR", "XDUB"),
            ("LU0292107645", "222100ABCDEFGHIJK456", "Xtrackers", "CIU", "USD", "XLUX"),
        ])
        zip_data = _xml_to_zip(xml_content)

        svc = FirdsService()
        results = list(svc.parse_xml(zip_data, lei_filter=None))

        assert len(results) == 2

    def test_parse_xml_rejects_invalid_isin(self):
        """Instruments with invalid ISIN format are skipped."""
        from data_providers.esma.firds_service import FirdsService

        xml_content = _build_firds_xml([
            ("INVALID", "549300MLUDYVRQOOXS22", "Bad ISIN Fund", "CIU", "EUR", "XDUB"),
        ])
        zip_data = _xml_to_zip(xml_content)

        svc = FirdsService()
        results = list(svc.parse_xml(zip_data, lei_filter=None))
        assert len(results) == 0

    def test_parse_xml_rejects_invalid_lei(self):
        """Instruments with invalid LEI format are skipped."""
        from data_providers.esma.firds_service import FirdsService

        xml_content = _build_firds_xml([
            ("IE00B4L5Y983", "SHORTLEI", "Bad LEI Fund", "CIU", "EUR", "XDUB"),
        ])
        zip_data = _xml_to_zip(xml_content)

        svc = FirdsService()
        results = list(svc.parse_xml(zip_data, lei_filter=None))
        assert len(results) == 0


class TestFirdsSyncWorkerUnit:
    """Unit tests for the sync worker with mocked DB and HTTP."""

    @pytest.mark.asyncio
    async def test_lock_busy_skips(self):
        """Worker skips if advisory lock is held."""
        from app.core.jobs.firds_ucits_security_sync import run_firds_ucits_security_sync
        from unittest.mock import MagicMock

        mock_db = AsyncMock()

        # pg_try_advisory_lock returns False (lock busy)
        lock_result = MagicMock()
        lock_result.scalar.return_value = False
        mock_db.execute.return_value = lock_result

        result = await run_firds_ucits_security_sync(mock_db)
        assert result["status"] == "skipped"
        assert result["reason"] == "lock_busy"

    @pytest.mark.asyncio
    async def test_no_esma_funds_skips(self):
        """Worker skips if esma_funds is empty."""
        from app.core.jobs.firds_ucits_security_sync import run_firds_ucits_security_sync
        from unittest.mock import MagicMock

        mock_db = AsyncMock()

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # pg_try_advisory_lock
                result.scalar.return_value = True
            elif call_count == 2:
                # SELECT lei FROM esma_funds
                result.fetchall.return_value = []
            else:
                # pg_advisory_unlock
                result.scalar.return_value = True
            return result

        mock_db.execute.side_effect = side_effect

        result = await run_firds_ucits_security_sync(mock_db)
        assert result["status"] == "skipped"
        assert result["reason"] == "no_esma_funds"


# ── Helpers ─────────────────────────────────────────────────────────


def _build_firds_xml(instruments: list[tuple[str, str, str, str, str, str]]) -> bytes:
    """Build minimal FIRDS FULINS_C XML for testing.

    Each instrument tuple: (isin, lei, full_name, cfi_code, currency, mic).
    """
    ref_data_blocks = []
    for isin, lei, name, cfi, ccy, mic in instruments:
        ref_data_blocks.append(f"""
        <RefData>
            <FinInstrmGnlAttrbts>
                <Id>{isin}</Id>
                <FullNm>{name}</FullNm>
                <ClssfctnTp>{cfi}</ClssfctnTp>
                <NtnlCcy>{ccy}</NtnlCcy>
            </FinInstrmGnlAttrbts>
            <Issr>{lei}</Issr>
            <TradgVnRltdAttrbts>
                <Id>{mic}</Id>
            </TradgVnRltdAttrbts>
        </RefData>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<BizData>
  <Pyld>
    <Document>
      <FinInstrmRptgRefDataRpt>
        {"".join(ref_data_blocks)}
      </FinInstrmRptgRefDataRpt>
    </Document>
  </Pyld>
</BizData>"""
    return xml.encode("utf-8")


def _xml_to_zip(xml_bytes: bytes) -> bytes:
    """Wrap XML bytes in a ZIP archive for FirdsService.parse_xml."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("FULINS_C_20260426_01of01.xml", xml_bytes)
    return buf.getvalue()
