# E2E Deep Review — Post-Optimization Comparison Run

> Paste this prompt into a fresh Claude Code session to run the E2E comparison.

---

## Context

Phases 1–6 of the Deep Review Optimization are implemented. This session runs the same deal used in the baseline (`docs/reference/deep-review-baseline-metrics-2026-03-20.md`) to produce a post-optimization comparison.

Read these documents first:

1. `docs/reference/deep-review-baseline-metrics-2026-03-20.md` — baseline metrics (pre-optimization)
2. `docs/reference/deep-review-optimization-plan-2026-03-20.md` — what changed
3. `docs/plans/2026-03-20-deep-review-optimization-backlog.md` — phase details

## Baseline Deal

| Parameter | Value |
|---|---|
| **Deal** | BridgeInvest Credit Fund V |
| **Deal ID** | `66b1ed07-8274-4d96-806f-1515bb0e148b` |
| **Fund ID** | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` |
| **Org ID** | `70f19993-b0d9-42ff-b3c7-cf2bb0728cec` |

## Pre-Flight Checks

Before running the pipeline, verify the environment:

### 1. Backend starts

```bash
make up  # docker-compose (PG + Redis)
make serve  # uvicorn on :8000
```

Hit health check: `curl http://localhost:8000/api/v1/admin/health`

### 2. LLM connectivity

The baseline used `qwen/qwen3-14b` via LM Studio (local). Confirm LM Studio is running and the model is loaded, or switch to OpenAI if available (set `OPENAI_API_KEY`).

### 3. Database state

Verify the deal exists and has indexed chunks in pgvector:

```python
# Run in a Python shell with backend on PYTHONPATH
import asyncio
from app.core.db.session import async_session_factory
from sqlalchemy import text

async def check():
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.current_organization_id = '70f19993-b0d9-42ff-b3c7-cf2bb0728cec'"))

        # Check deal exists
        r = await db.execute(text(
            "SELECT id, deal_name FROM pipeline_deals WHERE id = '66b1ed07-8274-4d96-806f-1515bb0e148b'"
        ))
        deal = r.first()
        print(f"Deal: {deal}")

        # Check chunks indexed
        r = await db.execute(text(
            "SELECT COUNT(*) FROM vector_chunks WHERE organization_id = '70f19993-b0d9-42ff-b3c7-cf2bb0728cec'"
        ))
        count = r.scalar()
        print(f"Chunks indexed: {count}")

asyncio.run(check())
```

If chunks = 0, the pipeline has nothing to retrieve. Do NOT proceed.

### 4. Reranker status

Check if the CrossEncoder reranker works:

```python
from vertical_engines.credit.retrieval.evidence import _rerank_chunks
# If this import fails or throws meta tensor error, reranker is still broken.
# Document this in the comparison — it affects signal differentiation.
```

## Run the Pipeline

### Option A: Via API (recommended — exercises full stack)

```bash
curl -X POST http://localhost:8000/api/v1/funds/{fund_id}/pipeline/deals/66b1ed07-8274-4d96-806f-1515bb0e148b/deep-review-v4 \
  -H "Content-Type: application/json" \
  -H "X-DEV-ACTOR: e2e-comparison" \
  -d '{"actor_id": "e2e-comparison", "force": true}'
```

Replace `{fund_id}` with `a1b2c3d4-e5f6-7890-abcd-ef1234567890`.

Note: `force: true` bypasses artifact cache to ensure a fresh run.

### Option B: Via Python (direct, better for debugging)

```python
from sqlalchemy.orm import Session
from app.core.db.session import sync_session_factory
from vertical_engines.credit.deep_review import run_deal_deep_review_v4
import uuid

db: Session = sync_session_factory()
# Set RLS context
from sqlalchemy import text
db.execute(text("SET LOCAL app.current_organization_id = '70f19993-b0d9-42ff-b3c7-cf2bb0728cec'"))

result = run_deal_deep_review_v4(
    db,
    fund_id=uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890"),
    deal_id=uuid.UUID("66b1ed07-8274-4d96-806f-1515bb0e148b"),
    organization_id=uuid.UUID("70f19993-b0d9-42ff-b3c7-cf2bb0728cec"),
    actor_id="e2e-comparison",
    force=True,
    full_mode=False,
)
```

### Monitor logs

Watch for these key log events during the run:

```
ic_grade_retrieval.start         — retrieval begins
ic_chapter_evidence.complete     — per-chapter evidence stats + coverage status
pre_classify_concordance.*       — NEW: Phase 7 concordance logging
rag_empty.no_indexed_chunks      — NEW: Phase 6 (replaces fallback_blob_download)
deep_review.v4.pre_classified    — pre-classifier result
deep_review.v4.instrument_classified — Stage 3 result
```

## Collect Metrics

After the run completes, extract these metrics from the `result` dict and logs:

### Retrieval Metrics

```python
retrieval_audit = result.get("retrieval_audit", {})
saturation = result.get("saturation_report", {})
chapter_evidence = result.get("chapter_evidence", {})

print("=== Retrieval ===")
print(f"Policy: {retrieval_audit.get('retrieval_policy')}")
print(f"Total chapters: {len(chapter_evidence)}")
print(f"Corpus chars: {len(result.get('corpus', ''))}")
print(f"Gaps: {saturation.get('gap_count')}")
print()

print("=== Per-Chapter Evidence ===")
for ch_key, ch in chapter_evidence.items():
    signal = ch.get("retrieval_signal", {})
    print(f"  {ch_key}: chunks={ch['stats']['chunk_count']}, "
          f"docs={ch['stats']['unique_docs']}, "
          f"coverage={ch['coverage_status']}, "
          f"confidence={signal.get('confidence', 'N/A')}")
```

### Memo & Confidence Metrics

```python
print("=== Memo Output ===")
print(f"Chapters: {result.get('chapters_generated')}")
print(f"Memo chars: {result.get('memo_chars')}")
print(f"Citations: {result.get('citation_count')}")
print(f"Recommendation: {result.get('recommendation')}")
print()

print("=== Confidence ===")
print(f"Confidence score: {result.get('confidence_score')}")
print(f"Underwriting score: {result.get('underwriting_score')}")
print(f"Underwriting level: {result.get('underwriting_level')}")
print(f"IC gate: {result.get('ic_gate')}")
print(f"Fatal flaws: {result.get('fatal_flaws')}")
print(f"Instrument type: {result.get('instrument_type')}")
```

### Phase 7 Concordance

```python
print("=== Phase 7 Concordance ===")
print(f"Pre-classifier: {result.get('pre_instrument_type', 'N/A')}")
print(f"Stage 3 classified: {result.get('instrument_type')}")
match = result.get('pre_instrument_type') == result.get('instrument_type')
print(f"Concordance: {'MATCH' if match else 'MISMATCH'}")
```

## Write Comparison Report

Create `docs/reference/deep-review-post-optimization-metrics-2026-03-20.md` with:

1. **Run Configuration** — same format as baseline, note any differences (LLM model, reranker status, corpus budget)

2. **Side-by-Side Comparison Table**

```markdown
| Metric | Baseline | Post-Optimization | Delta |
|---|---|---|---|
| Coverage status distribution | 14/14 CONTESTED | ? | ? |
| Confidence score | 0.182 | ? | ? |
| Underwriting score | 55 | ? | ? |
| Total memo chars | 38,879 | ? | ? |
| Citations | 55 | ? | ? |
| Fatal flaws | 1 (UNKNOWN instrument) | ? | ? |
| IC gate | CONDITIONAL | ? | ? |
| Instrument type | UNKNOWN | ? | ? |
| Pre-classifier concordance | N/A (no logging) | MATCH/MISMATCH | NEW |
| Legacy blob fallback calls | possible | 0 (removed) | Phase 6 |
| Search tier (legal chapters) | (200, 300) static | (100, 150) → expand if LOW | Phase 5 |
| Doc-type filters | present (dead) | removed | Phase 4 |
| Confidence Block 2 source | count-based proxy | RetrievalSignal | Phase 3 |
| Policy loader | Azure Search (dead) | ConfigService | Phase 3B |
```

3. **Per-Chapter Evidence Comparison** — side-by-side with baseline table from `deep-review-baseline-metrics-2026-03-20.md`

4. **Signal Differentiation Analysis** — are chapters getting different confidence signals (HIGH/MODERATE/AMBIGUOUS/LOW) or is everything still CONTESTED/AMBIGUOUS? If uniform, document that reranker is still broken.

5. **Interpretation** — what changed meaningfully vs what's blocked by the reranker. Separate "optimization working as designed" from "waiting on reranker fix".

## Important Notes

- **Do NOT modify any code during this session.** This is a read-only comparison run.
- **If the reranker is still broken**, document it prominently. The comparison will show Phase 1-3 infrastructure working correctly but without signal differentiation. This is expected.
- **If the pipeline fails**, capture the error, investigate root cause, and document it. Do not retry blindly.
- **Compare apples to apples**: same deal, same DB, same corpus budget. If any parameter differs from baseline, note it in the report.
