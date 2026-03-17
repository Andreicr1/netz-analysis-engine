---
status: pending
priority: p2
issue_id: 131
tags: [code-review, performance, backend]
---

# Problem Statement

After a bulk upsert in `benchmark_ingest.py`, the staleness check loop executes one `SELECT` query per allocation block to find the most recent `nav_date`. With 50+ blocks this adds 200ms or more of unnecessary latency on every ingest run, scaling linearly with block count.

# Findings

- `backend/app/domains/wealth/workers/benchmark_ingest.py` lines ~280-295 iterate over allocation blocks and issue individual SELECT queries to check staleness.
- Each query fetches the max `nav_date` for one `block_id`.
- At 50 blocks with ~4ms round-trip per query: ~200ms wasted per ingest.
- At 200 blocks (realistic institutional portfolio): ~800ms.
- The bulk upsert preceding this loop is already efficient; the staleness check undoes the performance benefit.

# Proposed Solutions

Replace the per-block loop with a single aggregated query using `GROUP BY`:

```python
from sqlalchemy import func, select

result = await db.execute(
    select(
        BenchmarkNav.allocation_block_id,
        func.max(BenchmarkNav.nav_date).label("latest_nav_date"),
    )
    .where(BenchmarkNav.allocation_block_id.in_(block_ids))
    .group_by(BenchmarkNav.allocation_block_id)
)
latest_by_block = {row.allocation_block_id: row.latest_nav_date for row in result}
```

Then replace the per-block lookup with a dict access: `latest_by_block.get(block_id)`.

This reduces N queries to 1 query regardless of block count.

# Technical Details

- **File:** `backend/app/domains/wealth/workers/benchmark_ingest.py` lines ~280-295
- **Current complexity:** O(N) queries where N = number of allocation blocks
- **Target complexity:** O(1) queries (single GROUP BY aggregation)
- **Estimated latency reduction:** 150-750ms depending on block count
- **Source:** performance-oracle
