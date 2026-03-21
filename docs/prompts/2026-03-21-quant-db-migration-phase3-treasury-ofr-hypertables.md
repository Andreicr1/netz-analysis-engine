# Phase 3 — Treasury + OFR Data → Hypertables + Ingestion Workers

**Status:** Ready
**Estimated scope:** ~400 lines new code + 2 migrations
**Risk:** Medium (new tables, new workers — but follows established patterns)

---

## Context

Two `quant_engine` services fetch external API data on-demand with no persistence:

1. **`fiscal_data_service.py`** — US Treasury API (rates, debt, auctions, FX, interest expense)
2. **`ofr_hedge_fund_service.py`** — OFR API (hedge fund leverage, AUM, strategy, repo volumes, risk scenarios)

These are called during macro analysis, portfolio evaluation, and content generation. Every call hits external APIs with 5 req/s rate limiting, adding latency and external dependency risk.

**Goal:** Create hypertables for both, add ingestion workers, and make the services read from DB by default with API as refresh source.

---

## Part A: Treasury Data

### Step 1: Migration — treasury_data Hypertable

Create migration `backend/app/core/db/migrations/versions/0036_treasury_data_hypertable.py`:

```python
"""Treasury fiscal data hypertable."""
# IMPORTANT: This migration requires autocommit mode for CREATE_HYPERTABLE.
# Pattern: same as migrations 0025-0031.

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0036"
down_revision = "0035"

def upgrade() -> None:
    # Create table
    op.create_table(
        "treasury_data",
        sa.Column("obs_date", sa.Date(), nullable=False),
        sa.Column("series_id", sa.String(80), nullable=False),
        sa.Column("value", sa.Numeric(18, 6), nullable=True),
        sa.Column("source", sa.String(40), nullable=False, server_default="treasury_api"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),  # auction details, etc.
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("obs_date", "series_id"),
    )

    # Convert to hypertable (must be in autocommit)
    conn = op.get_bind()
    conn.execute(text("COMMIT"))
    conn.execute(text(
        "SELECT create_hypertable('treasury_data', 'obs_date', "
        "chunk_time_interval => INTERVAL '1 month', "
        "if_not_exists => TRUE, "
        "migrate_data => TRUE)"
    ))
    conn.execute(text("BEGIN"))

    # Compression
    conn = op.get_bind()
    conn.execute(text("COMMIT"))
    conn.execute(text(
        "ALTER TABLE treasury_data SET ("
        "timescaledb.compress, "
        "timescaledb.compress_segmentby = 'series_id', "
        "timescaledb.compress_orderby = 'obs_date DESC')"
    ))
    conn.execute(text(
        "SELECT add_compression_policy('treasury_data', INTERVAL '3 months', if_not_exists => TRUE)"
    ))
    conn.execute(text("BEGIN"))

def downgrade() -> None:
    op.drop_table("treasury_data")
```

**Note:** Follow the exact autocommit pattern used in existing hypertable migrations (0025-0031). Check `0025_convert_sec_13f_holdings_to_hypertable.py` for the canonical pattern.

### Step 2: ORM Model

File: `backend/app/shared/models.py`

Add `TreasuryData` model (global table, no RLS, no `organization_id`):

```python
class TreasuryData(Base):
    __tablename__ = "treasury_data"

    obs_date: Mapped[date] = mapped_column(Date, primary_key=True)
    series_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    source: Mapped[str] = mapped_column(String(40), server_default="treasury_api")
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
```

### Step 3: Treasury Ingestion Worker

Create: `backend/app/domains/wealth/workers/treasury_ingestion.py`

```python
"""Treasury data ingestion worker — fetches rates, debt, auctions daily.

Advisory lock ID = 900_011.
"""
import asyncio
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import structlog
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db.engine import async_session_factory as async_session
from app.shared.models import TreasuryData
from quant_engine.fiscal_data_service import FiscalDataService

logger = structlog.get_logger()
TREASURY_LOCK_ID = 900_011


async def run_treasury_ingestion(lookback_days: int = 365) -> dict:
    """Fetch treasury data and upsert to treasury_data hypertable."""
    async with async_session() as db:
        lock = await db.execute(text(f"SELECT pg_try_advisory_lock({TREASURY_LOCK_ID})"))
        if not lock.scalar():
            return {"status": "skipped", "reason": "lock_held"}

        try:
            service = FiscalDataService()
            today = date.today()
            start = today - timedelta(days=lookback_days)

            rows = []

            # 1. Treasury rates (daily, most important)
            try:
                rates = await service.fetch_treasury_rates(
                    start_date=start.isoformat(),
                    end_date=today.isoformat(),
                )
                for r in rates:
                    obs_date = date.fromisoformat(r["record_date"])
                    for maturity_key in ["1_month", "3_month", "6_month", "1_year",
                                         "2_year", "3_year", "5_year", "7_year",
                                         "10_year", "20_year", "30_year"]:
                        val = r.get(f"avg_interest_rate_{maturity_key}")
                        if val is not None:
                            try:
                                rows.append({
                                    "obs_date": obs_date,
                                    "series_id": f"TREASURY_{maturity_key.upper()}",
                                    "value": Decimal(str(val)),
                                    "source": "treasury_api",
                                })
                            except (InvalidOperation, ValueError):
                                continue
            except Exception as e:
                logger.warning("treasury_rates_fetch_failed", error=str(e))

            # 2. Debt snapshot (daily)
            try:
                debt = await service.fetch_debt_to_penny(
                    start_date=start.isoformat(),
                    end_date=today.isoformat(),
                )
                for d in debt:
                    obs_date = date.fromisoformat(d["record_date"])
                    for key in ["tot_pub_debt_out_amt", "intragov_hold_amt", "debt_held_public_amt"]:
                        val = d.get(key)
                        if val is not None:
                            try:
                                rows.append({
                                    "obs_date": obs_date,
                                    "series_id": f"DEBT_{key.upper()}",
                                    "value": Decimal(str(val)),
                                    "source": "treasury_api",
                                })
                            except (InvalidOperation, ValueError):
                                continue
            except Exception as e:
                logger.warning("treasury_debt_fetch_failed", error=str(e))

            # 3. Auction results (periodic)
            try:
                auctions = await service.fetch_treasury_auctions(
                    start_date=start.isoformat(),
                    end_date=today.isoformat(),
                )
                for a in auctions:
                    obs_date = date.fromisoformat(a.get("auction_date", a.get("record_date", "")))
                    high_yield = a.get("high_yield")
                    if high_yield is not None:
                        security_type = a.get("security_type", "unknown")
                        security_term = a.get("security_term", "unknown")
                        try:
                            rows.append({
                                "obs_date": obs_date,
                                "series_id": f"AUCTION_{security_type}_{security_term}".upper().replace(" ", "_"),
                                "value": Decimal(str(high_yield)),
                                "source": "treasury_api",
                                "metadata_json": {
                                    "security_type": security_type,
                                    "security_term": security_term,
                                    "bid_to_cover": a.get("bid_to_cover_ratio"),
                                },
                            })
                        except (InvalidOperation, ValueError):
                            continue
            except Exception as e:
                logger.warning("treasury_auctions_fetch_failed", error=str(e))

            # Upsert all rows
            if rows:
                chunk_size = 2000
                for i in range(0, len(rows), chunk_size):
                    chunk = rows[i:i + chunk_size]
                    stmt = pg_insert(TreasuryData).values(chunk)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["obs_date", "series_id"],
                        set_={"value": stmt.excluded.value, "source": stmt.excluded.source,
                               "metadata_json": stmt.excluded.metadata_json},
                    )
                    await db.execute(stmt)
                await db.commit()

            logger.info("Treasury ingestion complete", rows_upserted=len(rows))
            return {"status": "completed", "rows": len(rows)}

        finally:
            await db.execute(text(f"SELECT pg_advisory_unlock({TREASURY_LOCK_ID})"))
```

**Important:** Adapt field names based on the actual Treasury API response schema. Read `backend/quant_engine/fiscal_data_service.py` carefully to understand the exact response format. The code above is a template — validate against the actual `_fetch_paginated()` return values.

---

## Part B: OFR Hedge Fund Data

### Step 4: Migration — ofr_hedge_fund_data Hypertable

Create migration `backend/app/core/db/migrations/versions/0037_ofr_hedge_fund_hypertable.py`:

Same autocommit pattern. Table:

```sql
CREATE TABLE ofr_hedge_fund_data (
    obs_date       DATE NOT NULL,
    series_id      VARCHAR(80) NOT NULL,
    value          NUMERIC(18, 6),
    source         VARCHAR(40) NOT NULL DEFAULT 'ofr_api',
    metadata_json  JSONB,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (obs_date, series_id)
);

-- Hypertable: 3-month chunks, segment by series_id
-- Compression: 6 months (data is quarterly/weekly, less frequent)
```

### Step 5: ORM Model

File: `backend/app/shared/models.py`

```python
class OfrHedgeFundData(Base):
    __tablename__ = "ofr_hedge_fund_data"

    obs_date: Mapped[date] = mapped_column(Date, primary_key=True)
    series_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    source: Mapped[str] = mapped_column(String(40), server_default="ofr_api")
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
```

### Step 6: OFR Ingestion Worker

Create: `backend/app/domains/wealth/workers/ofr_ingestion.py`

Advisory lock ID = 900_012. Fetches weekly (repo volumes are daily, rest quarterly).

Follow same pattern as treasury worker. Key series to persist:
- `OFR_LEVERAGE_{SIZE_COHORT}` — leverage by fund size
- `OFR_INDUSTRY_GAV`, `OFR_INDUSTRY_NAV`, `OFR_INDUSTRY_COUNT` — AUM
- `OFR_STRATEGY_{NAME}_AUM` — per strategy
- `OFR_REPO_VOLUME` — FICC repo (daily, most valuable signal)
- `OFR_CDS_P5`, `OFR_CDS_P50` — stress scenarios

**Read `backend/quant_engine/ofr_hedge_fund_service.py` carefully** to map each method's return format to series_id naming.

### Step 7: Register Workers

Add both workers to the worker registry/trigger mechanism (however the app currently triggers workers — check `backend/app/domains/wealth/routes/` for worker trigger patterns, likely admin endpoints).

### Step 8: Create DB Reader Functions

Add helper functions that read from the new hypertables instead of calling APIs:

File: `backend/quant_engine/fiscal_data_service.py` — add:

```python
async def get_treasury_rates_from_db(
    db: AsyncSession,
    maturity: str = "10_year",
    lookback_days: int = 252,
) -> list[dict]:
    """Read treasury rates from treasury_data hypertable."""
    from app.shared.models import TreasuryData
    stmt = (
        select(TreasuryData.obs_date, TreasuryData.value)
        .where(
            TreasuryData.series_id == f"TREASURY_{maturity.upper()}",
            TreasuryData.obs_date >= date.today() - timedelta(days=lookback_days),
        )
        .order_by(TreasuryData.obs_date.desc())
    )
    result = await db.execute(stmt)
    return [{"date": str(r.obs_date), "value": float(r.value)} for r in result.all()]
```

Similarly for OFR. These are the functions that callers should use instead of the API methods.

### Step 9: Tests

- Add tests for both workers (seed API responses with httpx mock, verify DB rows)
- Add tests for DB reader functions
- Verify existing quant_engine tests still pass

## Validation

```bash
make check
```

---

## Files to Create/Modify

| File | Action |
|---|---|
| `backend/app/core/db/migrations/versions/0036_treasury_data_hypertable.py` | New migration |
| `backend/app/core/db/migrations/versions/0037_ofr_hedge_fund_hypertable.py` | New migration |
| `backend/app/shared/models.py` | Add `TreasuryData`, `OfrHedgeFundData` models |
| `backend/app/domains/wealth/workers/treasury_ingestion.py` | New worker |
| `backend/app/domains/wealth/workers/ofr_ingestion.py` | New worker |
| `backend/quant_engine/fiscal_data_service.py` | Add DB reader functions |
| `backend/quant_engine/ofr_hedge_fund_service.py` | Add DB reader functions |
