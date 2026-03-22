# Phase 5A — Engine Activation (fee_drag + sponsor + underwriting Integration)

**Status:** Ready
**Estimated scope:** ~350 lines changed
**Risk:** Medium (cross-package integrations, import-linter enforcement)
**Prerequisite:** None

---

## Context

Three vertical engine packages exist with tested code but are **never called from any consumer**:

1. **`fee_drag/`** — fee drag ratio + efficiency analysis (wealth). Never called.
2. **`sponsor/`** — PE sponsor enrichment (credit). Never called.
3. **`underwriting/`** — underwriting artifact generator (credit). Never called.

This session wires each into its intended consumers. **Critical:** Run `make architecture` after every integration to verify import-linter contracts.

---

## Error Contracts (Read Before Coding)

| Engine | Contract | Caller Pattern |
|--------|----------|---------------|
| `fee_drag/service.py` | **Never-raises** (wealth pattern) | No try/except needed. Check for empty results. |
| `sponsor/service.py` | **Never-raises** — returns `_default_output()` with `status: 'NOT_ASSESSED'` | No try/except needed. Check `result["status"]` for UI handling. |
| `underwriting/service.py` | **Raises-on-failure** (transactional) | Wrap in try/except. On failure, log + continue. |

**Import direction:** Call ONLY `service.py` entry points. Never import helpers/models from one package into another.

---

## Task 1: Integrate `fee_drag/` into DD Report + Screener

### Step 1.1 — DD Report integration

Read `backend/vertical_engines/wealth/dd_report/dd_report_engine.py`. Find the evidence gathering section (look for `_build_evidence()` or `build_evidence_pack()` around line ~275-311).

After risk metrics are gathered, add fee drag computation:

```python
from vertical_engines.wealth.fee_drag.service import FeeDragService

# Inside evidence gathering
fee_drag_service = FeeDragService(fee_drag_threshold=0.50)
fee_drag_result = fee_drag_service.compute(instruments, weights)
# Add to evidence pack
evidence.scoring_data["fee_drag"] = fee_drag_result
```

**Chapter integration:** The fees/expenses chapter of the DD report should reference `evidence.scoring_data["fee_drag"]` to render fee drag ratio, efficiency score, and peer comparison as a metric card.

### Step 1.2 — Screener integration

Read `backend/vertical_engines/wealth/screener/service.py`. Find Layer 3 quant scoring (look for `composite_score()` around line ~135).

Add fee drag to the metrics dict and weights:

```python
from vertical_engines.wealth.fee_drag.service import FeeDragService

# After Layer 3 scoring
fee_drag_svc = FeeDragService()
fee_drag = fee_drag_svc.compute(instrument_data)
metrics_dict["fee_drag_ratio"] = fee_drag.ratio
metrics_dict["fee_efficiency_score"] = fee_drag.efficiency_score
```

### Step 1.3 — Schema extension

In `backend/app/domains/wealth/schemas/screener.py`, add:

```python
fee_drag_ratio: float | None = None
fee_efficiency_score: float | None = None
```

### Step 1.4 — Frontend screener columns

In `frontends/wealth/src/routes/(team)/screener/+page.svelte`, add two sortable columns:
- "Fee Drag" → `fee_drag_ratio` (format as percentage)
- "Fee Efficiency" → `fee_efficiency_score` (format as number 0-100)

### Step 1.5 — Filter extension

In screener query builder, add filter parameters:
```python
fee_drag_min: float | None = Query(None)
fee_drag_max: float | None = Query(None)
```

---

## Task 2: Integrate `sponsor/` into Deal Context + IC Memo

### Step 2.1 — Deal context enrichment

Read `backend/app/domains/credit/routes/deals.py` (or `backend/app/domains/credit/deals/routes/deals.py`). Find the deal creation endpoint (POST, lines ~26-91).

After deal creation, call sponsor enrichment:

```python
from vertical_engines.credit.sponsor.service import analyze_sponsor

# After deal is created
sponsor_result = await asyncio.to_thread(analyze_sponsor, deal_context)
# sponsor/service is NEVER-RAISES — returns _default_output() on failure
if sponsor_result.get("status") != "NOT_ASSESSED":
    deal.deal_context["sponsor_enrichment"] = sponsor_result
    # Update deal in DB
```

**No try/except needed** — `analyze_sponsor()` is never-raises contract.

### Step 2.2 — IC Memo evidence

Read `vertical_engines/credit/memo/` to find the sponsor chapter. The sponsor chapter template should reference `deal_context.sponsor_enrichment`:

```python
# In memo chapter generation, pass sponsor data as evidence
if deal_context.get("sponsor_enrichment"):
    evidence["sponsor"] = deal_context["sponsor_enrichment"]
```

Find the evidence pack builder (`vertical_engines/credit/memo/evidence_pack.py`) and ensure sponsor enrichment is included.

### Step 2.3 — Graceful degradation

If sponsor data is unavailable:
- Deal creation proceeds without it (no blocking)
- IC Memo sponsor chapter shows "Sponsor data not available" instead of empty
- Frontend deal detail shows "Not Assessed" badge

---

## Task 3: Integrate `underwriting/` into Pipeline + On-Demand Endpoint

### Step 3.1 — Pipeline auto-generation

Read `vertical_engines/credit/pipeline/service.py`. Find where qualification completes successfully. After qualification, call underwriting:

```python
from vertical_engines.credit.underwriting.service import generate_underwriting_artifact

# After qualification succeeds
try:
    artifact = await asyncio.to_thread(generate_underwriting_artifact, deal_context)
    # persist_underwriting_artifact uses SYNC Session — already in to_thread
    await asyncio.to_thread(persist_underwriting_artifact, artifact, deal_id)
except Exception as e:
    logger.warning(f"Underwriting artifact generation failed: {e}")
    # Qualification still succeeds — underwriting is best-effort
```

**underwriting/service is RAISES-ON-FAILURE** — MUST wrap in try/except.

### Step 3.2 — On-demand endpoint

In `backend/app/domains/credit/routes/deals.py`, add:

```python
@router.post(
    "/pipeline/deals/{deal_id}/underwriting-artifact",
    response_model=UnderwritingArtifactResponse,
    status_code=201,
    summary="Generate or regenerate underwriting artifact",
)
async def generate_underwriting(
    deal_id: UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    _actor: dict = Depends(require_role(Role.INVESTMENT_TEAM)),
):
```

### Step 3.3 — Schema

```python
class UnderwritingArtifactResponse(BaseModel):
    deal_id: UUID
    artifact_id: UUID
    term_sheet: dict | None = None
    credit_summary: str | None = None
    risk_matrix: dict | None = None
    created_at: datetime
    pdf_url: str | None = None
```

### Step 3.4 — Frontend

In `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte`, add an "Underwriting Artifact" section:
- Show artifact if it exists (term sheet, risk matrix)
- "Regenerate" button → POST endpoint
- Download PDF button if `pdf_url` is set

---

## Task 4: Verify Import Architecture

After ALL integrations, run:

```bash
make architecture
```

This runs import-linter. Verify:
1. DD report → `fee_drag.service` ✓ (allowed: different wealth packages)
2. Screener → `fee_drag.service` ✓
3. Credit deals → `sponsor.service` ✓ (app.domains.credit → vertical_engines.credit)
4. Credit memo → `sponsor.service` ✓
5. Credit pipeline → `underwriting.service` ✓
6. No reverse imports (helpers/models importing service)

---

## Files Changed

| File | Change |
|------|--------|
| `vertical_engines/wealth/dd_report/dd_report_engine.py` | Call fee_drag.service in evidence gathering |
| `vertical_engines/wealth/screener/service.py` | Call fee_drag.service in Layer 3 |
| `backend/app/domains/wealth/schemas/screener.py` | Add fee_drag fields |
| `frontends/wealth/src/routes/(team)/screener/+page.svelte` | Add fee_drag columns |
| `backend/app/domains/credit/routes/deals.py` (or deals/routes/) | Sponsor enrichment + underwriting endpoint |
| `vertical_engines/credit/memo/evidence_pack.py` | Include sponsor evidence |
| `vertical_engines/credit/pipeline/service.py` | Call underwriting after qualification |
| `backend/app/domains/credit/schemas/deals.py` | Add UnderwritingArtifactResponse |
| `frontends/credit/.../pipeline/[dealId]/+page.svelte` | Add underwriting section |

## Acceptance Criteria

- [ ] DD Report fees chapter includes fee drag ratio + efficiency score
- [ ] Screener results include fee_drag_ratio sortable column
- [ ] Screener filters support fee_drag_min/max
- [ ] New deal creation auto-enriches with sponsor data
- [ ] IC Memo sponsor chapter uses enriched data
- [ ] Qualification auto-generates underwriting artifact
- [ ] `POST /deals/{deal_id}/underwriting-artifact` regenerates on demand
- [ ] Deal detail page shows artifact with download
- [ ] All graceful degradation works (missing data doesn't block)
- [ ] `make architecture` passes (import-linter)
- [ ] `make check` passes

## Gotchas

- `sponsor/service.py` is **never-raises** — NO try/except needed
- `underwriting/service.py` is **raises-on-failure** — MUST try/except
- `persist_underwriting_artifact()` uses **sync Session** — call via `asyncio.to_thread()`
- `persist_underwriting_artifact()` deactivates prior versions before creating new (lines ~98-106)
- Import direction: ONLY call `service.py` entry points — never import models/helpers cross-package
- Run `make architecture` after EVERY integration to catch import violations
- Fee drag service method may be `.compute()` or `.compute_fee_drag()` — read the service file first
