---
title: "Monolithic deep_review cluster decomposition into 11-module DAG package"
date: 2026-03-15
module: vertical_engines/credit/deep_review
problem_type: architectural-debt
severity: high
tags:
  - refactoring
  - modularization
  - credit-vertical
  - deep-review
  - import-architecture
  - wave-2
  - pep-562
  - structlog
related_prs:
  - 23
symptoms:
  - "~5430 LOC spread across 6 flat files with no enforced dependency boundaries"
  - "Circular import risk between deep_review helpers and service layer"
  - "~200 LOC dead code accumulated in monolithic files"
  - "Unable to enforce import-linter contracts on internal module boundaries"
  - "NTFS collision: cannot have deep_review.py file and deep_review/ directory simultaneously"
root_cause: "The deep_review cluster grew organically as 6 flat files with implicit coupling, bypassing the modular package pattern established by Wave 1 (PRs #8-19) for the other 12 credit engine packages."
---

# Wave 2: deep_review Monolith to DAG Package

## Problem

The `deep_review` cluster was the last set of flat files in `vertical_engines/credit/` — six files totaling ~5430 LOC with a monolithic orchestrator (`deep_review.py` at 2990 LOC) containing near-identical sync/async pipelines (~2400 LOC duplication), stdlib `logging` throughout, no `__init__.py`/`__all__` protection, no DAG enforcement between files, and `db.add()` in for-loops for risk flag persistence.

| File | LOC | Role |
|------|-----|------|
| `deep_review.py` | 2990 | Monolithic orchestrator (sync + async + batch) |
| `deep_review_corpus.py` | 608 | Evidence gathering, RAG retrieval |
| `deep_review_policy.py` | 723 | Hard/soft policy + decision anchor |
| `deep_review_confidence.py` | 518 | Underwriting reliability score |
| `deep_review_helpers.py` | 241 | LLM wrappers, JSON parsing |
| `deep_review_prompts.py` | 350 | Prompt construction |

## Solution

### Approach: 4-Phase Staged Extraction (Single PR #23)

**Phase 0 — Prerequisites.** Resolved `async_session_factory` binding (4 undefined references that would NameError after module split). Captured 12 golden test snapshots for deterministic submodules (confidence scoring, decision anchor, hard policy checks). Fixed circular import where `policy.py` imported `_call_openai` from the orchestrator.

**Phase 1a — Create 9 modules in staging directory.** NTFS cannot have `deep_review.py` and `deep_review/` simultaneously. Solution: create modules in a `deep_review_pkg/` staging directory first. Extracted: `models.py`, `helpers.py`, `corpus.py`, `prompts.py`, `policy.py`, `decision.py`, `confidence.py`, `persist.py`, `portfolio.py`.

**Phase 1b — Create service.py from remaining orchestrator.** Migrated stdlib `logging` to `structlog` with dot-separated event names. Converted `db.add()` loops to `db.add_all()`. Added `NEVER_RAISES_CONTRACT_VIOLATION` log prefix to defense-in-depth catches. Added `__all__` with 4 public functions.

**Phase 1c — Assemble final package.** Renamed `deep_review_pkg/` to `deep_review/`, created `__init__.py` with PEP 562 lazy imports, `git rm` the 6 flat files and staging directory. Updated all internal imports.

**Phase 1d — Wire up and enforce.** Updated external callers (only `eval_metrics.py` needed a path change — all others resolved transparently via `__init__.py`). Added import-linter `layers` contract. Validated 337 tests passing, 5/5 contracts.

### Final Package Structure

```
deep_review/
  __init__.py      # PEP 562 lazy imports, __dir__, __all__ (9 public symbols)
  models.py        # _LLM_CONCURRENCY constant (LEAF — zero sibling imports)
  helpers.py       # LLM wrappers, JSON parsing, utilities
  corpus.py        # Evidence gathering, RAG retrieval, deal context
  prompts.py       # Instrument pre-classification, prompt construction
  policy.py        # Hard/soft policy checks, policy RAG
  decision.py      # Decision anchor + legacy confidence scoring
  confidence.py    # Underwriting Reliability Score (deterministic)
  persist.py       # Eval artifact helpers (_index_chapter_citations, _build_tone_artifacts)
  portfolio.py     # Portfolio periodic reviews (ThreadPoolExecutor, per-thread sessions)
  service.py       # Main orchestrator: sync + async pipelines + batch runners
```

### 6-Layer DAG (enforced by import-linter)

```
Tier 6 (top):  service.py
Tier 5:        portfolio.py
Tier 4:        persist.py
Tier 3:        corpus | prompts | policy | decision | confidence  (independent siblings)
Tier 2:        helpers.py
Tier 1 (leaf): models.py
```

Import-linter contract in `pyproject.toml`:
```toml
[[tool.importlinter.contracts]]
name = "Deep review internal DAG"
type = "layers"
layers = [
    "service",
    "portfolio",
    "persist",
    "corpus | prompts | policy | decision | confidence",
    "helpers",
    "models",
]
containers = ["vertical_engines.credit.deep_review"]
exhaustive = true
exhaustive_ignores = ["__init__"]
```

### Key Patterns

**NTFS staging directory workaround.** On Windows (NTFS), a file `deep_review.py` and directory `deep_review/` cannot coexist. Use a staging directory (`deep_review_pkg/`), develop all modules there, then perform a single atomic rename after `git rm` of the flat file.

**PEP 562 lazy imports in `__init__.py`.** Leaf-node symbols (`confidence.py`) are eagerly imported; heavy symbols (`service.py`, `portfolio.py`) use `__getattr__` for deferred loading. `TYPE_CHECKING` block provides static analysis support. `__dir__()` returns `__all__` for runtime introspection. Matches edgar/memo reference implementations.

**`NEVER_RAISES_CONTRACT_VIOLATION` log prefix.** Defense-in-depth `try/except` blocks around sub-engine calls log with this prefix when a supposedly never-raising engine unexpectedly raises. Makes violations searchable in structured logs without masking the error.

**ORM scalar extraction before thread boundaries.** `portfolio.py` extracts `(inv.id, inv.fund_id)` tuples before `ThreadPoolExecutor` dispatch. Each thread gets its own session via `async_session_factory`. ORM objects never cross thread boundaries.

**Function-level sibling engine imports.** `service.py` imports from ~12 sibling engine packages inside function bodies (not module scope). Keeps import time O(1), prevents circular dependencies, avoids loading heavy ML dependencies for lightweight callers.

**`_build_tone_artifacts()` call cached.** Previously called twice with identical args in both sync and async paths. Now computed once and reused.

### Code Review Findings (8 agents, resolved in-PR)

| Finding | Resolution |
|---------|------------|
| ~200 LOC dead code (prompt constants, budget constants, classify function) | Removed |
| structlog event naming inconsistent (free-text vs dot-separated) | Standardized to dot-separated |
| `__dir__()` missing from `__init__.py` | Added — returns `__all__` |
| `db.add()` loop for risk flags | Changed to `db.add_all()` |
| Dead `_PORTFOLIO_REVIEW_SYSTEM` (108-line prompt literal) | Removed |
| `noqa:F401` stale re-exports in corpus/policy/prompts | Cleaned up |
| `STAGE_CRITICALITY` dict added with zero consumers | Removed (YAGNI) |
| DAG docstring said "Three-tier" but contract has 6 layers | Fixed to "Six-layer" |

### Metrics

| Metric | Before | After |
|--------|--------|-------|
| Files | 6 flat | 11 in package |
| Tests | 324 | 337 (+12 golden, +1 API smoke) |
| Dead code | ~200 LOC | 0 |
| Logging | stdlib `logging` | `structlog` throughout |
| DAG enforcement | None | import-linter `layers`, `exhaustive=true` |
| `__all__` protection | None | Every module + PEP 562 `__init__.py` |
| Import-linter contracts | 4 | 5 |

## Prevention

### Pre-Extraction Checklist

Use this before any monolith-to-package refactor:

- [ ] **NTFS check:** Will the new package directory collide with the existing filename? If yes, plan a staging directory.
- [ ] **Undefined names audit:** Run `python -c "import the_module"` in isolation. Fix every `NameError` by converting monkey-patched globals to explicit imports.
- [ ] **Call graph for circular imports:** Map every cross-function call that will span module boundaries. Extract shared utilities first.
- [ ] **Dead code sweep:** Run `vulture` or equivalent. Delete unused functions and constants before extraction.
- [ ] **Log event naming convention:** Agree on `"{package}.{module}.{action}"` format before splitting.
- [ ] **Duplicate computation scan:** Review for functions called multiple times with identical arguments. Consolidate call sites.
- [ ] **Golden test snapshots:** Capture outputs of all deterministic functions before restructuring. Assert with `rtol=1e-6`.
- [ ] **Import-linter contract:** Add contracts to `pyproject.toml` with `exhaustive=true` before merging.
- [ ] **Post-split re-export audit:** Remove all `noqa:F401`, run linter, restore only for intentional public API names.
- [ ] **Test count parity:** Test count must not decrease. New structural and golden tests expected.
- [ ] **`make check` green:** Lint + typecheck + architecture + test pass before opening the PR.

### What the Guards Protect Going Forward

**Import-linter contracts** prevent: circular dependencies, helpers importing service, models importing service, cross-vertical imports. The `exhaustive=true` flag catches any new module added without declaring its layer.

**Golden tests** prevent: silent behavior regression after extraction. Exact numerical assertions on deterministic functions (confidence score, decision anchor, hard policy checks) catch any code path drift.

**`__all__` + PEP 562** prevent: prompt IP leakage via `from module import *`, unnecessary eager loading of heavy dependency chains.

## Related Documentation

- [Wave 1: Credit Vertical Modularization](wave1-credit-vertical-modularization-MonolithToPackages-20260315.md) — The canonical reference. 12 engine packages, 8 conventions.
- [Monolith to Modular Package (EDGAR)](monolith-to-modular-package-with-library-migration.md) — Prototype package pattern with PEP 562, ThreadPoolExecutor, never-raises contract.
- [Vertical Engine Extraction Patterns](vertical-engine-extraction-patterns.md) — Foundational architecture: BaseAnalyzer ABC, ConfigService, vertical independence.
- [Phase 3: StorageClient + ADLS](phase3-storageclient-adls-dualwrite-pattern-20260315.md) — Data flow boundaries relevant to deep_review persistence.
- [Thread-Unsafe Rate Limiter (FredService)](../runtime-errors/thread-unsafe-rate-limiter-FredService-20260315.md) — Thread safety patterns applicable to portfolio.py's ThreadPoolExecutor.
- [Wave 2 Plan](../../plans/2026-03-15-refactor-credit-deep-review-modularization-wave2-plan.md) — Full plan with deepened research from 10 agents.
