import logging
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import text

from app.core.config.settings import settings
from app.core.db.engine import async_session_factory as async_session
from app.core.jobs.sec_xbrl_facts_ingestion import LOCK_ID, ingest_sec_xbrl_facts

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "xbrl"

_log = logging.getLogger(__name__)


@pytest.fixture
def mock_companyfacts_dir(monkeypatch):
    """Mock COMPANYFACTS_DIR to point to our test fixtures."""
    monkeypatch.setattr("app.core.jobs.sec_xbrl_facts_ingestion.settings.companyfacts_dir", str(FIXTURE_DIR))
    yield str(FIXTURE_DIR)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sec_xbrl_facts_lock_lifecycle(mock_companyfacts_dir):
    """1. Advisory lock acquired + released across success path."""
    # This is implicitly tested if the test finishes and we can acquire it again
    async with async_session() as db:
        await db.execute(text("TRUNCATE sec_xbrl_facts"))
        await db.commit()

    result = await ingest_sec_xbrl_facts(ciks=["0000001750"])
    assert "error" not in result
    
    # Verify we can acquire the lock now (meaning it was released)
    async with async_session() as db:
        lock_res = await db.execute(text(f"SELECT pg_try_advisory_lock({LOCK_ID})"))
        assert lock_res.scalar() is True
        await db.execute(text(f"SELECT pg_advisory_unlock({LOCK_ID})"))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sec_xbrl_facts_lock_held(mock_companyfacts_dir):
    """2. Second concurrent invocation exits with 'lock held' log, zero writes."""
    
    # Ensure empty DB
    async with async_session() as db:
        await db.execute(text("TRUNCATE sec_xbrl_facts"))
        await db.commit()
    
    # Create a completely independent connection bypassing SQLAlchemy pool
    db_url = settings.database_url.replace("+asyncpg", "")
    conn = await asyncpg.connect(db_url)
    
    # Acquire lock in this independent connection
    await conn.execute(f"SELECT pg_advisory_lock({LOCK_ID})")
    
    try:
        # Try to run ingestion (will fail to acquire lock)
        result = await ingest_sec_xbrl_facts(ciks=["0000001750"])
        assert result.get("error") == "lock held", f"Expected 'lock held', got: {result}"
        
        # Zero writes
        async with async_session() as db:
            count = await db.scalar(text("SELECT COUNT(*) FROM sec_xbrl_facts"))
            assert count == 0
    finally:
        await conn.execute(f"SELECT pg_advisory_unlock({LOCK_ID})")
        await conn.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sec_xbrl_facts_fixture_aar(mock_companyfacts_dir):
    """3. Fixture AAR: inserts expected row count, correct cik, taxonomy, concept, accn."""
    async with async_session() as db:
        await db.execute(text("TRUNCATE sec_xbrl_facts"))
        await db.commit()

    result = await ingest_sec_xbrl_facts(ciks=["0000001750"])
    assert "error" not in result, f"Worker failed with: {result.get('error')}"
    assert result["rows_inserted"] == 4
    
    async with async_session() as db:
        res = await db.execute(text("SELECT cik, taxonomy, concept, accn FROM sec_xbrl_facts"))
        rows = res.all()
        assert len(rows) == 4
        for r in rows:
            assert r.cik == 1750
            assert r.taxonomy in ("dei", "us-gaap")
            assert r.concept in ("EntityRegistrantName", "AccountsPayable")
            assert r.accn is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sec_xbrl_facts_restatement(mock_companyfacts_dir):
    """4. Restatement: 10-K and 10-K/A for same produce two separate rows."""
    async with async_session() as db:
        await db.execute(text("TRUNCATE sec_xbrl_facts"))
        await db.commit()

    await ingest_sec_xbrl_facts(ciks=["0000001750"])
    
    async with async_session() as db:
        # AccountsPayable has 10-K and 10-K/A for 2011-05-31 in fixture
        res = await db.execute(text(
            "SELECT accn, form, val FROM sec_xbrl_facts WHERE concept='AccountsPayable' AND period_end='2011-05-31'"
        ))
        rows = res.all()
        assert len(rows) == 2
        forms = {r.form for r in rows}
        assert "10-K" in forms
        assert "10-K/A" in forms


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sec_xbrl_facts_unit_switching(mock_companyfacts_dir):
    """5. Unit switching: shares and USD observations for same concept both persist."""
    # Our fixture CIK0000320193.json has NetIncomeLoss (USD) and CommonStockSharesOutstanding (shares)
    async with async_session() as db:
        await db.execute(text("TRUNCATE sec_xbrl_facts"))
        await db.commit()

    result = await ingest_sec_xbrl_facts(ciks=["0000320193"])
    assert "error" not in result, f"Worker failed with: {result.get('error')}"
    
    async with async_session() as db:
        res = await db.execute(text("SELECT concept, unit FROM sec_xbrl_facts"))
        rows = res.all()
        units = {r.unit for r in rows}
        assert "USD" in units
        assert "shares" in units


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sec_xbrl_facts_idempotent(mock_companyfacts_dir):
    """6. Re-run idempotent: second run of same fixture inserts 0 additional rows."""
    async with async_session() as db:
        await db.execute(text("TRUNCATE sec_xbrl_facts"))
        await db.commit()

    await ingest_sec_xbrl_facts(ciks=["0000001750"])
    result2 = await ingest_sec_xbrl_facts(ciks=["0000001750"])
    assert result2["rows_inserted"] == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sec_xbrl_facts_period_start(mock_companyfacts_dir):
    """7. period_start populated when present in source, NULL when absent."""
    async with async_session() as db:
        await db.execute(text("TRUNCATE sec_xbrl_facts"))
        await db.commit()

    result = await ingest_sec_xbrl_facts(ciks=["0000320193"])
    assert "error" not in result, f"Worker failed with: {result.get('error')}"
    
    async with async_session() as db:
        # NetIncomeLoss has start date
        res_start = await db.execute(text("SELECT period_start FROM sec_xbrl_facts WHERE concept='NetIncomeLoss'"))
        assert res_start.scalar() is not None
        
        # Shares outstanding does not have start date
        res_no_start = await db.execute(text("SELECT period_start FROM sec_xbrl_facts WHERE concept='CommonStockSharesOutstanding'"))
        assert res_no_start.scalar() is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sec_xbrl_facts_non_numeric(mock_companyfacts_dir):
    """8. Non-numeric observation (e.g. dei:EntityRegistrantName) -> val IS NULL, val_text populated."""
    async with async_session() as db:
        await db.execute(text("TRUNCATE sec_xbrl_facts"))
        await db.commit()

    await ingest_sec_xbrl_facts(ciks=["0000001750"])
    
    async with async_session() as db:
        res = await db.execute(text("SELECT val, val_text FROM sec_xbrl_facts WHERE concept='EntityRegistrantName'"))
        row = res.one()
        assert row.val is None
        assert row.val_text == "AAR CORP."


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sec_xbrl_facts_malformed(mock_companyfacts_dir):
    """9. Malformed fixture: logged as failure, counter increments, worker continues."""
    result = await ingest_sec_xbrl_facts(ciks=["0000000000_malformed"])
    assert result["files_failed"] == 1
    assert result["files_processed"] == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sec_xbrl_facts_limit(mock_companyfacts_dir):
    """10. --limit 1 flag processes exactly one file."""
    result = await ingest_sec_xbrl_facts(limit=1)
    assert result["files_processed"] + result["files_failed"] == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sec_xbrl_facts_cik_subset(mock_companyfacts_dir):
    """11. --cik flag subsets correctly."""
    async with async_session() as db:
        await db.execute(text("TRUNCATE sec_xbrl_facts"))
        await db.commit()

    result = await ingest_sec_xbrl_facts(ciks=["0000001750"])
    assert result["files_processed"] == 1
    
    async with async_session() as db:
        count = await db.scalar(text("SELECT COUNT(DISTINCT cik) FROM sec_xbrl_facts"))
        assert count == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sec_xbrl_facts_dry_run(mock_companyfacts_dir):
    """12. --dry-run writes zero rows, returns summary with expected rows_would_insert."""
    async with async_session() as db:
        await db.execute(text("TRUNCATE sec_xbrl_facts"))
        await db.commit()

    result = await ingest_sec_xbrl_facts(ciks=["0000001750"], dry_run=True)
    assert result["rows_inserted"] == 0
    assert result["rows_would_insert"] == 4
    
    async with async_session() as db:
        count = await db.scalar(text("SELECT COUNT(*) FROM sec_xbrl_facts"))
        assert count == 0
