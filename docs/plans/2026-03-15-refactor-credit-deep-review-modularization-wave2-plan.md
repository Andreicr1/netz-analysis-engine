---
title: "refactor: Credit Deep Review Modularization — Wave 2"
type: refactor
status: active
date: 2026-03-15
origin: docs/brainstorms/2026-03-15-credit-vertical-modular-alignment-brainstorm.md
deepened: 2026-03-15
---

# refactor: Credit Deep Review Modularization — Wave 2

## Enhancement Summary

**Deepened on:** 2026-03-15
**Research agents used:** 10 (architecture-strategist, performance-oracle, security-sentinel, pattern-recognition-specialist, code-simplicity-reviewer, best-practices-researcher ×3, framework-docs-researcher, codebase-explorer)
**Learnings applied:** 4 (wave1-credit-modularization, vertical-engine-extraction-patterns, unified-pipeline-ingestion, hybrid-classifier)

### Key Improvements
1. **Phase 0 prerequisite added:** Resolve `async_session_factory` binding before any structural change (Critical — 4 undefined references will NameError after module split)
2. **`__init__.py` pattern corrected:** PEP 562 lazy imports to match edgar/memo reference implementations (not standard imports)
3. **Import-linter layers contract:** Concrete `pyproject.toml` config using `layers` contract with `|` pipe-separated independent siblings and `exhaustive = true`
4. **Golden test strategy added:** Missing from original plan (Wave 1 convention #5 violation)
5. **Security findings:** 2 Critical (async_session_factory RLS risk, missing organization_id in RAG queries), 3 High (prompt IP leakage, thread safety, search tenant filter)
6. **Simplicity review applied:** Weighed 11-module vs 7-module split — kept 11 with justifications from architecture and pattern reviews

### Debate: 11 Modules vs 7 Modules

The simplicity reviewer recommended merging to 7 files (eliminate models.py, decision.py, persist.py, portfolio.py). The architecture and pattern reviewers disagreed:

- **`decision.py` (keep separate):** `_compute_decision_anchor()` is the single source of truth for `finalDecision` (INVEST/CONDITIONAL/PASS) — a deterministic gate distinct from policy compliance. Architecture review confirmed the split at line 431 of `deep_review_policy.py`. Keeping it separate makes the decision logic independently testable and auditable.
- **`persist.py` (keep separate):** The architecture review found that persist logic is the only safe deduplication target between sync/async paths (identical DB writes with same session type). Extracting it enables a single `persist_review_artifacts()` function callable by both paths — reducing 260 LOC of duplication to one call site.
- **`portfolio.py` (keep separate):** Contains `run_all_portfolio_reviews()` which uses `ThreadPoolExecutor` and `async_session_factory` — a distinct concurrency concern from the main orchestrator. Security review requires ORM scalar extraction before threading (Finding F4).
- **`models.py` (keep):** Will hold `_LLM_CONCURRENCY` (env-read integer), stage criticality enum, and the `__all__` restriction for prompt IP protection. Architecture review noted this is the leaf node that enables the DAG — removing it breaks the import-linter layers contract.

**Verdict:** Keep 11 modules. The complexity is justified by the ~5430 LOC, the three-tier DAG, and the dedup opportunity in persist.py.

### New Considerations Discovered
- `_PORTFOLIO_REVIEW_SYSTEM` (108-line prompt) is a string literal in `deep_review_prompts.py`, not behind Jinja2 — IP exposure risk
- Policy compliance at line 382-388 falls back to importing `_call_openai` from the orchestrator — circular dependency when split
- `search_deal_chunks()` filters by `deal_id` only, no `organization_id` — tenant isolation gap (pre-existing, flag for fix)
- LLM-generated strings persisted to JSONB without sanitization (pre-existing, flag for fix)
- `db.add()` in a for-loop for risk flags — should be `db.add_all()` (minor perf fix)

---

## Overview

Decompose the deep_review cluster (~5430 LOC, 6 files) into an edgar-style `deep_review/` package. This is the final phase of the credit vertical modular alignment — Wave 1 (PRs #8-19) modularized all 12 engine packages; Wave 2 tackles the central orchestrator that calls them all.

**Scope:** 1 PR (single atomic package extraction) + 1 follow-up PR (prompt relocation + cleanup).

**Reference implementation:** `backend/vertical_engines/credit/edgar/` and Wave 1 conventions (see `docs/solutions/architecture-patterns/wave1-credit-vertical-modularization-MonolithToPackages-20260315.md`).

## Problem Statement

The deep_review cluster is the last set of flat files in `backend/vertical_engines/credit/`:
- `deep_review.py` (2990 LOC) — monolithic orchestrator with sync + async variants that are near-identical (~2400 LOC of duplicated logic)
- `deep_review_corpus.py` (608 LOC) — evidence gathering, RAG retrieval, deal context loading
- `deep_review_policy.py` (723 LOC) — hard/soft policy checks, decision anchor, legacy confidence
- `deep_review_confidence.py` (518 LOC) — underwriting reliability score (deterministic, no LLM)
- `deep_review_helpers.py` (241 LOC) — LLM wrappers, JSON parsing, utility functions
- `deep_review_prompts.py` (350 LOC) — instrument pre-classification, prompt construction

Issues: stdlib `logging` in all 6 files, no `__init__.py`/`__all__`, redundant try/except around never-raises engines (post-Wave 1), massive sync/async duplication.

## Proposed Solution

### Package Structure

```
deep_review/
  __init__.py          # Public API + __all__ (PEP 562 lazy imports — match edgar/memo pattern)
  models.py            # Constants, type aliases, stage criticality (LEAF — zero sibling imports)
  helpers.py           # LLM wrappers, JSON parsing, utilities (was deep_review_helpers.py)
  corpus.py            # Evidence gathering, RAG retrieval, deal context (was deep_review_corpus.py)
  prompts.py           # Instrument pre-classification, prompt construction (was deep_review_prompts.py)
  policy.py            # Hard/soft policy checks, policy RAG (from deep_review_policy.py)
  decision.py          # Decision anchor + legacy confidence (from deep_review_policy.py)
  confidence.py        # Underwriting reliability score (was deep_review_confidence.py)
  persist.py           # All DB persist logic extracted from deep_review.py (~260 LOC)
  portfolio.py         # Portfolio review functions (from deep_review.py, ~147 LOC)
  service.py           # Main orchestrator: sync + async pipelines + batch runners
```

### DAG Enforcement (5-Tier)

```
Tier 1 (top):    service.py          — entry point, may import everything below
Tier 2:          portfolio.py        — depends on persist and domain tier
Tier 3:          persist.py          — depends on domain tier and models
Tier 4:          helpers | corpus | prompts | policy | decision | confidence  — independent peers
Tier 5 (bottom): models.py           — pure data, zero sibling imports
```

- `models.py` — zero sibling imports (leaf)
- `helpers.py`, `corpus.py`, `prompts.py` — import only `models.py`
- `policy.py` — imports `models.py`, `helpers.py` (needs LLM wrapper for soft policy)
- `decision.py` — imports `models.py` only (pure deterministic)
- `confidence.py` — imports `models.py` only (pure deterministic)
- `persist.py` — imports `models.py`, `helpers.py` (DB operations)
- `portfolio.py` — imports `models.py`, `helpers.py`, `prompts.py`, `corpus.py` (self-contained review flow)
- `service.py` — sole orchestrator, imports ALL above modules + sibling engine packages

### Research Insights: DAG Design

**Best Practices:**
- The `|` pipe separator in import-linter's `layers` contract enforces independence between Tier 4 siblings automatically — no separate `independence` contract needed.
- Use `exhaustive = true` with `exhaustive_ignores = ["__init__"]` to catch undeclared new files.
- The three-tier DAG (models → domain → persist/portfolio → service) is novel vs Wave 1's two-tier pattern but justified by deep_review's unique role as the persistence orchestrator for all other engines.

**Import-Linter Configuration:**

```toml
[[tool.importlinter.contracts]]
name = "Deep review internal DAG"
type = "layers"
layers = [
    "service",
    "portfolio",
    "persist",
    "helpers | corpus | prompts | policy | decision | confidence",
    "models",
]
containers = [
    "vertical_engines.credit.deep_review",
]
exhaustive = true
exhaustive_ignores = [
    "__init__",
]
```

This is additive to the existing 4 contracts. The existing wildcard contracts (`vertical_engines.credit.*.models` must not import `vertical_engines.credit.*.service`) will also cover the new package automatically.

**Edge Cases:**
- `TYPE_CHECKING` imports are excluded from the graph via `exclude_type_checking_imports = true` (already configured). Use `if TYPE_CHECKING:` blocks freely for type annotations across tiers.
- PEP 562 `__getattr__` lazy imports are invisible to import-linter (AST-level, not runtime). The layers contract won't flag them.
- Adding contracts is cheap — all run against the same pre-built grimp graph. No CI slowdown.

### Error Contract

**Never-raises** (orchestration engine). Returns result dict with `status` field. Failed sub-stages set `status: 'NOT_ASSESSED'` with `exc_info=True` in structlog. The orchestrator never aborts due to a single engine failure.

### Research Insights: Error Contracts

**Best Practices:**
- Use the two-function split pattern (from `critic/service.py`): public function is the contract boundary (try/except + fallback), private function contains the logic and is free to raise.
- Keep defense-in-depth try/except around never-raises sub-engines. When the outer catch fires, log with a distinctive `NEVER_RAISES_CONTRACT_VIOLATION` prefix — set a production alert on this pattern.
- Consider named `StageOutcome` dataclass for stage results (name-based lookup instead of positional `asyncio.gather` unpacking). Prevents silent breakage on reorder. Deferred to sync/async dedup phase.

**Stage Criticality Classification (for `models.py`):**

```python
STAGE_CRITICALITY: dict[str, str] = {
    "deal_lookup": "fatal",
    "rag_context": "fatal",
    "structured_analysis": "fatal",
    "macro_context": "degraded",
    "edgar": "degraded",
    "kyc": "degraded",
    "quant": "fatal",
    "concentration": "fatal",
    "policy_hard": "fatal",
    "policy_llm": "fatal",
    "sponsor": "fatal",
    "evidence_pack": "fatal",
    "critic": "degraded",
    "memo_book": "fatal",
    "persist": "fatal",
}
```

This makes the fatal/non-fatal distinction explicit and grep-able rather than buried in if/else chains. Include in `models.py` but do not refactor the orchestrator to use it in Wave 2 — that is a behavioral change.

**Error Contract Testing (add to Wave 2):**
- Parametrized exception injection for `confidence.py`, `decision.py`, `policy.py::_run_hard_policy_checks()`
- These are pure deterministic functions — ideal candidates for contract verification tests

## Technical Approach

### Phase 0: Prerequisites (before branching)

#### 0a. Resolve `async_session_factory` binding (CRITICAL — P0)

`async_session_factory` appears at lines 278, 1720, 2822, 2917 of `deep_review.py` but is **never imported**. The `F821` (undefined name) ruff error is silently suppressed in `pyproject.toml` line 99. When the code moves to `service.py` and `portfolio.py` in separate modules, the runtime namespace injection will break.

**Investigation steps:**
1. Search for `deep_review.async_session_factory =` and `setattr(deep_review` across the codebase
2. Search for `async_session_factory` in `app.core.db.engine` — this is the likely source
3. Determine if it is monkey-patched, passed via closure, or a dead code path

**Resolution: Explicit import (decided).** Add `from app.core.db.engine import async_session_factory` as a function-level import in each of the 4 functions that use it. Parameter injection was considered but rejected — it changes the function interface (callers of `run_all_portfolio_reviews` and `run_all_deals_deep_review_v4` would need updates), making it a behavioral change. Wave 2 is a structural refactor; the explicit import preserves exact behavior.

**Security concern (from security audit):** The injected session factory may not set `SET LOCAL app.current_organization_id`. Verify RLS context is established in all threaded sessions.

#### 0b. Capture golden test snapshots (Wave 1 convention #5)

Before any file moves, capture outputs for deterministic submodules:

```bash
# confidence.py — underwriting reliability score (6 blocks, deterministic)
python -c "from vertical_engines.credit.deep_review_confidence import compute_underwriting_confidence; ..."

# decision.py — decision anchor (INVEST/CONDITIONAL/PASS, deterministic)
python -c "from vertical_engines.credit.deep_review_policy import _compute_decision_anchor; ..."

# policy.py — hard policy checks (4 hard limits, deterministic)
python -c "from vertical_engines.credit.deep_review_policy import _run_hard_policy_checks; ..."
```

Create test fixtures with known inputs. Assert outputs match after the move with `rtol=1e-6` for floating-point fields.

**For the orchestrator (`service.py`):** The full pipeline depends on LLM calls and is non-deterministic. The existing integration tests + import verification test are sufficient. Do NOT attempt golden tests for the orchestrator.

#### 0c. Fix policy compliance circular import

`deep_review_policy.py` lines 382-388 import `_call_openai` from the orchestrator:
```python
from vertical_engines.credit import deep_review as _deep_review
openai_caller = getattr(_deep_review, "_call_openai", _call_openai)
```

After the split, `_call_openai` will live in `helpers.py`. Update `policy.py` to import directly from `helpers.py`:
```python
from vertical_engines.credit.deep_review.helpers import _call_openai
```

This must be resolved before the module split to avoid a circular import (policy → deep_review → policy).

### Phase 1: Package Extraction (PR #1 — single atomic PR)

Create `deep_review/` directory and move all 6 files, splitting `deep_review.py` and `deep_review_policy.py` into their logical components.

#### 1a. Create `deep_review/models.py` (LEAF)

Extract from `deep_review.py`:
- `_LLM_CONCURRENCY` constant (line 89: `max(1, int(os.getenv("NETZ_LLM_CONCURRENCY", "5")))`) — env-read integer, NOT an asyncio primitive
- `STAGE_CRITICALITY` dict (new — documents fatal/non-fatal stages, used for logging enrichment only)
- Any shared type aliases

**Research insight:** `_LLM_CONCURRENCY` is safe as a module-level constant because it is a plain `int`, not an `asyncio.Semaphore`. Add a comment: `# Plain integer — NOT an asyncio primitive. Safe at module scope.`

**Dataclass formalization is deferred.** Per Wave 1 convention #6, do not formalize the result dict into a frozen dataclass during this refactor. The deep_review result is a complex aggregation of 9+ engine outputs. Formalize when callers need type safety.

#### 1b. Relocate satellite files (rename only)

These 4 files are already well-separated — just move into the package directory:

| Source | Target | Changes |
|---|---|---|
| `deep_review_helpers.py` (241 LOC) | `deep_review/helpers.py` | Update imports, stdlib→structlog, add `__all__` |
| `deep_review_corpus.py` (608 LOC) | `deep_review/corpus.py` | Update imports, stdlib→structlog, add `__all__` |
| `deep_review_prompts.py` (350 LOC) | `deep_review/prompts.py` | Update imports, stdlib→structlog, add `__all__` |
| `deep_review_confidence.py` (518 LOC) | `deep_review/confidence.py` | Update imports, stdlib→structlog, add `__all__` |

**Security requirement (Finding F3):** Define `__all__` in every module. Exclude all prompt constants and template-rendering functions from `__all__`. Specifically, `_DEAL_REVIEW_SYSTEM_LEGACY` and `_PORTFOLIO_REVIEW_SYSTEM` must NOT be in any `__all__`.

#### 1c. Split `deep_review_policy.py` → `policy.py` + `decision.py`

`deep_review_policy.py` (723 LOC) has two distinct concerns:

**`deep_review/policy.py`** (~390 LOC):
- `_parse_lockup_to_years()` — utility
- `_gather_policy_context()` — policy RAG retrieval
- `_run_hard_policy_checks()` — deterministic arithmetic (4 hard limits)
- `_run_policy_compliance()` — LLM-assessed soft guideline checks

**`deep_review/decision.py`** (~330 LOC):
- `_compute_decision_anchor()` — authoritative pipeline decision (INVEST/CONDITIONAL/PASS)
- `_compute_confidence_score()` — two-layer confidence computation

Both are pure functions that receive their inputs as parameters — no shared mutable state.

**Research insight:** The architecture review confirmed the split point at line 431. `_compute_decision_anchor()` is the single source of truth for `finalDecision` — it is a distinct deterministic gate from policy compliance. The split enables independent testing of the decision logic.

#### 1d. Extract `deep_review/persist.py` from `deep_review.py`

Extract all DB persistence logic from `deep_review.py` Stages 13b/c/d (~260 LOC duplicated between sync and async):
- Evidence pack metadata update (analyst_summary, executive_summary into JSONB)
- Underwriting artifact persist
- Profile + brief + risk flags persist
- `_index_chapter_citations()` helper
- `_build_tone_artifacts()` helper

**Research insight (architecture review):** Extract a single `persist_review_artifacts(db, ...)` function. Both `run_deal_deep_review_v4` and `async_run_deal_deep_review_v4` can call it because the DB operations are synchronous ORM calls even in the async path (same `Session` type). This is NOT behavioral dedup — it is extraction of identical DB writes.

**Performance fix:** Replace `for _flag in _v4_risk_flags: db.add(_flag)` with `db.add_all(_v4_risk_flags)` in the extracted function. One-line change, fewer round trips.

#### 1e. Extract `deep_review/portfolio.py` from `deep_review.py`

Extract portfolio review functions (~147 LOC):
- `run_portfolio_review()` — single investment periodic AI review
- `run_all_portfolio_reviews()` — batch runner with ThreadPoolExecutor
- `get_current_im_draft()` — query API for current IM draft

**Security requirement (Finding F4):** Extract ORM scalars into a plain list of UUIDs before spawning threads:
```python
# Before (broken — ORM attributes accessed across session boundaries):
futures = {executor.submit(_review_investment, inv): inv for inv in investments}

# After (safe — plain data crosses the thread boundary):
investment_ids = [(inv.id, inv.fund_id) for inv in investments]
futures = {executor.submit(_review_investment, inv_id, fund_id): inv_id for inv_id, fund_id in investment_ids}
```

**`async_session_factory` handling:** After Phase 0a resolution, add explicit import as a function-level import in `run_all_portfolio_reviews()` and `run_all_deals_deep_review_v4()`.

#### 1f. Create `deep_review/service.py` — orchestrator

The remaining `deep_review.py` logic (~2000 LOC) becomes `service.py`:
- `run_deal_deep_review_v4()` — sync pipeline (13 stages)
- `async_run_deal_deep_review_v4()` — async pipeline (7 phases)
- `run_all_deals_deep_review_v4()` — sync batch runner
- `async_run_all_deals_deep_review_v4()` — async batch runner

**Important:** The sync/async duplication (~2400 LOC) is preserved as-is in this PR. Deduplication is a separate behavioral change and should be a follow-up PR.

**Research insights:**
- **Keep function-level imports in service.py.** The ~40 function-level imports inside pipeline functions are by design — they keep import time O(1) and prevent circular dependencies. Add a comment at the top: `# NOTE: Sibling engine imports are function-level (not module-scope) by design.`
- **Defense-in-depth try/except:** Log with `NEVER_RAISES_CONTRACT_VIOLATION` prefix when the outer catch fires around a never-raises engine. This makes contract violations alertable in production.

### Research Insights: Sync/Async Duplication (Future)

The ~2400 LOC duplication is preserved in Wave 2 — this is the correct decision. Research identified three approaches for future dedup:

1. **Shared-core extraction (recommended first step):** Extract pure business logic into sync helpers. Reduces duplication to ~960 LOC of orchestration flow.
2. **`unasyncd` code generation (if needed):** AST-level via libcst, supports complex transformations. Psycopg3 uses this pattern for 27 files. Configuration via `pyproject.toml`.
3. **`asyncio.to_thread()` wrapper (not viable):** Loses async concurrency benefits. Incompatible with your `asyncpg` + `AsyncSession` architecture.

**Key finding:** Session lifecycle divergence (`AsyncSession` with `expire_on_commit=False` vs sync `Session`) makes full dedup risky. The shared-core approach is safer because the pure logic layer has no session dependency.

#### 1g. Create `deep_review/__init__.py`

**Corrected:** Use PEP 562 `__getattr__` to match the edgar and memo reference implementations.

```python
"""Deep Review V4 — IC-Grade Investment Memorandum Pipeline.

Three-tier DAG: models → domain modules → persist/portfolio → service.
This is distinct from the standard two-tier edgar pattern because deep_review
is the only engine that persists other engines' results.

Public API:
    run_deal_deep_review_v4()           — sync single-deal deep review
    async_run_deal_deep_review_v4()     — async single-deal deep review
    run_all_deals_deep_review_v4()      — sync batch deep review
    async_run_all_deals_deep_review_v4() — async batch deep review
    run_portfolio_review()              — single investment periodic review
    run_all_portfolio_reviews()         — batch portfolio reviews
    get_current_im_draft()              — query current IM draft
    compute_underwriting_confidence()   — underwriting reliability score
    apply_tone_normalizer_adjustment()  — post-tone confidence adjustment

Error contract: never-raises (orchestration engine). Functions return result
dicts with status/warnings on failure. exc_info=True in structlog.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

# Eagerly import leaf-node symbols only (no transitive deps)
from vertical_engines.credit.deep_review.confidence import (
    apply_tone_normalizer_adjustment,
    compute_underwriting_confidence,
)

if TYPE_CHECKING:
    from vertical_engines.credit.deep_review.portfolio import (
        get_current_im_draft as get_current_im_draft,
        run_all_portfolio_reviews as run_all_portfolio_reviews,
        run_portfolio_review as run_portfolio_review,
    )
    from vertical_engines.credit.deep_review.service import (
        async_run_all_deals_deep_review_v4 as async_run_all_deals_deep_review_v4,
        async_run_deal_deep_review_v4 as async_run_deal_deep_review_v4,
        run_all_deals_deep_review_v4 as run_all_deals_deep_review_v4,
        run_deal_deep_review_v4 as run_deal_deep_review_v4,
    )

__all__ = [
    "run_deal_deep_review_v4",
    "async_run_deal_deep_review_v4",
    "run_all_deals_deep_review_v4",
    "async_run_all_deals_deep_review_v4",
    "run_portfolio_review",
    "run_all_portfolio_reviews",
    "get_current_im_draft",
    "compute_underwriting_confidence",
    "apply_tone_normalizer_adjustment",
]


def __getattr__(name: str) -> Any:
    if name in (
        "run_deal_deep_review_v4",
        "async_run_deal_deep_review_v4",
        "run_all_deals_deep_review_v4",
        "async_run_all_deals_deep_review_v4",
    ):
        from vertical_engines.credit.deep_review.service import (
            async_run_all_deals_deep_review_v4,
            async_run_deal_deep_review_v4,
            run_all_deals_deep_review_v4,
            run_deal_deep_review_v4,
        )
        return {
            "run_deal_deep_review_v4": run_deal_deep_review_v4,
            "async_run_deal_deep_review_v4": async_run_deal_deep_review_v4,
            "run_all_deals_deep_review_v4": run_all_deals_deep_review_v4,
            "async_run_all_deals_deep_review_v4": async_run_all_deals_deep_review_v4,
        }[name]
    if name in ("run_portfolio_review", "run_all_portfolio_reviews", "get_current_im_draft"):
        from vertical_engines.credit.deep_review.portfolio import (
            get_current_im_draft,
            run_all_portfolio_reviews,
            run_portfolio_review,
        )
        return {
            "run_portfolio_review": run_portfolio_review,
            "run_all_portfolio_reviews": run_all_portfolio_reviews,
            "get_current_im_draft": get_current_im_draft,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

**Why PEP 562 (corrected from original plan):** The edgar package and memo package both use `__getattr__` for lazy imports. While deep_review's dependencies are sibling packages, `service.py` has function-level imports of the entire ORM model graph, prompt registry, and token budget tracker. Eagerly importing `service.py` via `__init__.py` would transitively load all of these on any `from vertical_engines.credit.deep_review import compute_underwriting_confidence` — pulling in the entire dependency graph for a pure deterministic function from `confidence.py`.

#### 1h. Update all external callers

8 files need import path updates:

| Caller | Current Import | New Import |
|---|---|---|
| `app/domains/credit/modules/ai/deep_review.py` | `from vertical_engines.credit.deep_review import async_run_all_deals_deep_review_v4` | `from vertical_engines.credit.deep_review import async_run_all_deals_deep_review_v4` (same — package `__init__` now) |
| `app/domains/credit/modules/ai/portfolio.py` | `from vertical_engines.credit.deep_review import run_portfolio_review, ...` | Same (resolved by package `__init__`) |
| `app/services/azure/pipeline_dispatch.py` | `from vertical_engines.credit.deep_review import async_run_deal_deep_review_v4` | Same |
| `ai_engine/ingestion/pipeline_ingest_runner.py` | `from vertical_engines.credit.deep_review import run_all_deals_deep_review_v4` | Same |
| `ai_engine/validation/eval_runner.py` | `from vertical_engines.credit.deep_review import run_deal_deep_review_v4` | Same |
| `ai_engine/validation/eval_metrics.py` | `from vertical_engines.credit.deep_review_confidence import compute_underwriting_confidence` | `from vertical_engines.credit.deep_review import compute_underwriting_confidence` |
| `ai_engine/validation/deep_review_validation_runner.py` | `from vertical_engines.credit.deep_review import run_deal_deep_review_v4` | Same |
| `worker_app/function_app.py` | `from vertical_engines.credit.deep_review import async_run_deal_deep_review_v4` | Same |

**Key insight:** Most callers already import `from vertical_engines.credit.deep_review import X`. When `deep_review.py` becomes `deep_review/__init__.py` (with re-exports), these import paths continue to work. Only `eval_metrics.py` (which imports from `deep_review_confidence`) needs a path change.

**Git strategy (Windows NTFS):** Cannot have `deep_review.py` and `deep_review/` at the same path simultaneously on NTFS. The `git mv` with temp file approach can result in "file deleted + new file created" instead of proper rename tracking. Use copy + git rm instead:

```powershell
# 1. Create the package directory first
New-Item -ItemType Directory backend\vertical_engines\credit\deep_review

# 2. Copy (not move) content to destination files
Copy-Item backend\vertical_engines\credit\deep_review.py backend\vertical_engines\credit\deep_review\service.py
Copy-Item backend\vertical_engines\credit\deep_review_helpers.py backend\vertical_engines\credit\deep_review\helpers.py
Copy-Item backend\vertical_engines\credit\deep_review_corpus.py backend\vertical_engines\credit\deep_review\corpus.py
# ... (all satellite files)

# 3. git add the new files
git add backend/vertical_engines/credit/deep_review/

# 4. git rm the originals
git rm backend/vertical_engines/credit/deep_review.py
git rm backend/vertical_engines/credit/deep_review_helpers.py
git rm backend/vertical_engines/credit/deep_review_corpus.py
# ... (all flat files)

# 5. Commit together — Git detects the rename via content similarity
```

This ensures `git blame` on `service.py` traces back to the original `deep_review.py` history.

#### 1i. Cleanup: try/except around never-raises engines

Post-Wave 1, these engines have documented never-raises contracts. The defensive try/except in deep_review.py are now redundant safety nets:

| Engine | Sync lines | Async lines | Action |
|---|---|---|---|
| EDGAR | 534-566 | 1838-1872 | Keep as non-fatal (already correct) |
| KYC | 686-729 | 1938-1964 | Keep as non-fatal (already correct) |
| Tone normalizer | 1162-1244 | 2404-2454 | Keep as non-fatal (already correct) |
| Market benchmarks | 478-497 | 1734-1758 | Keep (per-chapter) |

**Decision:** Leave the try/except blocks in place during Wave 2. They are defense-in-depth and their removal would be a behavioral change, not a structural refactor. Add `NEVER_RAISES_CONTRACT_VIOLATION` log prefix to all outer catches so they are alertable if they ever fire in production.

#### 1j. structlog migration

Replace `import logging` / `logging.getLogger(__name__)` with `import structlog` / `structlog.get_logger()` in all 6 files. Log at function boundaries only.

**Research insights:**
- Use `bind()` for context propagation: `log = logger.bind(deal_id=str(deal_id))`
- Use dot-separated event names: `log.info("deep_review.stage.evidence_gathering.complete")` not `log.info("Evidence gathering completed")`
- `exc_info=True` is implicit in `logger.exception()` for structlog — no need to pass explicitly
- Use `contextvars` for request-scoped context in async pipeline: `bind_contextvars(deal_id=str(deal_id), pipeline="deep_review_v4")`

**Migration checklist per file:**
```
[ ] Replace `import logging` with `import structlog`
[ ] Replace `logger = logging.getLogger(__name__)` with `logger = structlog.get_logger()`
[ ] Replace `logger.info("msg %s", val)` with `logger.info("event.name", key=val)`
[ ] Add `bind()` at function boundaries for context
[ ] Remove f-string interpolation in log messages
```

#### 1k. Update `test_vertical_engines.py::EXPECTED_MODULES`

Remove the 6 flat file entries:
- `vertical_engines.credit.deep_review`
- `vertical_engines.credit.deep_review_corpus`
- `vertical_engines.credit.deep_review_helpers`
- `vertical_engines.credit.deep_review_policy`
- `vertical_engines.credit.deep_review_prompts`
- `vertical_engines.credit.deep_review_confidence`

Replace with single package entry:
- `vertical_engines.credit.deep_review`

(Same module path — but now resolves to a package `__init__.py` instead of a flat file.)

#### 1l. Add golden tests for deterministic submodules (NEW)

Create test fixtures and assertions for:

1. **`confidence.py::compute_underwriting_confidence()`** — 6-block scoring with known inputs → known output (0-100 integer)
2. **`decision.py::_compute_decision_anchor()`** — deterministic INVEST/CONDITIONAL/PASS with known inputs
3. **`policy.py::_run_hard_policy_checks()`** — 4 hard limits with known inputs → known violations list

```python
class TestGoldenOutputs:
    """Verify zero behavioral change after module extraction."""

    def test_confidence_golden(self):
        result = compute_underwriting_confidence(**GOLDEN_CONFIDENCE_INPUT)
        assert result["confidence_score"] == pytest.approx(GOLDEN_CONFIDENCE_SCORE, rel=1e-6)

    def test_decision_anchor_golden(self):
        result = _compute_decision_anchor(**GOLDEN_DECISION_INPUT)
        assert result["finalDecision"] == "INVEST"  # or CONDITIONAL/PASS per fixture

    def test_hard_policy_golden(self):
        result = _run_hard_policy_checks(**GOLDEN_POLICY_INPUT)
        assert result["hard_limit_breaches"] == GOLDEN_BREACHES
```

#### 1m. Deletion audit (NEW — Wave 1 convention)

After extraction, verify:
- [ ] No dead functions created by the split (functions only called from one module that are now unreachable)
- [ ] No stale imports (imports that referenced symbols now in different modules)
- [ ] `grep -r "deep_review_helpers\|deep_review_corpus\|deep_review_policy\|deep_review_prompts\|deep_review_confidence" backend/` returns zero hits outside `deep_review/`
- [ ] Old flat files deleted in the same PR (Wave 1 convention: "delete, do not deprecate")

### Phase 2: Prompt Relocation (PR #2 — follow-up)

Move the 4 `.j2` templates used by deep_review into the package:

| Template | Used by | New location |
|---|---|---|
| `structured_legacy.j2` | `deep_review/prompts.py` | `deep_review/templates/structured_legacy.j2` |
| `deal_review_system_v1.j2` | `deep_review/prompts.py` | `deep_review/templates/deal_review_system_v1.j2` |
| `deal_review_system_v2.j2` | `deep_review/prompts.py` | `deep_review/templates/deal_review_system_v2.j2` |
| `portfolio_review.j2` | `deep_review/service.py` | `deep_review/templates/portfolio_review.j2` |

**Note:** The remaining 26 `.j2` files in `credit/prompts/` belong to other engines (memo chapter prompts ch01-ch14, critic, tone, evidence_law). They stay in `credit/prompts/` or migrate with their respective engines in a future cleanup.

**Security priority (Finding F3b):** Also move `_PORTFOLIO_REVIEW_SYSTEM` (108-line string literal in `deep_review_prompts.py`) to a Jinja2 template. Currently it is a raw string in source code — Netz IP directly in a module that can be imported. Converting to a `.j2` template puts it behind the prompt registry.

Update `prompt_registry` search paths to include `deep_review/templates/`. Verify Jinja2 `render()` resolves correctly.

### Phase 3: Future Opportunities (NOT in scope)

These are explicitly deferred:
- **Sync/async deduplication** — The ~2400 LOC of duplicated logic between sync and async pipelines. Research recommends shared-core extraction as the first step (extract pure business logic into sync helpers), then evaluate `unasyncd` if orchestration flow duplication remains burdensome. Separate PR.
- **Retrieval exception deprecation** — `EvidenceGapError`, `RetrievalScopeError`, `ProvenanceError` in `retrieval/models.py` are backward-compat from Wave 1. Deprecate when callers stop catching them.
- **Named `StageOutcome` dataclass** — Replace positional `asyncio.gather` + `isinstance(result, BaseException)` unpacking with name-based lookup. Prevents silent breakage on stage reorder. Part of the sync/async dedup effort.
- **`organization_id` in RAG queries** — Pre-existing tenant isolation gap in `search_deal_chunks()` and `_gather_policy_context()`. Must be fixed before Azure Search stub is replaced with real implementation.
- **LLM output sanitization** — Pre-existing: LLM-generated strings persisted to JSONB without HTML stripping or length enforcement. Fix in `persist.py` when the search client goes live.

## System-Wide Impact

### Interaction Graph

`deep_review/service.py` is the central hub — it calls every Wave 1 engine package:
- critic, edgar, memo, quant, sponsor, kyc, market_data, retrieval, underwriting
- ai_engine (governance, model_config, prompts, portfolio/concentration)
- app/domains/credit/modules/ai/models (ORM models for persistence)

All these dependencies are imported at function level inside the pipeline functions, not at module scope. This means the package `__init__.py` can use PEP 562 lazy imports for the public API surface, eagerly importing only leaf-node symbols (`compute_underwriting_confidence`, `apply_tone_normalizer_adjustment`).

### Error Propagation

The deep_review orchestrator already implements per-stage error isolation. Each engine call is wrapped in its own error handling. Post-Wave 1, engine failures return `status: 'NOT_ASSESSED'` rather than raising, so the orchestrator's try/except blocks are defense-in-depth.

### State Lifecycle Risks

Pure structural refactor. No schema changes, no new tables, no data flow changes. The only risk is import path breakage, mitigated by:
1. Most callers import `from vertical_engines.credit.deep_review import X` — which continues to work since `deep_review/` package `__init__.py` re-exports the same symbols
2. `make check` (lint + architecture + typecheck + test) gate
3. `test_vertical_engines.py` structural test
4. Golden tests for deterministic submodules (NEW)

## Acceptance Criteria

### Functional Requirements

- [ ] `deep_review/` is a package with 11 modules following the 5-tier DAG
- [ ] All 8 external callers work with updated import paths
- [ ] No flat `deep_review*.py` files remain in `credit/` root
- [ ] `__init__.py` exports all previously-importable public functions via PEP 562
- [ ] `make check` passes (lint + architecture + typecheck + test)
- [ ] `async_session_factory` resolved with explicit imports (no undefined names)

### Non-Functional Requirements

- [ ] Zero behavioral change — all pipeline outputs identical (verified by golden tests)
- [ ] structlog replaces stdlib `logging` in all 11 modules
- [ ] `__all__` defined in every module — prompt constants excluded
- [ ] Error contract documented in `__init__.py` docstring (three-tier DAG note)
- [ ] Import DAG verified (no circular imports within package)
- [ ] `test_vertical_engines.py::EXPECTED_MODULES` updated
- [ ] Golden tests passing for confidence, decision, and hard policy

### Quality Gates

- [ ] Import DAG verified: `python -c "import vertical_engines.credit.deep_review"`
- [ ] Architecture contracts pass: `lint-imports` (5/5 — 4 existing + 1 new layers contract)
- [ ] All 324+ tests pass
- [ ] Golden test snapshots match pre-refactor outputs

## Security Findings (from security audit)

| ID | Severity | Finding | Action |
|----|----------|---------|--------|
| F1 | **Critical** | `async_session_factory` unresolved binding — NameError + RLS bypass risk | Phase 0a prerequisite |
| F2 | **Critical** | Missing `organization_id` in RAG queries (`corpus.py`, `policy.py`) | Phase 3 deferred (stub client) |
| F3 | **High** | Prompt IP leakage via module exports — no `__all__` in any file | Phase 1b (`__all__` in every module) |
| F4 | **High** | ORM attributes accessed across thread boundaries in `portfolio.py` | Phase 1e (extract scalars before threading) |
| F5 | **High** | `search_deal_chunks()` no tenant filter | Phase 3 deferred (stub client) |
| F6 | Medium | SQL/OData string interpolation (UUID-typed, low exploitability) | Phase 3 deferred |
| F7 | Medium | LLM output unsanitized before JSONB persist | Phase 3 deferred |
| F8 | Low | Portfolio prompt injection surface (pre-existing) | Phase 2 (move to Jinja2) |
| F9 | Low | Error messages leak internal state (`str(exc)`) | Phase 1e (sanitize in portfolio.py) |
| F10 | Low | Asyncio primitive documentation gap | Phase 1a (comment in models.py) |

## Risk Analysis & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Import path breakage for callers | Low | High | Most callers use `from vertical_engines.credit.deep_review import X` which resolves to package `__init__` transparently |
| `async_session_factory` breaks | ~~Medium~~ **Resolved** | High | Phase 0a resolves before branching |
| Prompt registry path resolution | Low | Medium | Phase 2 (prompt relocation) is a separate PR. Phase 1 does not touch `.j2` paths. |
| Cross-module circular imports | Low | Medium | DAG enforced by import-linter layers contract (new) |
| Sync/async duplication hides divergent behavior | Low | Low | Preserve duplication in Phase 1. Dedup is a separate future effort with its own tests. |
| Policy compliance circular import on `_call_openai` | ~~Medium~~ **Resolved** | Medium | Phase 0c fixes before branching |
| Golden test coverage gap | Low | Medium | Phase 0b captures snapshots; Phase 1l adds assertions |

## Dependencies & Prerequisites

- Wave 1 complete (PRs #8-19 merged) ✅
- `make check` passes on current `main` before starting ✅
- No concurrent PRs touching `credit/` directory (serial discipline) ✅
- Phase 0a: `async_session_factory` resolved ✅ (commit 6b478b7)
- Phase 0b: Golden test snapshots captured ✅ (12 tests, commit 6b478b7)
- Phase 0c: Policy compliance circular import fixed ✅ (commit 6b478b7)

### Current Progress (as of session break)

- **Branch:** `refactor/credit-deep-review-wave2` (1 commit ahead of main)
- **Staging directory:** `backend/vertical_engines/credit/deep_review_pkg/` contains 9 of 11 modules (all except service.py and __init__.py)
- **Next step:** Phase 1b — create service.py from remaining deep_review.py (~2500 LOC transformation)
- **After that:** Phase 1c — rename deep_review_pkg → deep_review, update all internal imports
- **Final:** Phase 1d — external callers, import-linter contract, validation

## Per-PR Checklist

```
Phase 0 (before branching) — COMMITTED (6b478b7):
[x] async_session_factory binding resolved — explicit import in 4 functions
[x] Golden test snapshots captured for confidence, decision, hard policy (12 tests)
[x] Policy compliance _call_openai circular import fixed (policy.py → helpers.py)

Phase 1a — Module creation (IN PROGRESS, in deep_review_pkg/ staging dir):
[x] models.py — _LLM_CONCURRENCY + STAGE_CRITICALITY, zero sibling imports (leaf)
[x] helpers.py — structlog, __all__, zero behavioral changes (from agent)
[x] corpus.py — structlog, __all__, zero behavioral changes (from agent)
[x] prompts.py — structlog, __all__ (prompt constants excluded), zero behavioral changes (from agent)
[x] confidence.py — structlog, __all__, zero behavioral changes (from agent)
[x] policy.py — split from deep_review_policy.py, structlog, __all__ (from agent)
[x] decision.py — split from deep_review_policy.py, structlog, __all__ (from agent)
[x] persist.py — _index_chapter_citations + _build_tone_artifacts extracted
[x] portfolio.py — ORM scalars extracted before threading, error messages sanitized

Phase 1b — service.py creation (TODO):
[ ] Create service.py from remaining deep_review.py (~2500 LOC)
    - Remove extracted functions (portfolio, persist helpers, _LLM_CONCURRENCY)
    - Update imports to point to new package modules (deep_review_pkg.*)
    - stdlib logging → structlog
    - db.add() loop → db.add_all() (2 occurrences: sync + async)
    - Add NEVER_RAISES_CONTRACT_VIOLATION log prefix to outer catches
    - Keep ALL function-level imports as-is
    - Add __all__ with 4 public functions

Phase 1c — Package assembly (TODO):
[ ] Rename deep_review_pkg/ → deep_review/ (requires removing deep_review.py first)
    - Copy deep_review_pkg/* to deep_review/
    - git rm deep_review.py and all 5 flat deep_review_*.py files
    - git rm deep_review_pkg/ staging directory
[ ] Create __init__.py with PEP 562 lazy imports matching edgar/memo pattern
[ ] Update ALL internal imports in package modules:
    - deep_review_helpers → deep_review.helpers
    - deep_review_corpus → deep_review.corpus
    - deep_review_prompts → deep_review.prompts
    - deep_review_policy → deep_review.policy (+ decision)

Phase 1d — External callers + validation (TODO):
[ ] Update eval_metrics.py import path (only external caller that changes)
[ ] Update test_vertical_engines.py::EXPECTED_MODULES
[ ] Add import-linter layers contract to pyproject.toml
[ ] Golden tests updated to import from new package paths
[ ] Deletion audit — grep confirms zero remaining old import paths
[ ] python -c "import vertical_engines.credit.deep_review" succeeds
[ ] make check passes — lint + typecheck + test + architecture (5/5 contracts)
```

## Sources & References

### Origin

- **Brainstorm:** [docs/brainstorms/2026-03-15-credit-vertical-modular-alignment-brainstorm.md](docs/brainstorms/2026-03-15-credit-vertical-modular-alignment-brainstorm.md) — Wave 2 scope at lines 106-116. Key decisions: edgar pattern, prompt relocation to package-local directory.

### Internal References

- **Wave 1 plan:** `docs/plans/2026-03-15-refactor-credit-vertical-modular-alignment-wave1-plan.md` — conventions, per-PR checklist, error contracts
- **Wave 1 compound doc:** `docs/solutions/architecture-patterns/wave1-credit-vertical-modularization-MonolithToPackages-20260315.md` — the playbook
- **Edgar reference:** `backend/vertical_engines/credit/edgar/` — canonical package pattern (PEP 562 `__getattr__`)
- **Memo reference:** `backend/vertical_engines/credit/memo/__init__.py` — PEP 562 with TYPE_CHECKING stubs
- **Extraction patterns:** `docs/solutions/architecture-patterns/vertical-engine-extraction-patterns.md` — ProfileLoader, async patterns
- **Pipeline consolidation:** `docs/solutions/architecture-patterns/unified-pipeline-ingestion-path-consolidation-Phase2-20260315.md` — frozen dataclasses, "delete don't deprecate", function-level lazy imports
- **Thread safety:** `docs/solutions/runtime-errors/thread-unsafe-rate-limiter-FredService-20260315.md`
- **Hybrid classifier:** `docs/solutions/architecture-patterns/replace-external-ml-api-with-local-hybrid-classifier-DocumentClassifier-20260315.md` — asyncio.Lock bootstrap pattern, single-source constants

### External Research

- [Import Linter — Contract Types (layers, forbidden, independence)](https://import-linter.readthedocs.io/en/stable/contract_types.html)
- [Import Linter — Layers contract `|` and `:` separators](https://import-linter.readthedocs.io/en/v2.9/contract_types/layers/)
- [PEP 562 — Module `__getattr__` and `__dir__`](https://peps.python.org/pep-0562/)
- [PEP 810 — Explicit lazy imports (Python 3.15)](https://peps.python.org/pep-0810/)
- [structlog — Logging Best Practices](https://www.structlog.org/en/stable/logging-best-practices.html)
- [structlog — Context Variables](https://www.structlog.org/en/stable/contextvars.html)
- [unasyncd — AST-level async-to-sync code generation](https://pypi.org/project/unasyncd/)
- [Psycopg — Automatic async to sync conversion](https://www.psycopg.org/articles/2024/09/23/async-to-sync/)
- [Seth Larson — Designing Libraries for Async and Sync I/O](https://sethmlarson.dev/designing-libraries-for-async-and-sync-io)
