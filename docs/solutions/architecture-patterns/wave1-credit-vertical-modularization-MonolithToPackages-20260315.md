---
title: "Credit Vertical Modular Alignment — Wave 1: 31 monolithic files to 12 edgar-style packages"
date: 2026-03-15
module: backend/vertical_engines/credit/
problem_type: architecture-refactoring
severity: medium
status: resolved
tags:
  - credit-vertical
  - modularization
  - edgar-pattern
  - import-linter
  - structlog
  - never-raises
  - pep562
  - golden-tests
  - deep-review
  - wave-1
related_prs:
  - "#8"   # import-linter DAG enforcement setup (PR #0 in plan)
  - "#9"   # critic/ package (PR #1)
  - "#10"  # sponsor/ package (PR #2)
  - "#11"  # kyc/ package (PR #3)
  - "#12"  # retrieval/ package (PR #4)
  - "#13"  # pipeline/ package (PR #5)
  - "#14"  # quant/ package (PR #6)
  - "#15"  # market_data/ package (PR #7)
  - "#16"  # portfolio/ package (PR #8)
  - "#17"  # deal_conversion/ package (PR #9)
  - "#18"  # underwriting/ + domain_ai/ packages (PRs #10-11)
  - "#19"  # memo/ package (PR #12) + review fix-ups
---

# Credit Vertical Modular Alignment — Wave 1

## Problem Statement

The credit vertical engine (`backend/vertical_engines/credit/`) contained 31 monolithic `.py` files migrated as-is from the legacy Netz Private Credit OS. Only the `edgar/` engine had been restructured into the target modular package pattern. The remaining engines mixed parsing, orchestration, and constants in single files with no explicit public API contracts, inconsistent error handling, stdlib `logging` instead of structlog, and no golden regression tests. This made it difficult to reason about dependency direction, safely modify individual engines, or enforce architectural layering across the ~14,500 LOC codebase.

## Symptoms

- **Flat monolithic files**: Each engine was a single 500-2000 LOC file combining constants, data structures, parsing logic, and orchestration (e.g., `ic_quant_engine.py` bundled scenarios, sensitivity, backtesting, and scoring).
- **No public API surface**: No `__init__.py` files, no `__all__` declarations. Callers imported internal functions directly, creating invisible coupling. `deep_review.py` used function-level lazy imports scattered across 30+ call sites.
- **Inconsistent error contracts**: Orchestration engines like critic silently returned partial results on failure, while deal_conversion raised bare exceptions. No uniform `status: 'NOT_ASSESSED'` sentinel.
- **No architectural enforcement**: Without import-linter, nothing prevented domain modules from importing service-layer code or creating circular dependencies.
- **stdlib logging throughout**: All engines used `import logging` instead of structlog, producing unstructured log output.
- **No regression safety net**: No golden test snapshots for engine outputs, making structural refactoring risky.

## Root Cause

Five compounding problems in the legacy file structure:

1. **Mixed concerns in single files.** Parsing logic, orchestration, constants, and domain computations coexisted in files exceeding 1000 LOC (e.g., `retrieval_governance.py` at 1326 LOC, `market_data_engine.py` at 1031 LOC). Impossible to test one concern without loading the entire file.

2. **No explicit public API contracts.** Files lacked packages, `__all__`, or any mechanism to distinguish public symbols from internal helpers. Callers imported private functions (e.g., `_classify_instrument_type`), creating invisible coupling.

3. **Inconsistent error handling.** Some engines raised, some returned dicts, some swallowed errors silently. `deep_review.py` wrapped every engine call in defensive `try/except` because there was no behavioral contract.

4. **No structured logging.** No consistent log-at-boundary discipline, no context propagation, no structured fields.

5. **Import-path fragility.** Every engine was a flat file at the same directory level. Renaming or splitting any file required updating every caller, with no automated enforcement.

## Solution

### 1. The Edgar-Style Package Pattern

Every credit engine was restructured into a directory-based package following a strict DAG:

```
engine_name/
  __init__.py        # Public API surface + __all__
  models.py          # Dataclasses, enums, constants (LEAF — zero sibling imports)
  [domain_a].py      # Imports only models.py
  [domain_b].py      # Imports only models.py
  service.py         # Orchestrator — imports all domain modules
```

Dependency direction is always downward: `models.py` -> domain modules -> `service.py` -> `__init__.py`. No domain module ever imports `service.py`. No reverse imports.

Packages without orchestration logic (`underwriting/`, `retrieval/`) omit `service.py` — `__init__.py` re-exports directly. Packages with trivially small codebases (`sponsor/`) omit `models.py` when there are no typed models.

### 2. The 8 Conventions

1. **No backward-compat shims.** All callers updated in the same PR. Old import paths deleted, not aliased.

2. **Error contract per engine type.** Never-raises (orchestration engines: critic, sponsor, kyc, market_data, pipeline, portfolio, memo, retrieval) return `status: 'NOT_ASSESSED'` on failure with `exc_info=True` in structlog. Raises-on-failure (transactional: deal_conversion, underwriting, quant) propagate exceptions.

3. **Dict return at API boundary.** `@dataclass(frozen=True, slots=True)` internally. Custom `_to_dict()` at service boundary — not blanket `dataclasses.asdict()` (expensive recursive deepcopy).

4. **Conditional PEP 562 lazy imports.** Only for heavy deps: market_data (httpx), memo (openai). Lightweight engines use standard imports since their deps are already warm in `sys.modules`.

5. **Golden tests.** Capture outputs before restructuring, assert after with `rtol=1e-6`. Trivial pure functions use standard unit tests.

6. **Dataclass conventions.** `@dataclass(frozen=True, slots=True)` for return-type models. Do NOT formalize plain dicts into dataclasses during this refactor (scope creep).

7. **structlog everywhere.** `logger = structlog.get_logger()` in every module. Log at function boundaries only.

8. **Domain module import rules.** Each imports `models.py` or lower-tier siblings. Cross-package imports documented (e.g., `kyc/entity_extraction.py` -> `sponsor.person_extraction`).

### 3. Serial PR Strategy

12 PRs executed strictly serially — each merged before the next branched. Required because:
- `deep_review.py` (2600+ LOC orchestrator) is touched by every PR (import path updates)
- `test_vertical_engines.py::EXPECTED_MODULES` updated in every PR
- No backward-compat shims means parallel branches create immediate conflicts

The `deep_review.py` caller map was fully documented in the plan — every import site mapped to a specific PR number.

### 4. Import-Linter DAG Enforcement

PR #8 (preparatory) installed `import-linter` before any engine PR. Four contracts:

1. **Vertical independence** — credit and wealth must not import each other
2. **Models must not import service** — enforces leaf-node constraint
3. **Domain helpers must not import service** — broader DAG enforcement
4. **Quant-agnostic** — quant services must not import wealth domain models

`make architecture` runs `lint-imports` and is part of the `make check` gate.

### 5. Key `__init__.py` Patterns

**Standard imports** (lightweight engines — critic, sponsor, deal_conversion, etc.):

```python
"""IC Critic Engine — adversarial review.

Error contract: never-raises (orchestration engine).
"""
from vertical_engines.credit.critic.classifier import classify_instrument_type
from vertical_engines.credit.critic.models import CriticVerdict, INSTRUMENT_TYPE_PROFILES
from vertical_engines.credit.critic.service import critique_intelligence, build_critic_packet

__all__ = [
    "critique_intelligence", "build_critic_packet",
    "classify_instrument_type", "CriticVerdict", "INSTRUMENT_TYPE_PROFILES",
]
```

**PEP 562 lazy imports** (heavy-dependency engines — memo, market_data):

```python
from typing import TYPE_CHECKING, Any
from vertical_engines.credit.memo.models import CHAPTER_REGISTRY, ToneReviewResult

if TYPE_CHECKING:
    from vertical_engines.credit.memo.service import generate_memo_book as generate_memo_book
    from vertical_engines.credit.memo.chapters import generate_chapter as generate_chapter
    # ...

__all__ = ["CHAPTER_REGISTRY", "ToneReviewResult", "generate_memo_book", "generate_chapter", ...]

def __getattr__(name: str) -> Any:
    if name in ("generate_memo_book", "async_generate_memo_book"):
        from vertical_engines.credit.memo.service import generate_memo_book, async_generate_memo_book
        return {"generate_memo_book": generate_memo_book, "async_generate_memo_book": async_generate_memo_book}[name]
    # ... other groups
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

Three layers: (a) lightweight models imported eagerly, (b) `TYPE_CHECKING` block for IDE support, (c) `__getattr__` defers heavy imports until first access.

## Final Package Inventory

| Package | Files | PEP 562 | Error Contract | LOC (pre) |
|---|---|---|---|---|
| critic | 7 | No | never-raises | 766 |
| sponsor | 3 | No | never-raises | 390 |
| kyc | 8 | No | never-raises | 721 |
| retrieval | 7 | No | never-raises | 1326 |
| pipeline | 9 | No | never-raises | 1415 |
| quant | 8 | No | raises-on-failure | 1390 |
| market_data | 8 | Yes | never-raises | 1031 |
| portfolio | 9 | No | never-raises | 797 |
| deal_conversion | 4 | No | raises-on-failure | 316 |
| underwriting | 3 | No | raises-on-failure | 249 |
| domain_ai | 2 | No | never-raises | 270 |
| memo | 8 | Yes | never-raises | 4203 |

## Code Review Findings (Fixed)

Multi-agent review (8 agents) found 7 items, all resolved:

| # | Severity | Finding | Fix |
|---|---|---|---|
| 012 | P2 | `call_openai_fn: Any` should use Protocol | Added `CallOpenAiFn` type annotations |
| 013 | P2 | 14x redundant `json.dumps` per memo | Compute once, pass as parameter |
| 014 | P2 | `compress_to_budget` dead code | Deleted (zero callers) |
| 015 | P2 | Gap-text extraction duplicated 4x | Extracted `_extract_gap_text` helper |
| 016 | P3 | market_data missing TYPE_CHECKING | Added TYPE_CHECKING block |
| 017 | P3 | domain_ai/engine.py naming inconsistency | Renamed to service.py |
| 018 | P3 | Import-linter contracts too narrow | Added broader domain→service contract |

## Prevention Strategies

### Architectural Drift Prevention
Enforce the DAG continuously via `make check` including `lint-imports`. New verticals must add contracts before the first line of business logic. No PR merges without green import-linter output.

### Eager Coupling Prevention
PEP 562 lazy imports only for packages with >50ms import cost. Everything else stays explicit. Never instantiate asyncio primitives (`Semaphore`, `Lock`, `Event`) at module scope — create lazily inside async functions.

### Serial PR Discipline
Modularization PRs touching shared files must be strictly serialized. Parallel only for disjoint file sets.

### Type Hygiene
Use `Protocol` types for interface boundaries. Never use `Any` in public API signatures.

### Dead Code Discipline
Every PR includes a "deletion audit" — functions made unreachable are removed in the same PR.

## Checklist for Future Modularizations

### Pre-Work
- [ ] Map shared files that create serialization constraints
- [ ] Write import-linter contracts before starting
- [ ] Capture golden test snapshots
- [ ] Add new package to `EXPECTED_MODULES`
- [ ] Document error contract per engine

### During Each PR
- [ ] `make check` passes (lint + architecture + typecheck + test)
- [ ] Golden tests produce identical output
- [ ] No `Any` types in public signatures — use Protocol
- [ ] No module-level asyncio primitives
- [ ] All loggers use `structlog.get_logger()`
- [ ] PEP 562 only for heavy deps, not universally
- [ ] Deletion audit complete
- [ ] `__init__.py` re-exports match previous public API exactly

### Post-Merge
- [ ] Pull main before branching next PR
- [ ] `make check` on fresh main
- [ ] `EXPECTED_MODULES` passes with updated list

## Related Documentation

### Primary Documents
- **Brainstorm:** `docs/brainstorms/2026-03-15-credit-vertical-modular-alignment-brainstorm.md`
- **Plan:** `docs/plans/2026-03-15-refactor-credit-vertical-modular-alignment-wave1-plan.md`

### Related Solutions
- `docs/solutions/architecture-patterns/monolith-to-modular-package-with-library-migration.md` — THE canonical edgar reference. Documents the 8 patterns Wave 1 replicates.
- `docs/solutions/architecture-patterns/vertical-engine-extraction-patterns.md` — Phase 4 extraction that created the file structure Wave 1 modularizes. Backward-compat re-exports, async-to-sync patterns.
- `docs/solutions/runtime-errors/thread-unsafe-rate-limiter-FredService-20260315.md` — Thread safety pattern for shared mutable state. Applies to market_data/ (FredService).
- `docs/solutions/logic-errors/credit-stress-grading-boundary-StressSeverity-20260315.md` — Golden test boundary patterns. Referenced by quant/ and market_data/ phases.
- `docs/solutions/logic-errors/window-days-ignored-InsiderSignals-20260315.md` — Unused-parameter prevention. Motivates parameter contract testing.
- `docs/solutions/runtime-errors/fred-api-key-case-mismatch-MarketDataEngine-20260315.md` — Pydantic Settings case-sensitivity gotcha. Relevant to market_data/.
