---
title: "feat: EDGAR Upgrade with edgartools (Phase B)"
type: feat
status: active
date: 2026-03-15
origin: docs/brainstorms/2026-03-15-credit-engine-analytical-upgrade-brainstorm.md
deepened: 2026-03-15
---

# feat: EDGAR Upgrade with edgartools (Phase B)

## Enhancement Summary

**Deepened on:** 2026-03-15
**Review agents used:** architecture-strategist, security-sentinel, performance-oracle, kieran-python-reviewer, code-simplicity-reviewer, pattern-recognition-specialist, best-practices-researcher, framework-docs-researcher, edgartools skill, learnings-researcher, spec-flow-analyzer

### Critical Changes from Review

1. **Split into `edgar/` package, not single file** — replacing a 1561 LOC monolith with a 1600 LOC monolith defeats the purpose. Split into 7 focused modules ≤300 LOC each (Python reviewer + architecture strategist agree)
2. **`pandas` and `pyarrow` are NEW dependencies** — plan incorrectly claimed they were already in the stack. They are NOT in `pyproject.toml`. This adds ~100MB to the installed environment and native C++ extensions. Pin `edgartools>=5.23,<6.0` (architecture reviewer verified via pyproject.toml)
3. **HTTP request explosion: 3-4 → 10-60 per entity** — Form 4 `filing.obj()` downloads each filing individually (~50 requests at head(50)). Parallelize entity processing with `ThreadPoolExecutor(max_workers=3)` inside `fetch_edgar_multi_entity()` and filter Form 4 by `filing_date` before calling `filing.obj()` (performance oracle)
4. **Add Redis distributed rate limiter** — multi-process workers each have independent pyrate-limiter. With 3 workers = 30 req/s from same IP, exceeding SEC 10 req/s limit. Redis sliding window counter costs ~5 lines, prevents IP blocking (security sentinel)
5. **Add CIK resolution confidence scoring** — edgartools `find(name)` fuzzy matching can't disambiguate "Ares Capital Corporation" vs "Ares Management Partners". Add `rapidfuzz.fuzz.ratio()` threshold ≥70% and `resolution_confidence: float` field (security sentinel + edgartools skill)
6. **Going concern: add negation detection** — current keyword scan produces false positives on "no substantial doubt" and "doubt has been resolved". Add 3-tier classification: CONFIRMED / MITIGATED / NONE (best practices researcher)
7. **`nest-asyncio` risk** — edgartools dependency pulls `nest-asyncio` which patches the running event loop. Could interfere with uvicorn's event loop. Monitor for "already running" errors (framework docs researcher)

### Design Decisions Revised After Review

| Original Decision | Revised Decision | Rationale |
|---|---|---|
| Single `edgar_service.py` (1600+ LOC) | `edgar/` package with 7 modules (≤300 LOC each) | Replacing a monolith with a monolith defeats the purpose (Python reviewer) |
| `FinancialRatios` dataclass (11 fields) | Delete class; keep `ratios: dict[str, float \| None]` with only 4 credit-relevant ratios | Only 2 ratios currently used (leverage, NII coverage); add ICR + DSCR only. Others are YAGNI (simplicity reviewer) |
| Dual-use schema (LLM context + Phase C inputs) | Design for LLM context only | Phase C doesn't exist yet; refactor cost is near zero when it arrives (simplicity reviewer) |
| `edgartools>=5.23` (no upper bound) | `edgartools>=5.23,<6.0` | Prevent major version surprises; v5.x has had breaking changes (security sentinel) |
| Character-based truncation `_truncate_edgar_context(str)` | Section-level truncation: build incrementally with budget tracking | Character slicing breaks mid-table/mid-heading; operate on semantic sections (architecture + Python reviewer) |
| Re-export wrapper at `ic_edgar_engine.py` | Delete old file; update 3 import statements directly | Only 2 files import from it (deep_review.py ×2, test_vertical_engines.py). Not worth a compatibility shim (simplicity reviewer) |
| 6 implementation phases | 5 phases (merge CIK+financials; keep Form 4 separate but optional) | CIK validation requires checking financials; cleanup folded into integration (simplicity reviewer) |
| Trust edgartools rate limiting alone | Redis distributed rate limiter from day one | Multi-process SEC compliance; infrastructure (Redis) already exists (security sentinel) |
| `fetch_edgar_data()` returns `EdgarEntityResult` dataclass | Returns `dict[str, Any]` (dataclasses internally, `dataclasses.asdict()` at API boundary) | Backward compat: `build_edgar_multi_entity_context()` accesses results via `r.get("status")` dict-style (pattern recognition) |
| `edgar_service.py` naming | `edgar/` package (modules inside follow `*_engine.py` convention would be wrong for a package; use descriptive names) | Service wraps external library; package eliminates naming convention conflict (pattern recognition) |
| `InsiderSignal.signal_type: str` | `InsiderSignalType(str, Enum)` + `SignalSeverity(str, Enum)` | Matches `CVStrategy` pattern in `credit_backtest.py`; prevents typos (Python reviewer) |
| Sequential entity processing | `ThreadPoolExecutor(max_workers=3)` inside `fetch_edgar_multi_entity()` | 2-3x reduction in wall-clock time (40-60s → 15-25s); pyrate-limiter is thread-safe (performance oracle) |

---

## Overview

Replace the hand-rolled `ic_edgar_engine.py` (1561 LOC, manual HTTP + XBRL parsing) with the `edgartools` library for SEC EDGAR data access. This unlocks structured financial statements (income/balance/CF, multi-period), Form 4 insider trading signals, and automatic ratio calculation — enriching IC memo chapters 4 (Sponsor), 10 (Covenants/Financial Metrics), and 12 (Peers) with actual public financials instead of point-in-time XBRL concept extractions.

Phase B of the Credit Engine Analytical Upgrade (see brainstorm: `docs/brainstorms/2026-03-15-credit-engine-analytical-upgrade-brainstorm.md`). Follows the completed Phase A (Credit Quant Architecture Parity).

## Problem Statement

| Issue | Impact |
|-------|--------|
| `ic_edgar_engine.py` is 1561 LOC of hand-rolled HTTP, rate limiting, XBRL parsing | High maintenance burden; fragile against SEC API changes |
| Manual XBRL concept extraction returns point-in-time metrics only | No multi-period financial statement view (income/balance/CF) |
| No insider trading data (Form 4) | Missing early-warning signals for credit events |
| 4-tier CIK resolution with offline blob index | Requires separate `build_edgar_index.py` worker + blob storage infrastructure |
| Manual XBRL deduplication logic (frame-key filtering) | Fragile; misses edge cases in restated filings |
| BDC/REIT and AM Platform metrics are separate code paths with hardcoded concept lists | Cannot handle entities that don't fit either template; custom XBRL extensions (AUM, FRE, DE) require fuzzy label search |
| Financial ratios manually calculated (only leverage + NII coverage) | Missing ICR, DSCR for credit analysis |
| User-Agent still says "Previse Capital" | SEC compliance: must identify current application |
| Going concern scan has false positives | "No substantial doubt" and "doubt has been resolved" trigger false alarms |

## Proposed Solution

### Architecture After Upgrade

```
vertical_engines/credit/
  edgar/                            ← NEW PACKAGE (replaces ic_edgar_engine.py)
    __init__.py                     ← re-exports public API (~20 LOC)
    models.py                       ← EdgarEntityResult, EdgarMultiEntityResult, enums (~100 LOC)
    cik_resolver.py                 ← resolve_cik(), blob fallback, confidence scoring (~200 LOC)
    financials.py                   ← FinancialStatements, XBRLS extraction, ratios (~300 LOC)
    insider_signals.py              ← InsiderSignal, Form 4 detection (~200 LOC)
    entity_extraction.py            ← extract_searchable_entities() — copied verbatim (~150 LOC)
    service.py                      ← fetch_edgar_data(), fetch_edgar_multi_entity() (~300 LOC)
    context_serializer.py           ← build_edgar_multi_entity_context(), truncation (~250 LOC)
    going_concern.py                ← check_going_concern() with negation detection (~100 LOC)

  ic_edgar_engine.py                ← DELETED (imports updated directly in deep_review.py)
  deep_review.py                    ← UPDATED: 3 import statements changed
  prompts/evidence_law.j2           ← UPDATED: expanded attribution rules
```

### Research Insights: Module Organization

**Best practice (Python reviewer):** Each module has a single responsibility, is independently testable, and stays under 300 LOC. The `__init__.py` provides the same public API surface, so `deep_review.py` imports remain clean:

```python
# deep_review.py — clean import from package
from vertical_engines.credit.edgar import (
    fetch_edgar_multi_entity,
    build_edgar_multi_entity_context,
    extract_searchable_entities,
)
```

### Key Design Decisions

1. **Hybrid CIK resolution with confidence scoring** (SpecFlow Gap #1 + security review)
   - **Primary:** `Company(ticker)` for ticker-based lookup (fastest, most reliable). Always check `company.not_found` property — edgartools may return an object with `not_found=True` instead of raising
   - **Secondary:** `find(name)` for fuzzy name matching (replaces EFTS fallback). Validate match quality with `rapidfuzz.fuzz.ratio()` ≥ 70% threshold
   - **Fallback:** Keep blob index for offline-first resolution when edgartools network calls fail
   - **Confidence field:** `resolution_confidence: float` on result — consumers can filter low-confidence matches
   - **Why confidence scoring:** edgartools `find()` uses rapidfuzz internally but has NO special logic for disambiguating financial names sharing "Capital", "Partners", "Fund", "Management". "Ares Capital Corporation" vs "Ares Management Partners" would both score high for "Ares Capital" (framework docs researcher)

   ### Research Insights: CIK Resolution

   ```python
   from rapidfuzz import fuzz

   def _resolve_cik_edgartools(
       entity_name: str, ticker: str | None = None,
   ) -> CikResolution:
       # Tier 1: ticker (deterministic, sub-second)
       if ticker:
           company = Company(ticker.strip().upper())
           if not company.not_found:  # MUST check property, not just exception
               return CikResolution(
                   cik=str(company.cik).zfill(10),
                   company_name=company.name,
                   method="ticker",
                   confidence=1.0,
               )
       # Tier 2: fuzzy name search with confidence validation
       results = find(entity_name)
       if results:
           best = results[0]
           similarity = fuzz.ratio(entity_name.lower(), best.name.lower()) / 100.0
           if similarity >= 0.70:
               return CikResolution(
                   cik=str(best.cik).zfill(10),
                   company_name=best.name,
                   method="fuzzy",
                   confidence=similarity,
               )
       return CikResolution(cik=None, company_name=None, method="not_found", confidence=0.0)
   ```

   **Edge case (edgartools skill):** `Company(ticker)` on first call loads SEC's `company_tickers.json` (~2MB, ~200-500ms). Cached thereafter. This cold-start is per-process and amortized.

2. **Structured financials: XBRLS for multi-period, EntityFacts as BDC fallback**
   - Use `company.get_filings(form="10-K", amendments=False).head(5)` → `XBRLS.from_filings()`
   - **BDC fallback:** XBRLS has no BDC-specific taxonomy support. When `XBRLS.from_filings()` fails to resolve statements, fall back to `company.get_facts()` (EntityFacts API) which uses SEC's pre-parsed facts (framework docs researcher)
   - **AM Platform metrics:** AUM, FRE, DE are custom XBRL concepts (NOT us-gaap). Use `facts.query().by_label("Assets Under Management", fuzzy=True)` for cross-taxonomy search (edgartools skill)
   - **Method naming caution:** On `StitchedStatements` (from XBRLS) it's `cashflow_statement()`. On single `Statements` (from XBRL) it's `cash_flow_statement()`. Test both paths (edgartools skill)
   - Preserve provenance: `accession_number`, `filing_date`, `form_type` from each filing
   - **Why `amendments=False`:** Amended filings (10-K/A) may have incomplete financials that break multi-period stitching

   ### Research Insights: Financial Extraction

   - **XBRLS memory:** Each 10-K XBRL instance = 5-50MB. For 5 filings: 25-250MB peak per entity. Acceptable for single-entity sequential processing. Released after each entity completes (performance oracle)
   - **EntityFacts `get_fact()` returns most recent regardless of form type** — may return 10-Q value instead of 10-K annual. Use `facts.query().by_form_type("10-K").latest(1)` for annual-specific queries (edgartools skill)
   - **Extract data before crossing thread boundary** — convert DataFrames to plain dicts inside the `to_thread()` call. Never pass pandas objects across async boundaries (learnings researcher: Pattern D)

3. **Form 4 insider trading: conservative with date-filtered HTTP optimization** (SpecFlow Gap #4 + performance oracle)
   - **HTTP optimization (performance oracle critical finding):** Each `filing.obj()` on a Form 4 downloads and parses the filing XML (~100-200ms each). `head(50)` = ~6 seconds per entity. **Fix:** Filter by `filing.filing_date` from the filing index metadata (available without downloading) before calling `filing.obj()`. Only download filings within the 365-day lookback window. Reduces to ~10-15 filings per entity in practice
   - **Signal criteria (credit-relevant):**
     - Aggregate insider **net selling** > 10% of total holdings within trailing 90 days
     - 3+ distinct insiders selling within 30 days (cluster signal)
     - Any C-suite sale > $1M (executive exodus signal)
   - **Exclusions:**
     - 10b5-1 plan transactions — new SEC Rule (Feb 2023 amendments) added a Form 4 checkbox indicating whether transaction was pursuant to a 10b5-1 plan. Parse this field first; fall back to footnote text search for "10b5-1" (best practices researcher)
     - Transaction code "F" (tax withholding on RSU vesting) — NOT discretionary selling
     - Transaction code "G" (gifts) — not market activity
     - Option exercises with immediate hold (exercise + same-day acquisition)
   - **Entity scope:** Form 4 searched only for DIRECT TARGET and sponsor/manager roles
   - **Form 4 amendments (4/A):** edgartools has NO supersession tracking. When form type is "4/A", implement own logic to identify and replace superseded filings by same issuer/owner (framework docs researcher)
   - **Enums for type safety:**
     ```python
     class InsiderSignalType(str, Enum):
         NET_SELLING_THRESHOLD = "net_selling_threshold"
         CLUSTER_SELLING = "cluster_selling"
         EXECUTIVE_SALE = "executive_sale"

     class SignalSeverity(str, Enum):
         WATCH = "watch"
         ELEVATED = "elevated"
         CRITICAL = "critical"
     ```

4. **Non-fatal exception mapping with explicit httpx.HTTPStatusError** (SpecFlow Gap #10 + architecture review)
   - All edgartools calls wrapped in try/except with exception classification:
     - `CompanyNotFoundError` → warning, skip entity. Also check `company.not_found` property
     - `NoCompanyFactsFound` → warning, skip financials
     - `XBRLFilingWithNoXbrlData` → warning, fall back to EntityFacts or filing.text()
     - `httpx.TimeoutException` → warning, use cached data
     - `httpx.HTTPStatusError` → warning with HTTP status code ("SEC returned HTTP {status_code} — possible rate limiting or IP block"). Distinguishes 403 (IP blocked) from 500 (server error)
     - `Exception` (catch-all) → warning with `exc_info=True` in structlog (not in warning string — separate ops-facing traceback from user-facing message)
   - Contract preserved: `fetch_edgar_data()` **never raises** — all errors in `result["warnings"]`

5. **Going concern: 3-tier classification with negation detection** (SpecFlow Gap #5 + best practices researcher)
   - **False positive problem (current):** Keywords like "going concern" trigger on "no substantial doubt about the company's ability to continue as a going concern"
   - **Solution:** 3-tier classification:
     - `CONFIRMED` — keyword found WITHOUT negation in auditor report section
     - `MITIGATED` — keyword found with management mitigation language ("plans to alleviate", "mitigate the conditions")
     - `NONE` — keyword not found, or found only with negation ("no substantial doubt", "doubt has been resolved")
   - Keep the 2-pass scan (auditor report → broad) using `filing.text()` from edgartools

   ### Research Insights: Going Concern Detection

   ```python
   _GOING_CONCERN_NEGATORS = [
       "no substantial doubt", "does not raise substantial doubt",
       "no longer raise substantial doubt", "has been alleviated",
       "doubt has been resolved", "does not believe",
   ]
   # If any negator found within 200 chars of the keyword match → classify as NONE
   ```

   - **Additional keywords (ASC 205-40):** Add "ability to meet obligations as they become due", "recurring losses from operations", "material uncertainty related to going concern" (IFRS language used by some US filers) (best practices researcher)

6. **Token budget: section-level truncation with sub-caps** (SpecFlow Gap #6 + architecture + security review)
   - Build context incrementally in priority order, tracking character budget
   - Stop adding sections when budget exhausted — never build a 48KB string to discard two-thirds
   - **Cap:** 12KB total (revised down from 16KB — financial data has higher token density than prose, ~5-6 tokens per 4 chars vs ~4 tokens per 4 chars for text)
   - **Sub-cap:** Insider signals max 3KB within the 12KB total
   - **Priority order:** direct target full → recent financials → insider signals → related entity (most recent period only) → historical periods
   - Log truncation events with percentage metrics

7. **Rate limiting: Redis distributed limiter from day one** (SpecFlow Gap #2 + security sentinel)
   - edgartools' `pyrate-limiter` is process-global (thread-safe within a process)
   - **Multi-process gap:** With 3 workers = 30 req/s from same IP, 3x over SEC limit
   - **Solution:** Redis sliding window counter: `edgar:rate:{second}` key with TTL=2s, max=8 (leaving 2 req/s headroom)
   - Redis already in the stack (`REDIS_URL` in `.env.example`)
   - ~5 lines of code in a `_distributed_rate_check()` function called before each entity batch

8. **Parallel entity processing within `fetch_edgar_multi_entity()`** (performance oracle)
   - Phase 1: Resolve all CIKs sequentially (fast, needed for dedup)
   - Phase 2: Fetch data in parallel with `ThreadPoolExecutor(max_workers=3)`
   - edgartools' process-global pyrate-limiter handles cross-thread throttling
   - **Expected improvement:** 2-3x reduction (40-60s → 15-25s per deal)

9. **`set_identity()` lifecycle** (framework docs researcher)
   - Call ONCE at application startup (FastAPI lifespan handler), before any worker threads
   - `set_identity()` modifies `os.environ` and calls `close_clients()` — NOT thread-safe if called concurrently
   - NEVER call per-request

10. **Return type: dict at API boundary, dataclasses internally** (pattern recognition specialist)
    - `fetch_edgar_data()` returns `dict[str, Any]` — backward compatible with `r.get("status")` access in `build_edgar_multi_entity_context()`
    - Internally build `EdgarEntityResult` dataclass, convert via `dataclasses.asdict()` at the public API boundary
    - New keys added additively — existing consumers see richer dicts without breaking

## Technical Approach

### Implementation Phases

#### Phase 1: Golden Tests + Dependency + Compliance Fixes (~200 LOC)

**Goal:** Capture regression baselines, add edgartools dependency, fix User-Agent and going concern false positives.

**Tasks:**

1. Add `edgartools` to `pyproject.toml`:
   ```toml
   [project.optional-dependencies]
   edgar = ["edgartools>=5.23,<6.0"]
   ```

   ### Research Insights: Dependency Impact

   - **NEW transitive deps** (not already in stack): `pandas>=2.0`, `pyarrow>=17.0` (~100MB installed), `beautifulsoup4`, `lxml` (native C), `rapidfuzz` (native C), `rich`, `pyrate-limiter>=3.0`, `httpxthrottlecache`, `stamina`, `nest-asyncio` (architecture reviewer)
   - **`nest-asyncio` risk:** Patches `asyncio.run()` to allow nesting. Could interfere with uvicorn's event loop. Monitor for "This event loop is already running" errors (framework docs researcher)
   - **`pyrate-limiter` v4 compatibility:** Issue #640 showed TypeError with pyrate-limiter v4.x API changes. Fixed in edgartools 5.23+. Pinning `<6.0` prevents future breakage (framework docs)
   - **Optional dep group:** Place in `[project.optional-dependencies]` not core `[project.dependencies]` to keep base installation lean (architecture reviewer)

2. Set `EDGAR_IDENTITY` environment variable:
   - Add to `.env.example`:
     ```bash
     # Public identifier (not a secret — required by SEC policy)
     EDGAR_IDENTITY="Netz Analysis Engine tech@netzco.com"
     ```
   - Add startup validation in settings: `assert " " in settings.edgar_identity and "@" in settings.edgar_identity`
   - Update `_USER_AGENT` in `ic_edgar_engine.py` from "Previse Capital" to "Netz Analysis Engine"
   - Call `set_identity()` once in FastAPI lifespan handler (not per-request, not at module level)

3. Write golden-value tests capturing current EDGAR output:
   - `test_edgar_golden.py` — snapshot `fetch_edgar_data()` output for 5 entities:
     - BDC: Ares Capital (ARCC) — full BDC/REIT metrics
     - AM Platform: Blue Owl Capital (OWL) — AM platform metrics (custom XBRL: AUM, FRE, DE)
     - REIT: Chicago Atlantic (REFI) — BDC/REIT with going concern scan
     - Private entity: any Form D-only entity from test deals
     - EFTS-resolved: entity that requires tier 4 fallback
   - Snapshot `build_edgar_multi_entity_context()` output for a multi-entity deal (3+ entities)
   - Use `pytest.mark.integration` — these hit live SEC API (skip in CI by default)

4. Write mock-based unit tests for entity extraction:
   - `test_entity_extraction.py` — verify `extract_searchable_entities()` for various deal structures
   - Include smart target detection, placeholder filtering, CIK deduplication

5. Add entity name input sanitization:
   - Length cap: `if len(name) > 200: skip`
   - Control character stripping: `name = re.sub(r'[\x00-\x1f\x7f]', '', name)`
   - Markdown special character escaping in context serializer output (security sentinel)

6. Add `pip audit` to CI pipeline for transitive dep CVE scanning (security sentinel)

**Files:**
- `pyproject.toml` (edit — add edgartools optional dependency)
- `.env.example` (edit — add EDGAR_IDENTITY with comment)
- `backend/app/core/config.py` (edit — add edgar_identity setting with validation)
- `backend/vertical_engines/credit/ic_edgar_engine.py` (edit — fix User-Agent)
- `backend/tests/test_edgar_golden.py` (new)
- `backend/tests/test_entity_extraction.py` (new)

**Validation:** `make check` passes. Golden tests pass against live SEC API. User-Agent updated. `pip audit` clean.

#### Phase 2: Core Edgar Package — CIK + Financials + Going Concern (~800 LOC across 7 modules)

**Goal:** Build the `edgar/` package with hybrid CIK resolution, structured financials, BDC/AM metrics, going concern, and parallel entity orchestration.

**Tasks:**

1. Create `backend/vertical_engines/credit/edgar/` package:

   **`models.py`** (~100 LOC):
   ```python
   from dataclasses import dataclass, field
   from enum import Enum

   @dataclass
   class CikResolution:
       cik: str | None
       company_name: str | None
       method: str  # "ticker", "fuzzy", "blob_fallback", "not_found"
       confidence: float  # 0.0-1.0

   @dataclass
   class EdgarEntityResult:
       entity_name: str
       role: str
       cik: str | None = None
       ticker: str | None = None
       is_direct_target: bool = False
       company_name: str | None = None
       sic: str | None = None
       sic_description: str | None = None
       state: str | None = None
       fiscal_year_end: str | None = None
       recent_filings: list[dict[str, Any]] | None = None
       financials: "FinancialStatements | None" = None
       bdc_reit_metrics: dict[str, Any] | None = None
       am_platform_metrics: dict[str, Any] | None = None
       going_concern: dict[str, Any] | None = None
       insider_signals: list["InsiderSignal"] | None = None
       form_d: dict[str, Any] | None = None
       warnings: list[str] = field(default_factory=list)
       also_matched_as: list[str] = field(default_factory=list)
       resolution_method: str | None = None
       resolution_confidence: float = 0.0

   @dataclass
   class EdgarMultiEntityResult:
       results: list[EdgarEntityResult]
       unique_ciks: list[str]
       entities_found: int
       entities_searched: int
       combined_warnings: list[str]
   ```

   **`cik_resolver.py`** (~200 LOC):
   - `_resolve_cik_edgartools(name, ticker)`: Company(ticker) → find(name) with fuzz.ratio() ≥ 0.70
   - `_resolve_cik_blob_fallback(name, ticker)`: extracted from ic_edgar_engine.py
   - `resolve_cik(name, ticker) -> CikResolution`: edgartools first, blob fallback
   - Log resolution method + confidence for debugging

   **`financials.py`** (~300 LOC):
   ```python
   @dataclass
   class FinancialStatements:
       income_statement: list[dict[str, Any]] | None = None
       balance_sheet: list[dict[str, Any]] | None = None
       cash_flow: list[dict[str, Any]] | None = None
       ratios: dict[str, float | None] = field(default_factory=dict)
       periods_available: int = 0
       source_filings: list[dict[str, Any]] = field(default_factory=list)
   ```
   - `_extract_structured_financials(company) -> FinancialStatements`: XBRLS primary, EntityFacts BDC fallback
   - `_extract_bdc_reit_metrics(company) -> dict`: via EntityFacts `facts.query().by_form_type("10-K")`
   - `_extract_am_platform_metrics(company) -> dict`: via `facts.query().by_label("...", fuzzy=True)` for custom XBRL concepts
   - `_calculate_ratios(financials) -> dict[str, float | None]`: only 4 credit-relevant ratios:
     - `leverage_ratio` (total_debt / total_equity)
     - `nii_dividend_coverage` (NII / dividends_paid) — BDC/REIT only
     - `interest_coverage` (EBIT / interest_expense) — NEW
     - `debt_service_coverage` (operating_cf / total_debt_service) — NEW
   - Cross-period ratio: set to `None` when numerator/denominator from different fiscal periods (security sentinel)

   ### Research Insights: Financial Extraction Patterns

   - **BDC fallback (critical):** XBRLS has NO BDC-specific taxonomy support. `XBRLS.from_filings()` will likely fail on BDCs using custom extensions. Fall back to `company.get_facts()` (EntityFacts) which uses SEC's pre-parsed facts API (framework docs)
   - **AM platform custom concepts:** AUM/FRE/DE are NOT us-gaap. Use `facts.query().by_label("Assets Under Management", fuzzy=True)` across ALL taxonomies (edgartools skill)
   - **`cashflow_statement()` vs `cash_flow_statement()`:** Naming inconsistency between `StitchedStatements` and `Statements`. Test both paths (edgartools skill)
   - **DataFrame conversion:** Extract to plain dicts inside `to_thread()` call. Never pass pandas objects across async boundaries (learnings researcher)

   **`going_concern.py`** (~100 LOC):
   - `_check_going_concern(company) -> dict | None`: 3-tier classification
   - Uses `filing.text()` from edgartools (replaces manual HTTP)
   - Negation detection within 200 chars of keyword match
   - Returns `{verdict: "CONFIRMED"|"MITIGATED"|"NONE", confidence: float, filing_date, accession}`

   **`entity_extraction.py`** (~150 LOC):
   - Copy `extract_searchable_entities()` verbatim from `ic_edgar_engine.py`
   - No changes — well-tested production code
   - Add entity name sanitization (length cap 200, control char stripping)

   **`service.py`** (~300 LOC):
   - `fetch_edgar_data(entity_name, ticker, role, ...) -> dict[str, Any]`: single-entity, never-raises
   - `fetch_edgar_multi_entity(entities, instrument_type) -> dict[str, Any]`: batch with parallel processing
   - Phase 1: resolve CIKs sequentially (for dedup)
   - Phase 2: `ThreadPoolExecutor(max_workers=3)` for parallel data fetching
   - `return_exceptions=True` in gather for non-fatal design (learnings researcher)
   - Redis distributed rate check before each batch

   **`context_serializer.py`** (~250 LOC):
   - `build_edgar_multi_entity_context(multi_result, deal_name, target_vehicle) -> str`
   - Build context incrementally in priority order, tracking character budget (12KB cap)
   - Preserve attribution framework (DIRECT TARGET / RELATED ENTITY boxes)
   - Add structured financials, ratios, insider signals subsections
   - Sub-cap: insider signals max 3KB

   **`__init__.py`** (~20 LOC):
   ```python
   from vertical_engines.credit.edgar.service import (
       fetch_edgar_data,
       fetch_edgar_multi_entity,
   )
   from vertical_engines.credit.edgar.context_serializer import (
       build_edgar_multi_entity_context,
   )
   from vertical_engines.credit.edgar.entity_extraction import (
       extract_searchable_entities,
   )
   ```

2. Wire into `deep_review.py` — update 3 import statements:
   - Sync path import (~line 361)
   - Async path import (~line 1646)
   - `test_vertical_engines.py` if it references `ic_edgar_engine`

3. Delete `ic_edgar_engine.py` — grep confirms only 3 import sites, all updated above

4. Add Redis distributed rate limiter:
   ```python
   async def _distributed_rate_check(redis_url: str, max_per_second: int = 8):
       """Sliding window counter for cross-process SEC rate limiting."""
       key = f"edgar:rate:{int(time.time())}"
       # INCR + EXPIRE in pipeline
   ```

**Files:**
- `backend/vertical_engines/credit/edgar/__init__.py` (new)
- `backend/vertical_engines/credit/edgar/models.py` (new)
- `backend/vertical_engines/credit/edgar/cik_resolver.py` (new)
- `backend/vertical_engines/credit/edgar/financials.py` (new)
- `backend/vertical_engines/credit/edgar/going_concern.py` (new)
- `backend/vertical_engines/credit/edgar/entity_extraction.py` (new)
- `backend/vertical_engines/credit/edgar/service.py` (new)
- `backend/vertical_engines/credit/edgar/context_serializer.py` (new)
- `backend/vertical_engines/credit/deep_review.py` (edit — 3 import changes)
- `backend/vertical_engines/credit/ic_edgar_engine.py` (delete)
- `backend/vertical_engines/credit/prompts/evidence_law.j2` (edit — expanded attribution)
- `backend/tests/test_edgar_cik.py` (new — mock-based CIK resolution tests)
- `backend/tests/test_edgar_financials.py` (new — mock-based financial extraction + ratio tests)
- `backend/tests/test_edgar_going_concern.py` (new — negation detection tests)
- `backend/tests/test_edgar_context.py` (new — context serializer + truncation tests)

**Validation:** Golden tests pass (same CIKs, same BDC/REIT metrics within 1%, same going concern). `make check` passes. New unit tests for all modules.

#### Phase 3: Form 4 Insider Trading Signals (~300 LOC)

**Goal:** Add insider trading signal detection for credit early-warning. This phase is **optional scope** — the core library migration (Phase 2) delivers value independently.

**Tasks:**

1. Create `backend/vertical_engines/credit/edgar/insider_signals.py`:
   - `InsiderSignalType(str, Enum)` + `SignalSeverity(str, Enum)`
   - `InsiderSignal` dataclass with enum-typed fields
   - `_detect_insider_signals(company, lookback_days=365) -> list[InsiderSignal]`
   - **HTTP optimization:** Filter `filing.filing_date` from index metadata BEFORE calling `filing.obj()`. Only parse filings within lookback window. Reduces ~50 → ~10-15 HTTP requests per entity (performance oracle)
   - 10b5-1 plan detection: check Form 4 checkbox field (SEC 2023 amendments) + footnote text fallback
   - Transaction code filtering: exclude "F" (tax), "G" (gift)

2. Integrate into `service.py`:
   - After CIK + metadata, if role is target or sponsor: detect insider signals
   - Non-fatal: wrap in try/except, skip on failure

3. Update `context_serializer.py`:
   - Add `### Insider Trading Signals` subsection (within 3KB sub-cap)

**Files:**
- `backend/vertical_engines/credit/edgar/insider_signals.py` (new)
- `backend/vertical_engines/credit/edgar/service.py` (edit — integrate signals)
- `backend/vertical_engines/credit/edgar/context_serializer.py` (edit — add signals section)
- `backend/tests/test_insider_signals.py` (new — mock Form 4 data, signal detection)

**Validation:** Signal detection correctly identifies synthetic selling patterns. No false positives on routine Form 4 filings (tax withholding, gifts). `make check` passes.

#### Phase 4: Integration Testing + Side-by-Side Validation (~200 LOC)

**Goal:** Comprehensive validation that the new package matches the old engine.

**Tasks:**

1. Side-by-side comparison for 5 golden test entities:
   - CIK resolution: identical CIK returned?
   - BDC/REIT metrics: values within 1% tolerance?
   - Going concern: same detection result (accounting for improved negation detection)?
   - Context string: old data is still present, new data is additive?

2. Validate rate limiting:
   - Integration test issuing 15 rapid requests through edgartools
   - Measure wall-clock time to confirm throttling is active (security sentinel)

3. Validate multi-entity orchestration:
   - Test with a deal having 5+ entities, including CIK deduplication
   - Test batch path (`run_all_deals_deep_review_v4`) with 2 deals sharing a sponsor

4. Validate token budget:
   - Measure actual `edgar_public_filings` context size for 5 real deals
   - Confirm truncation works at section boundaries, not mid-content
   - Verify 12KB cap maps to ~3000-4000 tokens empirically

5. Evaluate blob index retirement:
   - If edgartools CIK resolution matches for 100% of golden + 50 historical entities → retire blob index
   - If <100% → keep fallback, document the gap

**Files:**
- `backend/tests/test_edgar_integration.py` (new — side-by-side comparison, rate limit validation)
- `backend/tests/test_edgar_e2e.py` (new — multi-entity orchestration, batch path)

**Validation:** Full `make check` passes. All golden tests pass. Side-by-side comparison passes. Rate limiting confirmed.

#### Phase 5: Cleanup (~50 LOC)

**Goal:** Remove orphaned infrastructure, finalize docs.

**Tasks:**

1. If blob index retired in Phase 4:
   - Remove `build_edgar_index.py` worker
   - Remove `edgar-index-blob` container reference
   - Remove blob fallback from `cik_resolver.py`

2. Update deployment configs:
   - Ensure `EDGAR_IDENTITY` in all environments
   - Add `EDGAR_LOCAL_DATA_DIR` if disk cache location needs configuring (edgartools caches to `~/.edgar/_tcache` by default — grows unbounded; set to location with cleanup policy)

3. Monitor `nest-asyncio` behavior in production — no action needed unless errors observed

**Files:**
- `backend/vertical_engines/credit/edgar/cik_resolver.py` (edit — remove blob fallback if retired)
- Deployment configs (edit)
- `build_edgar_index.py` (delete if retired)

**Validation:** `make check` passes. Deep Review produces correct IC memos in production.

## System-Wide Impact

### Interaction Graph

```
Deep Review (deep_review.py)
  └→ extract_searchable_entities() [edgar/entity_extraction.py — UNCHANGED logic]
       └→ Entity name sanitization (length cap, control char strip) — NEW
  └→ fetch_edgar_multi_entity() [edgar/service.py — UNCHANGED signature, returns dict]
       ├→ Phase 1: resolve_cik() sequentially [edgar/cik_resolver.py]
       │    ├→ Company(ticker) [edgartools — tier 1, confidence=1.0]
       │    ├→ find(name) [edgartools — tier 2, confidence=fuzz.ratio()]
       │    └→ _resolve_cik_blob_fallback() [blob index — tier 3]
       ├→ _distributed_rate_check() [Redis — cross-process throttle] — NEW
       ├→ Phase 2: ThreadPoolExecutor(max_workers=3) — PARALLEL
       │    ├→ _extract_structured_financials() [edgar/financials.py]
       │    │    ├→ XBRLS.from_filings() [primary — multi-period stitching]
       │    │    └→ company.get_facts() [BDC fallback — EntityFacts API]
       │    ├→ _extract_bdc_reit_metrics() / _extract_am_platform_metrics()
       │    ├→ _calculate_ratios() [leverage, NII coverage, ICR, DSCR]
       │    ├→ _check_going_concern() [edgar/going_concern.py — 3-tier]
       │    ├→ _detect_insider_signals() [edgar/insider_signals.py — date-filtered]
       │    └→ search_form_d() [preserved for private entities]
       └→ dataclasses.asdict() at API boundary → returns dict[str, Any]
  └→ build_edgar_multi_entity_context() [edgar/context_serializer.py]
       ├→ Section-level truncation with 12KB budget — NEW
       ├→ Attribution framework (DIRECT TARGET / RELATED ENTITY) — PRESERVED
       ├→ Structured financials subsection — NEW
       ├→ Financial ratios subsection — NEW
       └→ Insider signals subsection (3KB sub-cap) — NEW
  └→ evidence_pack["edgar_public_filings"] → all 14 IC memo chapters
       └→ evidence_law.j2 [UPDATED: expanded attribution rules]
```

### Error & Failure Propagation

- **edgartools Company not found:** `CompanyNotFoundError` caught OR `company.not_found == True` → warning, try blob index fallback → if also fails, skip entity. Non-fatal.
- **edgartools No XBRL data:** `NoCompanyFactsFound` or `XBRLFilingWithNoXbrlData` caught → warning, fall back to EntityFacts. If EntityFacts also fails → entity has metadata but no financials. Non-fatal.
- **edgartools HTTP error:** `httpx.HTTPStatusError` caught → warning with status code. 403 → "possible IP block". 500/503 → "SEC server error". Non-fatal.
- **edgartools network timeout:** `httpx.TimeoutException` caught → warning. Disk cache (`~/.edgar/_tcache`) may serve stale data for previously-fetched filings.
- **XBRLS statement resolution failure (BDC custom taxonomy):** Caught → fall back to EntityFacts API. Warning logged. Non-fatal.
- **Form 4 individual filing parse error:** Skip that filing, continue with others. Aggregate signals may be incomplete. Non-fatal.
- **Token budget exceeded:** Section-level truncation → always returns valid string ≤ 12KB. Truncation logged with percentage. Non-fatal.
- **Redis rate limiter unavailable:** Fall back to edgartools-only rate limiting (process-global). Warning logged. Non-fatal.
- **All EDGAR fails:** evidence_pack has no `edgar_public_filings` key → IC memo chapters proceed without EDGAR data (existing behavior, no change).

### State Lifecycle Risks

- **No database changes:** No Alembic migration. EDGAR data is ephemeral (fetched live per Deep Review).
- **Dependency addition:** `edgartools>=5.23,<6.0` adds 21 transitive deps. **CRITICAL: `pandas` and `pyarrow` are NEW** — not currently in `pyproject.toml`. Adds ~100MB + native C++ extensions. May cause build issues on Alpine Docker images. Place in optional dep group `[project.optional-dependencies] edgar = [...]` (architecture reviewer verified)
- **Disk cache:** edgartools caches to `~/.edgar/_tcache`. Filing archive data cached forever. No size limit. Monitor in production. Set `EDGAR_LOCAL_DATA_DIR` for custom location with cleanup policy (framework docs).
- **Blob index retirement:** Only after production validation in Phase 4/5.

### API Surface Parity

- `extract_searchable_entities()` signature: **UNCHANGED**
- `fetch_edgar_data()` signature: **UNCHANGED** (returns `dict[str, Any]` with additional keys)
- `fetch_edgar_multi_entity()` signature: **UNCHANGED** (returns `dict[str, Any]` with richer results)
- `build_edgar_multi_entity_context()` signature: **UNCHANGED** (returns longer string with new sections)
- Import path: **CHANGED** from `vertical_engines.credit.ic_edgar_engine` to `vertical_engines.credit.edgar`
- All existing consumers (deep_review.py sync + async paths) updated in Phase 2

## Acceptance Criteria

### Functional Requirements

- [ ] `fetch_edgar_data()` returns structured financials (income/balance/CF) for BDC and AM Platform entities with ≥3 periods
- [ ] `fetch_edgar_data()` returns 4 credit-relevant ratios (leverage, NII coverage, ICR, DSCR)
- [ ] `fetch_edgar_data()` detects insider trading signals from Form 4 filings (if Phase 3 included)
- [ ] CIK resolution returns IDENTICAL CIKs as old engine for all 5 golden test entities
- [ ] CIK resolution includes confidence score; low-confidence matches (<70%) flagged in warnings
- [ ] Going concern scan returns 3-tier classification (CONFIRMED/MITIGATED/NONE) with negation detection
- [ ] Going concern: "no substantial doubt" classified as NONE (not false positive)
- [ ] BDC/REIT metrics (NAV, assets, debt, leverage, NII, coverage) match old engine within 1% tolerance
- [ ] AM Platform metrics (AUM, mgmt fees, FRE, DE) extracted via fuzzy label search on custom XBRL
- [ ] Multi-entity orchestration preserves 8 entity roles with parallel processing + CIK dedup
- [ ] Attribution framework (DIRECT TARGET / RELATED ENTITY) preserved in context output
- [ ] Non-fatal design: EDGAR failures never crash Deep Review pipeline
- [ ] Token budget: `edgar_public_filings` context capped at 12KB via section-level truncation
- [ ] Evidence_law.j2 updated with expanded attribution rules for financials + insider signals
- [ ] Side-by-side comparison passes for 5 entities: old engine vs new package
- [ ] Redis distributed rate limiter enforces ≤8 req/s per worker for SEC compliance

### Non-Functional Requirements

- [ ] `EDGAR_IDENTITY` env var validated at startup (must contain app name + email)
- [ ] User-Agent updated from "Previse Capital" to "Netz Analysis Engine"
- [ ] `set_identity()` called once at app startup, never per-request
- [ ] All edgartools calls dispatched via `asyncio.to_thread()` in async paths
- [ ] No module-level edgartools initialization (lazy init inside functions)
- [ ] Data extracted to plain dicts/dataclasses before crossing thread boundary (never pass pandas objects)
- [ ] Provenance metadata (accession number, filing date, form type) preserved on all financial data
- [ ] `structlog` logging with `exc_info=True` for ops-facing tracebacks; sanitized warnings for user-facing
- [ ] Entity names sanitized: max 200 chars, control characters stripped
- [ ] `edgartools>=5.23,<6.0` pinned with upper bound
- [ ] `pip audit` in CI pipeline for transitive dep CVE scanning
- [ ] Each module in `edgar/` package ≤300 LOC

### Quality Gates

- [ ] `make check` passes (lint + typecheck + test)
- [ ] Golden tests pass for all 5 reference entities
- [ ] Mock-based unit tests for CIK resolution, financial extraction, ratio calculation, going concern, insider signals
- [ ] Side-by-side integration tests comparing old vs new EDGAR output
- [ ] Rate limiting integration test (15 rapid requests, confirm throttling)
- [ ] Zero regressions in existing Deep Review test suite

## Dependencies & Prerequisites

- **New Python package:** `edgartools>=5.23,<6.0` (MIT license, actively maintained, 5.23.2 released 2026-03-13)
- **NEW transitive deps (not in current stack):** `pandas>=2.0`, `pyarrow>=17.0` (native C++, ~100MB), `beautifulsoup4`, `lxml` (native C), `rapidfuzz` (native C), `rich`, `pyrate-limiter>=3.0`, `httpxthrottlecache`, `stamina`, `nest-asyncio`, `truststore`
- **Already in stack:** `httpx`, `pydantic>=2.0`, `orjson`
- **No Alembic migration required**
- **No frontend changes**
- **Redis required** for distributed rate limiting (already in stack)
- **Prerequisite:** Phase A complete (it is — PR open on `refactor/credit-quant-parity` branch)
- **Environment:** `EDGAR_IDENTITY` env var must be set in all deployment environments

## Risk Analysis & Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| edgartools CIK `find()` can't disambiguate similar financial names | **High** | Wrong entity matched → compliance failure | Confidence scoring with fuzz.ratio() ≥ 70% threshold; blob fallback; side-by-side validation for 50 entities |
| Multi-process SEC rate limit violation (3 workers × 10 req/s = 30 req/s) | **High** | SEC IP blocking affects all EDGAR access | Redis distributed rate limiter from day one (≤8 req/s per worker) |
| `pandas`/`pyarrow` are NEW deps adding ~100MB + native C++ | **High** | Build failures on constrained environments (Alpine, Azure Functions) | Place in optional dep group; test Docker build before merge |
| HTTP request explosion (3-4 → 10-60 per entity with Form 4) | **High** | EDGAR stage becomes 40-60s bottleneck | Parallelize entities (ThreadPoolExecutor 3); filter Form 4 by filing_date; reduces to 15-25s |
| XBRLS fails for BDCs with custom taxonomy extensions | **Medium** | No structured financials for BDC entities | Fall back to EntityFacts API (SEC pre-parsed facts) |
| Going concern false positives on "no substantial doubt" | **Medium** | Misleading risk signal in IC memo | 3-tier classification with negation detection |
| `nest-asyncio` interferes with uvicorn event loop | **Medium** | Subtle async bugs | Monitor for "already running" errors; test thoroughly |
| Form 4 signal detection creates false positives | **Medium** | Noise in IC memos | Conservative thresholds; 10b5-1 exclusion; only target + sponsor roles |
| Form 4 amendments (4/A) not tracked by edgartools | **Medium** | Duplicate or stale transactions | Implement own amendment supersession logic |
| edgartools disk cache grows unbounded at `~/.edgar/_tcache` | **Low** | Disk space exhaustion in production | Set `EDGAR_LOCAL_DATA_DIR`; add monitoring/cleanup |
| `pyrate-limiter` v4+ API changes | **Low** | TypeError at runtime | Pinned `edgartools<6.0`; compatibility shim already in 5.23 |
| edgartools abandoned or breaks on SEC API change | **Low** | Dependency rot | MIT license allows forking; core logic separable from HTTP layer |

## Future Work (Not In This Phase)

| Item | Phase | Trigger |
|------|-------|---------|
| 13F institutional holdings analysis | Phase D+ | When portfolio-level ownership concentration analysis is needed |
| 8-K real-time event monitoring | Phase D+ | When worker infrastructure supports event-driven alerts |
| Blob index full retirement | Phase B+1 sprint | After production validation confirms edgartools precision ≥ blob index |
| FRED parallel fetching (from Phase A Future Work) | Phase B companion | Can be done alongside EDGAR upgrade |
| Structured financial data persistence (beyond evidence pack) | Phase C | When Phase C PD/LGD models need historical financial data without re-fetching |
| Full `FinancialRatios` dataclass with 11 fields | Phase C | When Phase C PD models need typed ratio inputs |
| IFRS namespace support for foreign private issuers | Phase C+ | When analyzing 20-F filers |
| Per-chapter EDGAR evidence injection (instead of all 14 chapters) | Phase C | Token optimization: inject EDGAR data only into Ch4, Ch10, Ch12 |
| EDGAR `formerNames` fallback in CIK resolution | Phase C+ | When historical entity names cause resolution failures |
| Auditor opinion type extraction from going concern scan | Phase C+ | When severity differentiation (unqualified vs qualified) is needed |
| Form 4 multi-reporting-owner attribution | Phase C+ | When individual insider attribution is needed (edgartools aggregates all owners) |

## Sources & References

### Origin

- **Brainstorm document:** [docs/brainstorms/2026-03-15-credit-engine-analytical-upgrade-brainstorm.md](docs/brainstorms/2026-03-15-credit-engine-analytical-upgrade-brainstorm.md) — Key decisions: (1) replace ic_edgar_engine.py with edgartools-powered service, (2) structured financials + insider trading, (3) 13F and 8-K deferred
- **Phase A plan:** [docs/plans/2026-03-15-refactor-credit-quant-architecture-parity-plan.md](docs/plans/2026-03-15-refactor-credit-quant-architecture-parity-plan.md) — Future Work section describes EDGAR upgrade scope and key files

### Internal References

- `backend/vertical_engines/credit/ic_edgar_engine.py` — 1561 LOC being replaced
- `backend/vertical_engines/credit/deep_review.py:514-566` — sync EDGAR integration
- `backend/vertical_engines/credit/deep_review.py:1974-1980` — async EDGAR integration (Phase 3 parallel)
- `backend/vertical_engines/credit/prompts/evidence_law.j2:121-137` — EDGAR attribution rules
- `docs/solutions/architecture-patterns/vertical-engine-extraction-patterns.md` — asyncio.to_thread() pattern (Pattern D), non-fatal design (Pattern E), lazy re-exports, YAGNI abstractions (Finding #009)

### External References

- [edgartools GitHub](https://github.com/dgunning/edgartools) — MIT license, v5.23.2
- [edgartools PyPI](https://pypi.org/project/edgartools/)
- [SEC EDGAR API documentation](https://www.sec.gov/edgar/sec-api-documentation)
- [SEC rate limiting policy](https://www.sec.gov/os/accessing-edgar-data) — 10 req/s with User-Agent identification
- [SEC Rule 10b5-1 amendments (Feb 2023)](https://www.sec.gov/rules/2022/33-11138) — New Form 4 checkbox for plan transactions

### Review Agent Findings Applied

- **Architecture strategist:** Fix pandas/pyarrow claim; section-level truncation; coordinate with TokenBudgetTracker; `set_identity()` lifecycle; frozen vs mutable dataclass discussion (kept mutable per convention); optional dep group
- **Security sentinel:** Redis distributed rate limiter; CIK confidence scoring; entity name sanitization; pin `<6.0`; `pip audit` in CI; lxml XXE check; sub-cap for Form 4 context; startup validation for EDGAR_IDENTITY
- **Performance oracle:** HTTP request explosion (3-4 → 10-60); parallelize with ThreadPoolExecutor; filter Form 4 by filing_date; build context incrementally; entity-level cache for batch mode
- **Python reviewer:** Split into `edgar/` package; `dict[str, Any]` not bare `dict`; `InsiderSignalType` + `SignalSeverity` enums; `CikResolution` return dataclass; delete `FinancialRatios` redundancy; `exc_info=True` for structlog
- **Simplicity reviewer:** Delete `FinancialRatios` (only 2 ratios used); cut dual-use schema; delete re-export wrapper (update 3 imports); simplify truncation to 3-tier; Form 4 flagged as optional scope
- **Pattern recognition:** Dict return type at API boundary (backward compat); `structlog` vs `logging` migration note; naming convention for `edgar/` package
- **Best practices researcher:** Going concern negation detection; ASC 205-40 keyword coverage; 10b5-1 plan checkbox (2023 amendments); Form 4 transaction code filtering ("F"=tax, "G"=gift); tiered evidence prioritization
- **Framework docs researcher:** Thread safety (not designed for concurrent use, but pyrate-limiter is process-global); disk cache at `~/.edgar/_tcache` (unbounded); `nest-asyncio` patches event loop; Form 4 amendments (4/A) no supersession; `set_identity()` closes HTTP clients; XBRLS has no BDC support; EntityFacts better for BDCs
- **edgartools skill:** `Company.not_found` property vs exception; `find()` fuzzy matching weakness for financial names; `cashflow_statement()` vs `cash_flow_statement()` naming; EntityFacts `get_fact()` returns most recent regardless of form type; AM metrics need `by_label()` fuzzy search
- **Learnings researcher:** Pattern D (asyncio.to_thread); Pattern E (non-fatal with warning list); `return_exceptions=True` for parallel gather; no module-level asyncio primitives
- **SpecFlow analyzer:** 14 gaps identified and resolved (CIK precision, rate limiting, schema, Form 4 criteria, going concern, token budget, Phase C inputs, User-Agent, blob index, non-fatal, context serializer, testing, dependency risk, batch mode)

### Institutional Learnings Applied

- **Pattern D (asyncio.to_thread):** Canonical pattern for sync SDKs in async context — applies directly to edgartools
- **Pattern E (non-fatal SSE resilience):** Swallow failures in non-critical subsystems; log warning; continue
- **`return_exceptions=True`:** For `asyncio.gather()` — failed entity fetches return Exception objects instead of cancelling siblings
- **No module-level asyncio primitives:** Create Semaphores/Locks lazily inside async functions
- **Error events sanitized:** No raw `str(exception)` in user-facing warnings (ops-facing tracebacks via structlog `exc_info=True`)
- **Sequential → parallel config fetches:** Finding #005 — use `asyncio.gather()` / `ThreadPoolExecutor` for parallel entity fetches
