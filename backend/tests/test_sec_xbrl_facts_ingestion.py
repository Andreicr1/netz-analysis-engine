from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.db.engine import async_session_factory as async_session
from app.core.jobs.sec_xbrl_facts_ingestion import LOCK_ID, ingest_sec_xbrl_facts

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "xbrl"


@pytest.fixture
def mock_companyfacts_dir(monkeypatch):
    """Mock COMPANYFACTS_DIR to point to our test fixtures."""
    monkeypatch.setattr("app.core.jobs.sec_xbrl_facts_ingestion.settings.companyfacts_dir", str(FIXTURE_DIR))
    yield str(FIXTURE_DIR)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sec_xbrl_facts_success(mock_companyfacts_dir):
    # Ensure empty table before test
    async with async_session() as db:
        await db.execute(text("TRUNCATE sec_xbrl_facts"))
        await db.commit()

    # Run ingestion
    result = await ingest_sec_xbrl_facts(ciks=["0000001750", "0000320193"])
    
    assert "error" not in result
    assert result["files_processed"] == 2
    assert result["rows_inserted"] == 6  # 4 from 1750, 2 from 320193
    
    # Verify records in DB
    async with async_session() as db:
        query_res = await db.execute(text("SELECT cik, taxonomy, concept, val, val_text, accn FROM sec_xbrl_facts ORDER BY cik, concept, accn"))
        records = [dict(r._mapping) for r in query_res]
        assert len(records) == 6
        
        # Check AAR CORP
        ap_records = [r for r in records if r["concept"] == "AccountsPayable"]
        assert len(ap_records) == 3
        
        # Check restatements are preserved as separate rows
        assert len({r["accn"] for r in ap_records}) == 3
        
        # Check non-numeric
        name_records = [r for r in records if r["concept"] == "EntityRegistrantName"]
        assert len(name_records) == 1
        assert name_records[0]["val"] is None
        assert name_records[0]["val_text"] == "AAR CORP."
        
        # Check AAPL
        income_records = [r for r in records if r["concept"] == "NetIncomeLoss"]
        assert len(income_records) == 1
        assert income_records[0]["val"] == Decimal("94680000000")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sec_xbrl_facts_idempotent(mock_companyfacts_dir):
    # Run once
    async with async_session() as db:
        await db.execute(text("TRUNCATE sec_xbrl_facts"))
        await db.commit()

    result1 = await ingest_sec_xbrl_facts(ciks=["0000001750"])
    assert result1["rows_inserted"] == 4
    
    # Run twice
    result2 = await ingest_sec_xbrl_facts(ciks=["0000001750"])
    assert result2["rows_inserted"] == 0  # 0 new rows


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sec_xbrl_facts_lock_held(mock_companyfacts_dir):
    # Manually hold lock
    async with async_session() as db:
        await db.execute(text(f"SELECT pg_advisory_lock({LOCK_ID})"))
        
        try:
            # Try to run ingestion
            result = await ingest_sec_xbrl_facts(ciks=["0000001750"])
            assert result.get("error") == "lock held"
        finally:
            await db.execute(text(f"SELECT pg_advisory_unlock({LOCK_ID})"))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sec_xbrl_facts_dry_run(mock_companyfacts_dir):
    async with async_session() as db:
        await db.execute(text("TRUNCATE sec_xbrl_facts"))
        await db.commit()

    result = await ingest_sec_xbrl_facts(ciks=["0000001750"], dry_run=True)
    
    assert "error" not in result
    assert result["rows_inserted"] == 0
    assert result["rows_would_insert"] == 4
    
    # DB is still empty
    async with async_session() as db:
        count = await db.execute(text("SELECT COUNT(*) FROM sec_xbrl_facts"))
        assert count.scalar() == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sec_xbrl_facts_malformed(mock_companyfacts_dir):
    # Testing that malformed file is skipped gracefully
    # We pass the exact prefix to avoid normal globbing since malformed has a different structure
    result = await ingest_sec_xbrl_facts(ciks=["0000000000_malformed"])
    
    assert result["files_processed"] == 0
    assert result["files_failed"] == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sec_xbrl_facts_limit(mock_companyfacts_dir):
    result = await ingest_sec_xbrl_facts(limit=1)
    
    assert "error" not in result
    assert result["files_processed"] + result["files_failed"] == 1
