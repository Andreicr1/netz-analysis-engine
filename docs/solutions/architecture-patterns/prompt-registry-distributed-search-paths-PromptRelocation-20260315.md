---
title: "Fix Jinja2 template path resolution after credit vertical migration"
date: 2026-03-15
category: architecture-patterns
module: ai_engine/prompts/registry.py, vertical_engines/credit/
symptoms:
  - TemplateNotFound errors when rendering IC memos, sponsor reports, and deep review outputs
  - PromptRegistry only searched ai_engine/prompts/, missing vertical_engines/credit/prompts/ and deep_review/templates/
  - All 31 migrated templates unreachable due to stale "intelligence/" prefix in 10 call sites across 6 files
  - list_templates() returned incomplete results, hiding the broken references
  - Dead templates and uncalled functions accumulated as migration artifacts
root_cause: "Sprint 4 relocated 31 Jinja2 templates to vertical_engines/credit/prompts/ but PromptRegistry had a single hardcoded search path (ai_engine/prompts/) and call sites retained the old 'intelligence/' prefix"
fix_type: refactor
severity: medium
tags:
  - template-resolution
  - prompt-registry
  - path-migration
  - dead-code-removal
  - credit-vertical
  - jinja2
related_prs:
  - 24
---

# Fix Jinja2 Template Path Resolution After Credit Vertical Migration

## Root Cause

After Sprint 4 moved 31 `.j2` templates from `ai_engine/prompts/intelligence/` to `vertical_engines/credit/prompts/`, the `PromptRegistry` still only searched `ai_engine/prompts/` (its `_base_dir`). All 10+ call sites continued using the `"intelligence/..."` prefix path (e.g., `prompt_registry.render("intelligence/ch01_exec.j2")`), which resolved to `ai_engine/prompts/intelligence/ch01_exec.j2` — a directory that no longer existed after the move.

The code worked at runtime only because every call site had a `has_template()` fallback that fell through to Python string constants (`_CHAPTER_PROMPTS`, `_EVIDENCE_LAW`, `_EVIDENCE_LAW_CH13`) defined in `memo/prompts.py`. These fallbacks were supposed to be temporary migration scaffolding but had silently become the permanent code path — meaning all Jinja2 templates were dead code.

## Solution

### 1. Added `add_search_path()` to PromptRegistry

`backend/ai_engine/prompts/registry.py` — allows vertical engine packages to register their own template directories at import time. Includes path validation (must be within `backend/`) and collision detection (warns if template names shadow existing ones):

```python
def add_search_path(self, path: Path | str) -> None:
    resolved = Path(path).resolve()
    backend_root = Path(__file__).resolve().parents[2]
    if not str(resolved).startswith(str(backend_root)):
        raise ValueError(...)
    if not resolved.is_dir():
        raise ValueError(...)
    path_str = str(resolved)
    if path_str not in self._env.loader.searchpath:
        # Warn on template name collisions
        existing_names: set[str] = set()
        for sp in self._env.loader.searchpath:
            for f in Path(sp).glob("*.j2"):
                existing_names.add(f.name)
        for f in resolved.glob("*.j2"):
            if f.name in existing_names:
                logger.warning(
                    "Template name collision: %s in %s shadows existing template",
                    f.name, path_str,
                )
        self._env.loader.searchpath.append(path_str)
```

### 2. Registered search paths at import time

`backend/vertical_engines/credit/__init__.py`:
```python
from ai_engine.prompts import prompt_registry
prompt_registry.add_search_path(Path(__file__).parent / "prompts")
```

`backend/vertical_engines/credit/deep_review/__init__.py`:
```python
from ai_engine.prompts import prompt_registry
prompt_registry.add_search_path(Path(__file__).parent / "templates")
```

### 3. Dropped `"intelligence/"` prefix from all 10 call sites

| File | Before | After |
|------|--------|-------|
| `memo/chapters.py` (3 calls) | `"intelligence/ch01_exec.j2"`, `"intelligence/evidence_law.j2"`, `"intelligence/evidence_law_ch13.j2"` | `"ch01_exec.j2"`, `"evidence_law.j2"`, `"evidence_law_ch13.j2"` |
| `memo/tone.py` (2 calls) | `"intelligence/tone_pass1.j2"`, `"intelligence/tone_pass2.j2"` | `"tone_pass1.j2"`, `"tone_pass2.j2"` |
| `pipeline/intelligence.py` (2 calls) | `"intelligence/pipeline_structured.j2"`, `"intelligence/pipeline_memo.j2"` | `"pipeline_structured.j2"`, `"pipeline_memo.j2"` |
| `deep_review/prompts.py` (1 call) | `"intelligence/deal_review_system_v2.j2"` | `"deal_review_system_v2.j2"` |
| `domain_ai/service.py` (1 call) | `"intelligence/domain_portfolio.j2"` | `"domain_portfolio.j2"` |
| `sponsor/service.py` (1 call) | `"intelligence/sponsor_assessment.j2"` | `"sponsor_assessment.j2"` |

### 4. Removed `has_template()` fallback scaffolding

Before (fallback to Python string constants):
```python
def _get_chapter_base_prompt(chapter_tag, **context):
    if chapter_tag in _CHAPTER_TAGS and prompt_registry.has_template(f"intelligence/{chapter_tag}.j2"):
        return prompt_registry.render(f"intelligence/{chapter_tag}.j2", **context)
    return _CHAPTER_PROMPTS.get(chapter_tag)  # Python string fallback
```

After (direct render, fail-fast):
```python
def _get_chapter_base_prompt(chapter_tag, **context):
    if chapter_tag in _CHAPTER_TAGS:
        return prompt_registry.render(f"{chapter_tag}.j2", **context)
    return None
```

### 5. Deleted dead code

- `deal_review_system_v1.j2` (159 lines) — superseded by v2, caller deleted
- `structured_legacy.j2` (79 lines) — zero Python references
- `_build_deal_review_prompt()` v1 function (21 lines) — uncalled, only v2 used

### 6. Production optimization + `list_templates()` fix

`auto_reload=False` in production eliminates per-render `os.stat()` calls:
```python
auto_reload=os.getenv("NETZ_ENV", "dev") == "dev",
```

`list_templates()` rewritten to iterate all search paths (not just `_base_dir`), with deduplication matching `FileSystemLoader` resolution order.

## Key Design Decisions

1. **Import-time registration, not runtime discovery.** Search paths registered in `__init__.py` via `add_search_path()`. Python's import graph guarantees ordering — if a caller can reference a template, the package was imported, and templates were registered. Zero manual wiring in startup code.

2. **Flat template names, not path-prefixed.** Templates resolved by filename alone (`"ch01_exec.j2"`) rather than path (`"intelligence/ch01_exec.j2"`). Jinja2's `FileSystemLoader` searches all registered paths in order, so the first match wins. This decouples call sites from physical template locations.

3. **Fail-fast over fallback.** The `has_template()` + Python string constant fallback pattern was removed. A missing template is now a hard `TemplateNotFound` error, not a silent degradation to stale string constants that diverge from `.j2` files.

4. **Path validation constrains to `backend/`.** Prevents misconfigured verticals from registering arbitrary filesystem paths. The `backend/` root is computed from the registry module's own location.

5. **Collision detection warns but does not block.** If two directories contain a template with the same name, the registry logs a warning. First-registered path wins per Jinja2 semantics. Makes accidental shadowing visible in logs.

## Prevention Strategies

### Anti-pattern: `has_template()` with fallback strings

This is the exact mechanism that masked the breakage for months. If a template is missing, the correct behavior is to fail, not to silently fall back to a Python string constant. Fallbacks convert hard errors into subtle behavioral regressions that only surface in output quality — the hardest kind of bug to detect.

### Rule: When you delete a caller, delete its callees

If nothing imports or references the template, it is dead. Delete it in the same commit. Git history is the archive — any deleted file can be recovered from a specific commit. Keeping dead code "just in case" trades a guaranteed ongoing cost (maintenance burden) for a hypothetical future benefit that almost never materializes.

### Import-time registration > manual initialization

Manual initialization (`register_templates()` from `init_app()`) creates temporal coupling: registration must happen before any render, but nothing enforces ordering. Import-time registration in `__init__.py` eliminates this — if code can reference a template, the package was imported, and templates were registered.

## Checklist for Future Template Relocations

1. Grep the entire codebase for every template path string that will change. Record every caller file and line number.
2. Update or create a centralized path registry (constants in package `__init__.py`).
3. Update every caller to use the registry constant instead of hardcoded strings.
4. Remove `has_template()` fallback patterns — replace with direct `render()` that fails loudly.
5. Add startup-time template validation (every registered path must resolve to an actual file).
6. Check for shadowing — confirm no two templates with the same filename exist in different search paths.
7. Delete dead templates whose callers were removed. Same PR.
8. Run the full test gate (`make check`).
9. Grep for the old path prefix one final time — zero hits required.
10. Verify in a clean environment (CI, fresh checkout).

## Related Documentation

- `docs/solutions/architecture-patterns/wave2-deep-review-modularization-MonolithToDAGPackage-20260315.md` — Wave 2 deep_review package extraction (PR #23)
- `docs/solutions/architecture-patterns/wave1-credit-vertical-modularization-MonolithToPackages-20260315.md` — Wave 1 edgar-style package pattern (PRs #8-19)
- `docs/solutions/architecture-patterns/vertical-engine-extraction-patterns.md` — Phase 4 vertical engine extraction patterns
- `docs/solutions/architecture-patterns/monolith-to-modular-package-with-library-migration.md` — Edgar package reference implementation
- `docs/plans/2026-03-15-refactor-credit-deep-review-modularization-wave2-plan.md` — Wave 2 plan (Phase 2: Prompt Relocation)

## Cross-References

- **PR #24** — `refactor(credit): Phase 2 — prompt relocation to deep_review/templates/`
- **PR #23** — `refactor(credit): Wave 2 — deep_review package modularization`

## Validation

- 337 tests pass
- 5/5 import-linter contracts pass
- Lint clean (ruff)
- `grep -rn '"intelligence/' backend/vertical_engines/credit/ --include="*.py"` returns zero template path hits
- 8-agent code review: 0 P1, 0 P2 (after fixes), 0 P3 (after fixes)
