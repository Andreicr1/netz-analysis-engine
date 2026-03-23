---
title: "Monolith to Modular Package with Library Migration"
category: architecture-patterns
tags: [refactoring, modular-package, library-migration, edgartools, sec-edgar, lazy-imports, rate-limiting, thread-safety, async-to-thread]
module: vertical_engines/credit/edgar
symptom: "1561 LOC hand-rolled HTTP client (ic_edgar_engine.py) with manual XBRL parsing, point-in-time metrics only, no structured financials or insider trading signals"
root_cause: "Original integration built before edgartools library matured. Manual HTTP/XBRL approach could not access structured financials, Form 4 data, or automatic ratio calculation. Single-file monolith was unmaintainable."
---

# Monolith to Modular Package with Library Migration

**Date:** 2026-03-15
**PRs:** #4 (Phase A — quant decoupling), #5 (Phase B — EDGAR upgrade)
**Impact:** Replaced 1561 LOC monolith with 8-module package backed by `edgartools` library

## Problem

`ic_edgar_engine.py` was a 1561-line monolithic module containing hand-rolled HTTP requests, XBRL parsing, rate limiting, CIK resolution (4-tier blob index), multi-entity orchestration, and context serialization — all in a single file. It produced only point-in-time XBRL concept extractions, missing structured multi-period financial statements, Form 4 insider trading signals, and computed financial ratios.

## Solution: 8 Patterns

### 1. Package Structure — Single-Responsibility Split

```
backend/vertical_engines/credit/edgar/
  __init__.py           (~52 LOC)  — PEP 562 lazy imports, public API
  models.py             (~109 LOC) — dataclasses + enums, zero sibling imports
  cik_resolver.py       (~308 LOC) — hybrid CIK resolution
  service.py            (~386 LOC) — orchestration
  financials.py         (~466 LOC) — XBRL extraction, BDC/REIT + AM metrics
  going_concern.py      (~169 LOC) — 3-tier classification
  insider_signals.py    (~315 LOC) — Form 4 signal detection
  entity_extraction.py  (~235 LOC) — entity name extraction + dedup
  context_serializer.py (~385 LOC) — LLM context with attribution
```

**Dependency DAG:** `models.py` is the leaf (zero intra-package imports). All domain modules import only from `models.py`. `service.py` is the sole orchestrator that fans out to all domain modules. `context_serializer.py` works on plain dicts (fully decoupled from models).

### 2. Type-Safe Lazy Imports (PEP 562)

```python
# __init__.py
from typing import TYPE_CHECKING, Any

from vertical_engines.credit.edgar.entity_extraction import extract_searchable_entities

if TYPE_CHECKING:
    from vertical_engines.credit.edgar.service import (
        fetch_edgar_data as fetch_edgar_data,
    )

def __getattr__(name: str) -> Any:
    if name == "fetch_edgar_data":
        from vertical_engines.credit.edgar.service import fetch_edgar_data
        return fetch_edgar_data
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

**Why:** `edgartools` pulls `pandas` + `pyarrow` (~100MB). Lazy imports prevent loading at app startup. The `TYPE_CHECKING` block gives mypy/IDE full type visibility without runtime cost.

### 3. Hybrid Resolution with Confidence Scoring

```
Tier 1: Company(ticker)      → confidence=1.0
Tier 2: find(name) + fuzz≥85% → confidence=fuzz.ratio/100
Tier 3: blob_light normalize  → confidence=0.9
Tier 4: blob_heavy normalize  → confidence=0.8
```

`CikResolution` dataclass carries `method` + `confidence` through the pipeline. Low confidence (<0.7) triggers a warning. Heavy normalization strips `inc/llc/corp/ltd` but NOT `Fund/Capital/Partners` (meaningful for private credit).

### 4. Non-Fatal Design — Never-Raises Contract

```python
def fetch_edgar_data(...) -> dict[str, Any]:
    """Never raises. All errors in result['warnings']."""
    warnings: list[str] = []
    try:
        result.financials = extract_structured_financials(company)
    except Exception as exc:
        warnings.append(f"Financials failed: {type(exc).__name__}")
        logger.warning("financials_failed", exc_info=True)  # ops-facing traceback
```

Each sub-operation (financials, going concern, insider signals) is independently wrapped. Failure in one does NOT prevent others. `exc_info=True` gives full traceback in structlog without exposing to callers.

### 5. Thread-Safe Parallel Entity Processing

```python
def fetch_edgar_multi_entity(entities, ...):
    # Phase 1: Sequential CIK resolution (for dedup)
    resolved = []
    for entity in entities:
        cik = resolve_cik(entity["name"], entity.get("ticker"))
        if cik.cik in seen_ciks: continue  # dedup
        resolved.append((entity, cik.cik))

    # Phase 2: Parallel fetch (skip re-resolution via pre_resolved_cik)
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="edgar") as pool:
        futures = {pool.submit(_fetch_one, e, cik): e for e, cik in resolved}
```

**Critical:** ThreadPoolExecutor created INSIDE the function (not module level). `max_workers=3` respects SEC 10 req/s. Pre-resolved CIK avoids redundant resolution in Phase 2.

### 6. Dict Return at API Boundary

Internal code uses typed dataclasses (`EdgarEntityResult`, `FinancialStatements`). The `_to_dict()` helper converts via `dataclasses.asdict()` at the public API surface, preserving backward compatibility with `r.get("status")` dict-style access in consumers.

### 7. Redis Distributed Rate Limiter

```python
def _check_distributed_rate(max_per_second: int = 8) -> None:
    key = f"edgar:rate:{int(time.time())}"
    count = r.incr(key)  # atomic — no race conditions
    if count == 1: r.expire(key, 2)
    if count > max_per_second: time.sleep(1.0)
```

Sliding window (1 key/second, TTL=2s). `max=8` leaves headroom below SEC's 10/s. Entire function wrapped in bare `except` — Redis unavailability never blocks EDGAR.

### 8. Going Concern Negation Detection

```python
_NEGATION_PHRASES = ["no substantial doubt", "doubt has been resolved", ...]
_MITIGATION_PHRASES = ["plans to alleviate", "management believes", ...]

def _classify_context(text_window: str) -> GoingConcernVerdict:
    if any(neg in text_window for neg in _NEGATION_PHRASES): return NONE
    if any(mit in text_window for mit in _MITIGATION_PHRASES): return MITIGATED
    return CONFIRMED
```

Two-pass scan: auditor report section first (15KB window, confidence 0.9), then broad scan (200KB, confidence 0.7). Context window is 400 chars around the keyword match.

## Bugs Caught During Review

| Bug | How Caught | Fix |
|-----|-----------|-----|
| `_check_net_selling` ignored `window_days` parameter | 3 review agents flagged independently | Added date window filtering |
| `filing.text()` fallback in 10b5-1 detection: ~30 extra HTTP req/entity | Performance oracle | Removed text fallback, kept checkbox + footnote |
| `TokenBucketRateLimiter.acquire()` not thread-safe | Security sentinel | Added `threading.Lock` |
| Double `parse_fred_value()` call per observation | Python reviewer | Walrus operator |
| CIK fuzzy threshold 70% matched wrong entities | Security sentinel | Raised to 85% |
| `credit_stress` grading: score 10 → "mild" instead of "moderate" | Architecture reviewer | Fixed boundary from 14 to 9 |
| Redis rate limiter in plan but not in code | 3 agents flagged | Implemented sliding window |
| Dead `EdgarMultiEntityResult` + 4 unpopulated fields | Simplicity reviewer | Deleted |

## Prevention Checklist

```
[ ] REQUEST VOLUME — profile old vs new request count per operation
[ ] PARAMETER CONTRACTS — every parameter has a test proving it affects output
[ ] TYPE SAFETY — lazy imports use TYPE_CHECKING + __getattr__
[ ] CONCURRENCY — shared mutable state protected with Lock from day one
[ ] TEXT EXTRACTION — negation detection + context windowing for keyword matching
[ ] DEAD CODE — old client deleted in same PR, not left "for reference"
[ ] PLAN PARITY — every "Required before merge" item is implemented
[ ] FUZZY MATCHING — threshold documented as named constant with rationale
```

## Related Documentation

- [Vertical Engine Extraction Patterns](vertical-engine-extraction-patterns.md) — asyncio.to_thread() pattern, lazy re-exports, non-fatal SSE design
- [Alembic Monorepo Migration](../database-issues/alembic-monorepo-migration-fk-rls-ordering.md) — backward-compatible import migration, global table patterns
- [Phase A Plan](../../plans/2026-03-15-refactor-credit-quant-architecture-parity-plan.md) — quant_engine decoupling, FredService, stress severity
- [Phase B Plan](../../plans/2026-03-15-feat-edgar-upgrade-edgartools-plan.md) — EDGAR upgrade with edgartools (deepened with 11 review agents)
- [Brainstorm](../../brainstorms/2026-03-15-credit-engine-analytical-upgrade-brainstorm.md) — 4-phase analytical upgrade roadmap
