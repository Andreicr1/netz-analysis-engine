---
date: 2026-03-15
topic: credit-vertical-modular-alignment
---

# Credit Vertical — Modular Package Alignment

## What We're Building

A systematic refactoring of all credit vertical engines (`backend/vertical_engines/credit/`) from monolithic single-file modules to edgar-style modular packages. The edgar package (9 files, 2416 LOC) is the canonical pattern — every engine gets the same treatment: `models.py` leaf → domain modules → `service.py` orchestrator → `__init__.py` with PEP 562 lazy imports.

The primary goal is **architecture alignment** — making engines maintainable, testable, and structurally consistent. Scientific skills may be applied opportunistically during each engine's modularization when a clear analytical improvement exists, but the PR scope must remain structure-first.

## Why This Approach

**Approaches considered:**

1. **Edgar package pattern for all** — Full subdirectory package per engine
2. **Quant flat extraction** — Keep top-level files, extract helpers alongside
3. **Hybrid size-based** — Packages for >500 LOC, flat for smaller

**Chosen: Edgar package pattern for all.** Rationale:
- Consistency beats micro-optimization. One pattern to learn, one to review.
- Even small engines benefit from explicit `__init__.py` API contracts.
- Packages naturally grow; starting flat means refactoring twice.
- The edgar solution doc (`docs/solutions/architecture-patterns/monolith-to-modular-package-with-library-migration.md`) is the proven reference.

## Key Decisions

1. **Edgar package is the canonical pattern** — `models.py` (leaf) → domain modules → `service.py` (orchestrator) → `__init__.py` (PEP 562 lazy imports + `__all__`). Every engine follows this DAG.

2. **Wave 1: All non-deep_review engines** — deep_review cluster (2990 LOC + 5 satellite files) is the biggest beast with the most interconnections. Everything else goes first.

3. **No backward-compat shims** — Update all callers to new import paths in the same PR. Cleaner, no tech-debt accumulation.

4. **Full standardization per engine:**
   - Package structure (models → domain → orchestrator)
   - Never-raises contract (`result['warnings']`, `exc_info=True`)
   - structlog throughout
   - Dict return at API boundary
   - Golden tests (output regression with `rtol=1e-6` where applicable)
   - PEP 562 lazy imports for heavy dependencies

5. **Scientific skills applied opportunistically, scoped per PR** — During each engine's `/ce:plan`, check if scientific skills add concrete analytical value. If yes, integrate in the same PR only when the improvement is small and well-defined. Large analytical upgrades get their own separate PR after the structural refactor lands.

6. **Wave 2: deep_review cluster** — After all other engines are aligned, tackle deep_review.py + corpus + policy + confidence + helpers + prompts as a single coordinated effort.

## Engine Inventory & Proposed Package Groupings

### Wave 1 — Independent Engines (modularize in any order)

| Current File(s) | Proposed Package | LOC | Notes |
|---|---|---|---|
| `ic_critic_engine.py` | `critic/` | 765 | Instrument profiles dict → `profiles.py`, scoring → `scoring.py` |
| `sponsor_engine.py` | `sponsor/` | ~350 | Person analysis, key-man risk |
| `pipeline_engine.py` + `pipeline_intelligence.py` | `pipeline/` | ~1380 | Discovery + aggregation + single-deal memo |
| `ic_quant_engine.py` + `credit_scenarios.py` + `credit_sensitivity.py` + `credit_backtest.py` | `quant/` | ~1560 | Already partially extracted during quant parity; complete the package |
| `market_data_engine.py` | `market_data/` | 1030 | Bloomberg, FRED, YieldBook integrations |
| `memo_book_generator.py` + `memo_chapter_engine.py` + `memo_chapter_prompts.py` + `memo_evidence_pack.py` + tone + batch | `memo/` | ~4070 | Largest Wave 1 package. See **memo/ DAG** below. |
| `portfolio_intelligence.py` | `portfolio/` | 796 | Portfolio monitoring + alerts |
| `kyc_pipeline_screening.py` + `kyc_models.py` + `kyc_client.py` | `kyc/` | ~720 | Already has models extracted; complete the package |
| `retrieval_governance.py` | `retrieval/` | 1326 | Evidence governance + authority scoring |
| `deal_conversion_engine.py` | `deal_conversion/` | ~260 | Domain-specific conversion logic, standalone |
| `underwriting_artifact.py` | `underwriting/` | ~220 | Domain concept, standalone |
| `tone_normalizer.py` | Absorb into `memo/tone.py` | ~280 | Memo-exclusive caller set |
| `batch_client.py` | Absorb into `memo/batch.py` | ~230 | Exclusively used by memo_book_generator |
| `domain_ai_engine.py` | TBD at plan time | ~270 | If dispatcher → absorb into `deep_review/`; if own logic → standalone |

> **Absorption Criteria (firm, not per-plan):**
>
> **Absorb** (no standalone package) when ALL of:
> - LOC < 300
> - Single-purpose, no subdomain of its own
> - Caller set is exclusively one target package
>
> **Create standalone package** even if < 300 LOC when ANY of:
> - Has callers in multiple engines
> - Has justifiable `models.py` of its own
> - Foreseeable growth (e.g., kyc will expand in future phases)
>
> Applied to current inventory:
> - `tone_normalizer.py` → absorb into `memo/tone.py` (memo-exclusive)
> - `batch_client.py` → absorb into `memo/batch.py` (exclusively used by memo_book_generator)
> - `deal_conversion_engine.py` → standalone `deal_conversion/` (domain-specific conversion logic, not a utility)
> - `underwriting_artifact.py` → standalone `underwriting/` (domain concept, not auxiliary)
> - `domain_ai_engine.py` → evaluate at plan time: if dispatcher only, absorb into `deep_review/`; if own logic, standalone package

### memo/ Internal DAG (mandatory for `/ce:plan`)

The memo/ package is the largest and riskiest in Wave 1. This DAG must be enforced to prevent circular imports:

```
memo/
  models.py          ← ChapterResult, MemoOutput, EvidencePack dataclasses (LEAF)
  prompts.py         ← templates + constants (was memo_chapter_prompts.py) — imports models only
  evidence.py        ← was memo_evidence_pack.py — imports models only
  tone.py            ← was tone_normalizer.py — imports models only
  batch.py           ← was batch_client.py — imports models only
  chapters.py        ← was memo_chapter_engine.py — imports models, prompts, evidence
  service.py         ← was memo_book_generator.py — imports ALL above (sole orchestrator)
  __init__.py        ← exposes generate_memo_book(), ChapterResult
```

Existing `credit/prompts/` dir (empty `__init__.py` only) is absorbed here.

### Wave 2 — deep_review Cluster

| Current File(s) | Proposed Package | LOC | Notes |
|---|---|---|---|
| `deep_review.py` + `deep_review_corpus.py` + `deep_review_policy.py` + `deep_review_confidence.py` + `deep_review_helpers.py` + `deep_review_prompts.py` | `deep_review/` | ~5840 | 13-chapter IC memo pipeline. Needs careful chapter isolation. |

### Wave 2 — Prompt Relocation Decision

Today `credit/prompts/` has Jinja2 `.j2` templates at the vertical directory level. When `deep_review/` becomes a package, prompts used exclusively by deep review (ch01–ch14, critic, evidence_law, tone_pass) must move.

**Decision: Option A — prompts move into `deep_review/prompts/`** (colocated with the package that uses them). This requires updating `ProfileLoader` search path to include `vertical_engines/{vertical}/{package}/prompts/`. Since ProfileLoader is not yet implemented (Sprint 3+), this can be coordinated without backward-compat risk. Document in the Wave 2 plan.

### Already Done

| Package | LOC | Status |
|---|---|---|
| `edgar/` | 2416 | Complete — the reference implementation |

## Edgar Pattern Checklist (Per Engine)

Each engine modularization must satisfy:

```
[ ] models.py — dataclasses + enums, zero sibling imports (leaf node)
[ ] Domain modules — each imports only models.py
[ ] service.py — sole orchestrator, fans out to domain modules
[ ] __init__.py — PEP 562 lazy imports + TYPE_CHECKING + __all__
[ ] Never-raises contract — all errors in result['warnings']
[ ] structlog — logger = structlog.get_logger() in every module
[ ] Dict return at API boundary — typed internally, dict at surface
[ ] Golden tests — output regression for key functions
[ ] All callers updated — no backward-compat re-exports
[ ] Dependency DAG verified — no circular imports
[ ] make check passes — lint + typecheck + test
```

## Scientific Skills Applicability Map

Preliminary mapping — validated during each engine's `/ce:plan`. Only high-confidence matches listed:

| Engine | Candidate Skills | Potential Application | Confidence |
|---|---|---|---|
| `quant/` | statsmodels, pymc, shap | Bayesian parameter estimation, feature importance | High — direct domain match |
| `critic/` | hypothesis-generation, statistical-analysis | Structured hypothesis for devil's advocate | High — core analytical upgrade |
| `market_data/` | fred-economic-data, alpha-vantage, polars | FRED integration, faster DataFrame ops | High — replaces manual HTTP |
| `portfolio/` | aeon | Time series anomaly detection for alerts | Medium — needs evaluation |
| `pipeline/` | scikit-learn | Deal screening ML scoring | Medium — needs evaluation |
| `retrieval/` | transformers | Semantic similarity for evidence ranking | Medium — embedding model choice matters |
| `deep_review/` | hypothesis-generation, what-if-oracle | IC memo hypothesis framework, scenarios | High — Wave 2 scope |

## Execution Strategy

**Each engine = 1 PR.** Small, reviewable, independently mergeable.

**Recommended sequence (Wave 1):**

| # | Package | Rationale |
|---|---|---|
| 1 | `critic/` | Smallest self-contained engine. Build confidence with the pattern. |
| 2 | `sponsor/` | Simple, good second rep. |
| 3 | `kyc/` | Already has `kyc_models.py` extracted; completion is fast. |
| 4 | `retrieval/` | Independent, well-defined domain. |
| 5 | `pipeline/` | `pipeline_engine` + `pipeline_intelligence` together. |
| 6 | `quant/` | Already has `credit_sensitivity` + `credit_scenarios` + `credit_backtest`; complete the package. |
| 7 | `market_data/` | After quant/ — depends on quant outputs. **Plan must specify:** imports point to `quant.models` and `quant.service`, not the old flat `ic_quant_engine.py`. |
| 8 | `portfolio/` | Independent but uses portfolio domain models. |
| 9 | `deal_conversion/` | Small standalone. |
| 10 | `underwriting/` | Small standalone. |
| 11 | `memo/` | Largest Wave 1 package, most interdependencies — do last. |

**Wave 2:** `deep_review/` — after all Wave 1 engines are merged.

**Per-engine workflow:**
1. Golden tests first — capture current outputs as regression tests before touching structure
2. Scientific skill check — invoke relevant skills during `/ce:plan`
3. Implement package structure
4. Review with `/ce:review` — multi-agent review catches bugs (see "Bugs Caught" in solution doc)

## Open Questions

_None — all key decisions resolved during brainstorm._

## Next Steps

→ `/ce:plan` for the first engine (recommend starting with `critic/` — medium complexity, self-contained, clear internal structure)
