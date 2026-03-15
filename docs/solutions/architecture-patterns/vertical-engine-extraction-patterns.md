---
title: "Phase 4: Vertical Engine Extraction, StorageClient, ProfileLoader & Code Review Resolution"
date: 2026-03-15
tags:
  - vertical-engines
  - storage-abstraction
  - profile-loader
  - knowledge-aggregation
  - privacy-by-design
  - code-review
  - upload-architecture
  - import-migration
category: architecture-patterns
severity: high
component:
  - vertical_engines/base
  - vertical_engines/credit
  - vertical_engines/wealth
  - backend/app/services/storage_client.py
  - backend/ai_engine/profile_loader.py
  - backend/app/domains/credit/documents/routes/upload_url.py
  - worker_app/knowledge_aggregator.py
  - worker_app/outcome_recorder.py
related_issues:
  - "Platform Plan Phase 4 (docs/plans/2026-03-14-feat-netz-analysis-engine-platform-plan.md)"
  - "ProductConfig Plan (docs/plans/2026-03-14-feat-customizable-vertical-config-plan.md)"
  - "PR #2 (Sprint 3 — ProductConfig Phase 1, merged)"
  - "Sprint 2b Migration (docs/solutions/database-issues/alembic-monorepo-migration-fk-rls-ordering.md)"
problem_type: multi-concern
status: resolved
---

# Vertical Engine Extraction — Architecture Patterns

## Problem Statement

The `ai_engine/intelligence/` directory contained all IC memo generation, deep review, and deal analysis logic as a monolithic package (28 Python modules, 31 Jinja2 prompts, ~850 KB). Adding a second vertical (Wealth Management DD reports) would have required either forking the intelligence code or polluting it with vertical-specific conditionals. The engine needed a pluggable architecture where each asset class vertical owns its analysis logic, prompts, and scoring independently.

Additionally, no storage abstraction existed for the data lake (ADLS vs local dev), no profile loading mechanism connected YAML seed data to vertical engines via ConfigService, and no upload architecture supported direct-to-storage uploads with SSE progress streaming.

## Root Cause

Single-vertical assumptions baked throughout `ai_engine/intelligence/`:
- All 28 modules assumed Private Credit domain concepts (IC memos, 13-chapter structure, covenants, LTV)
- Prompt templates lived under `ai_engine/prompts/intelligence/` with no namespace isolation
- Import paths throughout the codebase pointed directly at `ai_engine.intelligence.*`
- No abstract interface existed to define what "analysis" means across verticals

## Solution — 5-Chunk Implementation

The work was split into 5 focused chunks for maximum concentration, each with its own commit and test pass.

### Chunk 1: Base interfaces + credit file move

**Commit:** `b02e00a` | **Tests:** 50/50

Moved 28 Python files and 31 Jinja2 templates from `ai_engine/intelligence/` to `vertical_engines/credit/`. Created `BaseAnalyzer` abstract class:

```python
class BaseAnalyzer(ABC):
    """Note: Methods accept sync Session (not AsyncSession) because
    vertical engine business logic is CPU-bound and runs in sync context.
    Callers in async route handlers must dispatch via asyncio.to_thread()."""

    vertical: str  # e.g. "private_credit", "liquid_funds"

    @abstractmethod
    def run_deal_analysis(self, db: Session, *, fund_id, deal_id, actor_id, ...) -> dict: ...

    @abstractmethod
    def run_portfolio_analysis(self, db: Session, *, fund_id, actor_id, ...) -> dict: ...

    def run_pipeline_analysis(self, db: Session, ...) -> dict:
        return {"status": "not_applicable", "vertical": self.vertical}  # non-abstract default
```

Backward-compatible re-exports in `ai_engine/__init__.py`:
```python
def run_pipeline_ingest(*args, **kwargs):
    from vertical_engines.credit.pipeline_intelligence import run_pipeline_ingest as _impl
    return _impl(*args, **kwargs)
```

### Chunk 2: StorageClient + ProfileLoader

**Commit:** `09dcc25` | **Tests:** 72/72

**StorageClient** — dual-backend abstraction with path traversal protection:

```python
class StorageClient(ABC):
    @staticmethod
    def _validate_path(path: str) -> None:
        if not path: raise ValueError("must not be empty")
        if "\x00" in path: raise ValueError("must not contain null bytes")
        if ".." in path.split("/"): raise ValueError(f"Path traversal detected: {path}")
        if path.startswith(("/", "\\")): raise ValueError("Absolute paths not allowed")
```

**ProfileLoader** — connects YAML seed data to vertical engines via ConfigService with parallel config fetches:

```python
chapters_config, calibration = await asyncio.gather(
    self._config.get(vertical, "chapters", org_id),
    self._config.get(vertical, "calibration", org_id),
)
```

### Chunk 3: Upload architecture (SAS URL + SSE)

**Commit:** `c8acd64` | **Tests:** 80/80

Two-step upload flow:
1. `POST /documents/upload-url` → SAS URL + `upload_id`
2. `POST /documents/upload-complete` → marks PROCESSING, publishes SSE, returns `job_id`
3. `GET /jobs/{job_id}/stream` → SSE events (existing endpoint, now wired to ingestion worker)

Ingestion worker emits granular progress: `processing → ocr_complete → chunking_complete → indexing_complete → ingestion_complete`. Redis failures swallowed (logging only) to prevent SSE issues from breaking ingestion.

### Chunk 4: Knowledge aggregator + outcome recorder

**Commit:** `11bf341` | **Tests:** 113/113

**Privacy-by-design** with three-layer defense:
1. **One-way hash:** `SHA256(org_id + deal_id + memo_id)` — cannot reverse
2. **Deny list:** `_FORBIDDEN_FIELDS` rejects `organization_id`, `company_name`, etc.
3. **Positive allowlist:** `_ALLOWED_SIGNAL_FIELDS` — any unexpected field raises `RuntimeError`

All numeric values bucketed (LTV: `0-40%|40-60%|60-70%|70%+`). No exact values stored. Outcome recorder links conversion results via the same anonymous hash, enabling the knowledge flywheel.

### Chunk 5: Wealth engine scaffold + profile YAML

**Commit:** `db4a599` | **Tests:** 120/120

`FundAnalyzer(BaseAnalyzer)` for `liquid_funds` profile, `DDReportEngine` (7-chapter DD report), `QuantAnalyzer` (bridges quant_engine). Profile YAML in `profiles/liquid_funds/profile.yaml`.

## Code Review Findings

8 parallel review agents (Python, Security, Performance, Architecture, Pattern Recognition, Simplicity, Agent-Native, Learnings) produced 11 findings. 10 resolved in commit `c8562bb`:

| # | Priority | Finding | Resolution |
|---|----------|---------|------------|
| 001 | P1 | ADLS blocks event loop with sync SDK | `asyncio.to_thread()` wrappers |
| 002 | P1 | Unsanitized filename in blob path | `_SAFE_FILENAME_RE` + `_validate_path()` on base class |
| 003 | P2 | Deny list only for privacy signals | Added positive `_ALLOWED_SIGNAL_FIELDS` allowlist |
| 004 | P2 | Exception details leak to SSE | Sanitized to `{"reason": "processing_error"}` |
| 005 | P2 | Sequential ProfileLoader config calls | `asyncio.gather()` |
| 006 | P2 | Dual registry dicts | Consolidated to single `_REGISTRY` |
| 007 | P2 | Sync Session contract undocumented | Added BaseAnalyzer docstring |
| 008 | P2 | No ADLS credential validation at startup | Added to `validate_production_secrets()` |
| 009 | P3 | YAGNI BaseCritic/BaseExtractor | Removed; `run_pipeline_analysis` made non-abstract |
| 010 | P3 | Stale agent system prompt | **Deferred** — separate scope |
| 011 | P3 | Pretty-printed JSON for signals | Compact `separators=(",", ":")` |

## Key Reusable Patterns

### Pattern A: Import path migration with backward-compat re-exports

When moving modules to a new package, leave lazy re-exports at the old path:

```python
# ai_engine/__init__.py — old location delegates to new
def run_pipeline_ingest(*args, **kwargs):
    from vertical_engines.credit.pipeline_intelligence import run_pipeline_ingest as _impl
    return _impl(*args, **kwargs)
```

Callers migrate incrementally. Git detects renames (preserving blame) when you copy-then-delete.

### Pattern B: Dual-layer path traversal protection

Layer 1 (base class): static validation rejects `..`, absolute paths, null bytes before any I/O.
Layer 2 (LocalStorageClient): `resolve()` + prefix check ensures resolved path stays under root.

```python
def _resolve(self, path: str) -> Path:
    resolved = (self._root / path).resolve()
    if not str(resolved).startswith(str(self._root)):
        raise ValueError(f"Path traversal detected: {path}")
    return resolved
```

### Pattern C: Privacy-by-design with allowlist + deny list + bucketed ranges

Never rely on deny lists alone. The positive allowlist ensures adding a new field requires explicit approval:

```python
_ALLOWED_SIGNAL_FIELDS = frozenset({
    "anonymous_hash", "timestamp", "profile", "recommendation",
    "confidence_score", "chapter_scores", "risk_flags_count",
    "critic_fatal_flaws", "ltv_bucket", "tenor_bucket",
    "structure_type", "regime", "vix_bucket",
})

unexpected = signal.keys() - _ALLOWED_SIGNAL_FIELDS
if unexpected:
    raise RuntimeError(f"PRIVACY VIOLATION: unexpected fields: {unexpected}")
```

### Pattern D: `asyncio.to_thread()` for sync SDKs in async context

When a third-party SDK is sync-only, wrap each call:

```python
async def write(self, path: str, data: bytes, **kw) -> str:
    self._validate_path(path)
    file_client = self._fs.get_file_client(path)
    await asyncio.to_thread(file_client.upload_data, data, overwrite=True)
    return path
```

### Pattern E: SSE event emission with resilience

Workers publish events at each stage. Redis failures are swallowed to prevent SSE from breaking ingestion:

```python
async def _emit(version_id, event_type, data=None):
    try:
        await publish_event(str(version_id), event_type, data)
    except Exception:
        logger.warning("Failed to publish SSE event %s", event_type, exc_info=True)
```

## Prevention Strategies

### Adding a new vertical engine
1. Create `vertical_engines/{vertical}/` with `{vertical}_analyzer.py` subclassing `BaseAnalyzer`
2. Add seed YAML under `calibration/seeds/{vertical}/` and `profiles/{vertical}/`
3. Add entries to `_YAML_FALLBACK_MAP` in `config_service.py`
4. Register in ProfileLoader's `_REGISTRY`
5. Add tests in `test_vertical_engines.py`

### Adding a new storage backend
1. Subclass `StorageClient` — call `self._validate_path()` as first line of every method
2. Wrap sync SDK calls with `asyncio.to_thread()`
3. Add path traversal tests mirroring `TestPathValidation`
4. Gate behind a feature flag in `settings.py`

### Review checklist for future PRs
- [ ] No sync I/O inside `async def` without `asyncio.to_thread()`
- [ ] No module-level asyncio primitives (Semaphore, Lock, Event)
- [ ] User input validated before path construction
- [ ] Error events sanitized — no raw `str(exception)` in SSE or DB
- [ ] New config types explicitly classified in `CLIENT_VISIBLE_TYPES`
- [ ] New abstract methods have 2+ implementations (no YAGNI)

## Related Documentation

- **Platform Plan:** `docs/plans/2026-03-14-feat-netz-analysis-engine-platform-plan.md` (Phase 4)
- **ProductConfig Plan:** `docs/plans/2026-03-14-feat-customizable-vertical-config-plan.md`
- **Sprint 2b Migration Patterns:** `docs/solutions/database-issues/alembic-monorepo-migration-fk-rls-ordering.md`
- **Platform Brainstorm:** `docs/brainstorms/2026-03-14-analysis-engine-platform-brainstorm.md`

## Stats

- **Branch:** `feat/sprint-4-vertical-engines` (7 commits)
- **Files changed:** 112
- **Lines:** +3005 / -293
- **Tests:** 131 pass, 0 fail
- **Review agents:** 8 parallel, 11 findings, 10 resolved
