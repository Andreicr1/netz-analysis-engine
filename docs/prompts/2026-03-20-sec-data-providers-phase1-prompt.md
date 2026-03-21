# SEC Data Providers — Phase 1: Shared SEC Infrastructure

## Context

You are working on `netz-analysis-engine`, a multi-tenant investment analysis platform. Read `CLAUDE.md` at the repo root for full architecture context.

**What you're building:** `backend/data_providers/sec/shared.py` + `backend/data_providers/sec/models.py` — the shared SEC infrastructure layer consumed by both Credit and Wealth verticals.

**Prior phase (Phase 9 — DONE):** Package scaffold created. `data_providers` is importable. Both `backend/data_providers/__init__.py` and `backend/data_providers/sec/__init__.py` exist (empty). `pyproject.toml` already has `"data_providers*"` in `[tool.setuptools.packages.find] include` and `"data_providers"` in `[tool.importlinter] root_packages`. All gates green. Test count is 1583+.

**Plan documents (read BEFORE writing any code):**
- `docs/plans/2026-03-20-feat-sec-data-providers-layer-plan.md` — full technical plan (lines 122-160 for Phase 1)
- `docs/plans/2026-03-20-feat-sec-data-providers-layer-backlog.md` — phased backlog with exit criteria

## Precise Task

Create two files. No other files should be modified.

### File 1: `backend/data_providers/sec/models.py`

Frozen dataclasses for all SEC data types. This file has **zero imports from `app.*`** — fully standalone.

Contents:
- `CikResolution` — migrate from `backend/vertical_engines/credit/edgar/models.py` (lines 42-48). Make it `@dataclass(frozen=True)` (current one is mutable — new one must be frozen). Fields: `cik: str | None`, `company_name: str | None`, `method: str`, `confidence: float`.
- `AdvManager` — frozen dataclass. Fields: `crd_number: str`, `cik: str | None`, `firm_name: str`, `sec_number: str | None`, `registration_status: str | None`, `aum_total: int | None`, `aum_discretionary: int | None`, `aum_non_discretionary: int | None`, `total_accounts: int | None`, `fee_types: dict[str, Any] | None`, `client_types: dict[str, Any] | None`, `state: str | None`, `country: str | None`, `website: str | None`, `compliance_disclosures: int | None`, `last_adv_filed_at: str | None`, `data_fetched_at: str | None`.
- `AdvFund` — frozen dataclass. Fields: `crd_number: str`, `fund_name: str`, `fund_id: str | None`, `gross_asset_value: int | None`, `fund_type: str | None`, `is_fund_of_funds: bool | None`, `investor_count: int | None`.
- `AdvTeamMember` — frozen dataclass. Fields: `crd_number: str`, `person_name: str`, `title: str | None`, `role: str | None`, `education: dict[str, Any] | None`, `certifications: list[str]`, `years_experience: int | None`, `bio_summary: str | None`.
- `ThirteenFHolding` — frozen dataclass. Fields: `cik: str`, `report_date: str`, `filing_date: str`, `accession_number: str`, `cusip: str`, `issuer_name: str`, `asset_class: str | None`, `shares: int | None`, `market_value: int | None` (USD, ×1000 already applied), `discretion: str | None`, `voting_sole: int | None`, `voting_shared: int | None`, `voting_none: int | None`.
- `ThirteenFDiff` — frozen dataclass. Fields: `cik: str`, `cusip: str`, `issuer_name: str`, `quarter_from: str`, `quarter_to: str`, `shares_before: int | None`, `shares_after: int | None`, `shares_delta: int | None`, `value_before: int | None`, `value_after: int | None`, `action: str`, `weight_before: float | None`, `weight_after: float | None`.
- `InstitutionalAllocation` — frozen dataclass. Fields: `filer_cik: str`, `filer_name: str`, `filer_type: str | None`, `report_date: str`, `target_cusip: str`, `target_issuer: str`, `market_value: int | None`, `shares: int | None`.
- `SeriesFetchResult` — generic wrapper. Fields: `data: list[Any]`, `warnings: list[str]`, `is_stale: bool`, `data_fetched_at: str | None`.
- `CoverageType` — `str, Enum`. Values: `FOUND = "found"`, `PUBLIC_SECURITIES_NO_HOLDERS = "public_securities_no_holders"`, `NO_PUBLIC_SECURITIES = "no_public_securities"`.
- `InstitutionalOwnershipResult` — frozen dataclass. Fields: `manager_cik: str`, `coverage: CoverageType`, `investors: list[InstitutionalAllocation]`, `note: str | None = None`.

Use `from __future__ import annotations`. Only imports: `dataclasses`, `enum`, `typing`. No `structlog`, no `app.*`.

### File 2: `backend/data_providers/sec/shared.py`

Shared SEC infrastructure. This file has **zero imports from `app.*`** — fully standalone.

**Reference code to migrate from (read these files first):**
- `backend/vertical_engines/credit/edgar/cik_resolver.py` — current 4-tier CIK resolver (read the entire file)
- `backend/vertical_engines/credit/edgar/service.py` — lines 34-61 for `_SEC_USER_AGENT` and `_check_distributed_rate()`

**What to implement:**

1. **Constants:**
   - `SEC_USER_AGENT = "Netz Analysis Engine tech@netzco.com"`
   - `SEC_EDGAR_RATE_LIMIT = 8` (req/s)
   - `SEC_IAPD_RATE_LIMIT = 2` (req/s)

2. **Rate limiters** (`check_edgar_rate()`, `check_iapd_rate()`):
   - Redis sliding window pattern: key = `edgar:rate:{current_second}` / `iapd:rate:{current_second}`, TTL = 2s
   - If count > max_per_second: `time.sleep(1.0)`
   - **Local fallback** when Redis unavailable: in-process token bucket at `rate / 4` req/s (not unlimited). Log WARNING once when fallback activates.
   - Redis import must be lazy (inside function body). Import `redis` and get URL from env var `REDIS_URL` directly (`os.environ.get("REDIS_URL")`), NOT from `app.core.config.settings`. This keeps `shared.py` standalone.

3. **`sanitize_entity_name(name: str) -> str | None`:**
   - Migrate from `cik_resolver.py` lines 55-68
   - **Security hardening** (plan item #12): add strict character allowlist `^[a-zA-Z0-9\s.,'\-&()]+$`. Reject names with EFTS query operators or quotes that could inject into SEC search queries. Return None for rejected names with a warning log.

4. **`_normalize_light(name)` and `_normalize_heavy(name)`:**
   - Copy exactly from `cik_resolver.py` lines 26-46. These are used by fuzzy matching.

5. **`resolve_cik(entity_name: str, ticker: str | None = None) -> CikResolution`:**
   - **3-tier cascade** (blob index tier intentionally eliminated):
     - **Tier 1:** `edgartools Company(ticker)` → `confidence=1.0`, `method="ticker"`
     - **Tier 2:** `edgartools find(name)` + `rapidfuzz.fuzz.ratio ≥ 0.85` → `confidence=ratio/100`, `method="fuzzy"`
     - **Tier 3 (NEW — not in current cik_resolver.py):** EFTS full-text search via `httpx.get("https://efts.sec.gov/LATEST/search-index", params={"q": name, "dateRange": "custom", "startdt": "2020-01-01"}, headers={"User-Agent": SEC_USER_AGENT})` — parse response for CIK, `method="efts"`, `confidence=0.7`
   - Never raises — returns `CikResolution(cik=None, ..., method="not_found", confidence=0.0)` on failure
   - `edgartools` and `rapidfuzz` imports must be lazy (inside try/except ImportError)
   - Call `check_edgar_rate()` before EFTS request
   - Use `structlog` for logging (same patterns as `cik_resolver.py`)

6. **Dedicated SEC thread pool:**
   - `_sec_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sec-data")`
   - `async def run_in_sec_thread(fn: Callable[..., T], *args: Any) -> T:` — runs sync function in the dedicated executor via `loop.run_in_executor()`
   - Do NOT create at module level — create lazily to avoid event loop issues (per CLAUDE.md rule: "No module-level asyncio primitives"). The `ThreadPoolExecutor` itself is fine at module level (it's not an asyncio primitive), but the async helper must get the loop at call time.

## Exit Criteria

- [ ] `backend/data_providers/sec/models.py` exists with all dataclasses listed above
- [ ] `backend/data_providers/sec/shared.py` exists with all functions listed above
- [ ] Both files have **zero imports from `app.*`** — verify with `grep -r "from app\." backend/data_providers/`
- [ ] `resolve_cik()` has 3 tiers (ticker → fuzzy → EFTS). No blob index tier.
- [ ] Rate limiters work with Redis available and degrade gracefully without it (local fallback, not unlimited)
- [ ] `sanitize_entity_name()` includes character allowlist security hardening
- [ ] Run `make check` — must be green (no regressions on existing 1583+ tests)
- [ ] Both files pass `mypy` with no errors

## After Completion

When all exit criteria pass, do the following:

1. Mark Phase 1 as `Status: DONE` in `docs/plans/2026-03-20-feat-sec-data-providers-layer-backlog.md`
2. Fill in the Phase 1 continuation prompt section with the prompt below (adapted with any runtime observations)
3. Output the Phase 2 continuation prompt for the user

**Phase 2 continuation prompt template:**

```
Read `docs/plans/2026-03-20-feat-sec-data-providers-layer-backlog.md` before doing anything.

Phase 1 (Shared SEC Infrastructure) is DONE. Exit criteria met:
- `data_providers/sec/models.py` has all frozen dataclasses (CikResolution, AdvManager, AdvFund, AdvTeamMember, ThirteenFHolding, ThirteenFDiff, InstitutionalAllocation, SeriesFetchResult, CoverageType, InstitutionalOwnershipResult)
- `data_providers/sec/shared.py` has CIK resolver (3-tier: ticker → fuzzy → EFTS), rate limiters (Redis + local fallback), sanitize_entity_name (hardened), normalize functions, SEC thread pool
- Both files have zero imports from `app.*`
- `make check` passes (XXXX tests, 0 failures)
- [ADD ANY RUNTIME OBSERVATIONS HERE — e.g., unexpected import issues, test count, pre-existing lint warnings]

Execute Phase 2 next: credit/edgar Refactor.

Key references for Phase 2:
- CIK resolver to DELETE: `backend/vertical_engines/credit/edgar/cik_resolver.py`
- Service to update: `backend/vertical_engines/credit/edgar/service.py` (replace `_check_distributed_rate`, `_SEC_USER_AGENT`, CIK resolver imports)
- Entity extraction to update: `backend/vertical_engines/credit/edgar/entity_extraction.py` (replace `sanitize_entity_name` import)
- __init__.py to update: `backend/vertical_engines/credit/edgar/__init__.py` (remove `cik_resolver` lazy import)
- Test to update: `backend/tests/test_edgar_package.py` (replace `sanitize_entity_name` import)
- Plan Phase 2 details: `docs/plans/2026-03-20-feat-sec-data-providers-layer-plan.md` lines 163-200
- `CikResolution` in `credit/edgar/models.py` must add re-export: `from data_providers.sec.models import CikResolution`
- The new `CikResolution` is frozen — verify no existing code mutates it (it shouldn't, it's already used as immutable)
- `resolve_cik()` signature changed: no `blob_loader` parameter (blob index eliminated). Callers just pass `(name, ticker)`.
- `_search_form_d()` in `service.py` stays — it's credit-specific Form D search, NOT the same as EFTS CIK resolution

After the phase passes all exit criteria, mark it DONE in the backlog and write the continuation prompt for Phase 3 before closing the session.
```
