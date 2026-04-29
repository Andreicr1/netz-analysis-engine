# PR-Q108 — Codex Auto Review hotfix — annotation guard test path resolution (P2)

**Status:** READY FOR DISPATCH (fresh Opus 4.7 1M session)
**Origin:** Codex Auto Review on PR-Q103 (Wave 6 S09 C-15) — 1 P2 catch
**Target file:** `backend/tests/static/test_no_org_id_str_annotation.py`
**Severity:** P2 (test passes silently in CI cwd=backend, allowing regressions to slip through)

---

## STAGE — Q108 Hotfix

You are implementing PR-Q108, a narrow hotfix for a Codex Auto Review P2 catch on PR-Q103's C-15 cleanup (`org_id: str` annotation sweep, Wave 6 Session 09, already shipped to main).

The Q103 PR added a static guard test `test_no_org_id_str_annotation.py` that scans `backend/app/domains` for offending annotation patterns. The path is hard-coded as `Path("backend/app/domains")` — a relative path that only resolves correctly when pytest is launched from the repository root. CI and local Make targets run pytest with `working-directory: backend`, so the path doesn't exist, the loop iterates zero files, and the test passes silently regardless of whether new offenders were introduced.

The guard is currently **ineffective** — a regression introducing `org_id: str = Depends(get_org_id)` to a new route would not trip the test in CI.

## CATCH (verbatim)

> This guard test currently scans `Path("backend/app/domains")`, which only works when pytest is launched from the repository root; in this repo, both CI and local Make targets run pytest with `working-directory: backend` (`.github/workflows/ci.yml`, `Makefile`), so this path does not exist and the loop finds zero files, allowing new `org_id: str = Depends(get_org_id)` regressions to pass undetected. Use a path anchored to the test file/repo root (or `app/domains` under backend cwd) so the check runs in both execution contexts.

## VERIFIED

`backend/tests/static/test_no_org_id_str_annotation.py` (line ~28):

```python
def test_no_org_id_str_lying_annotation():
    offenders: list[str] = []
    for path in Path("backend/app/domains").rglob("*.py"):
        ...
```

CI executes pytest with cwd=backend (`.github/workflows/ci.yml` + Makefile rules). `Path("backend/app/domains")` from cwd=backend resolves to `backend/backend/app/domains` — does not exist. `.rglob("*.py")` returns empty iterator. Test passes vacuously.

## REQUIRED FIX

Anchor the path resolution to the test file's location, not to the cwd. Use `Path(__file__)` to walk up to the repository root and locate `backend/app/domains`:

```python
from pathlib import Path

# Resolve repo-root from this test file's location:
# backend/tests/static/test_no_org_id_str_annotation.py
#   parent[0] = backend/tests/static
#   parent[1] = backend/tests
#   parent[2] = backend
#   parent[3] = repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DOMAINS_ROOT = _REPO_ROOT / "backend" / "app" / "domains"


def test_no_org_id_str_lying_annotation():
    """Static check: no route handler annotates ``org_id: str = Depends(get_org_id)``.

    Q108: path resolved from __file__ rather than cwd, so the check runs
    correctly in both repo-root and cwd=backend execution contexts.
    """
    assert _DOMAINS_ROOT.is_dir(), (
        f"Expected app/domains at {_DOMAINS_ROOT} — path resolution broken"
    )
    offenders: list[str] = []
    for path in _DOMAINS_ROOT.rglob("*.py"):
        ... existing scan logic ...
    assert not offenders, f"org_id: str annotation lies: {offenders}"
```

The `assert _DOMAINS_ROOT.is_dir()` guard ensures that if the directory layout ever changes, the test fails loudly with the resolved path, not silently.

## CONSTRAINTS

- Do NOT change the AST scan logic — only the path resolution.
- Do NOT broaden the test to other directories (e.g., `backend/app/core`, `backend/app/services`) — out of scope.
- Keep the helper function `_has_depends_get_org_id` unchanged.
- Lint clean: `.venv/Scripts/python.exe -m ruff check backend/tests/static/test_no_org_id_str_annotation.py`
- Run from both contexts to verify:
  - From repo root: `python -m pytest backend/tests/static/test_no_org_id_str_annotation.py -v`
  - From backend cwd: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/static/test_no_org_id_str_annotation.py -v`
  - Both must produce identical results (passing if no offenders, failing with explicit list otherwise).

## REQUIRED TEST (validation that the guard works)

Add a meta-test that proves the path resolution is anchored correctly:

```python
def test_guard_path_resolves_to_real_directory():
    """Q108 invariant: _DOMAINS_ROOT must resolve to an existing dir
    independent of cwd. Catches the original bug where the guard scanned
    a non-existent path and passed vacuously."""
    assert _DOMAINS_ROOT.is_dir(), (
        f"_DOMAINS_ROOT must resolve regardless of cwd. Got: {_DOMAINS_ROOT}"
    )
    py_files = list(_DOMAINS_ROOT.rglob("*.py"))
    assert len(py_files) > 50, (
        f"Expected >50 Python files under app/domains, got {len(py_files)}. "
        "Path resolution likely broken."
    )
```

Optional second meta-test — temporarily inject a fake offender, assert the guard catches it:

```python
def test_guard_catches_lying_annotation_when_present(tmp_path, monkeypatch):
    """Q108 invariant: guard must FAIL when an offender exists. Validates
    the assertion path, not just the path resolution."""
    fake_offender = tmp_path / "domains" / "fake_route.py"
    fake_offender.parent.mkdir(parents=True)
    fake_offender.write_text(
        "from fastapi import Depends\n"
        "from app.core.tenancy.middleware import get_org_id\n"
        "async def lying_route(org_id: str = Depends(get_org_id)):\n"
        "    pass\n"
    )
    monkeypatch.setattr(
        "tests.static.test_no_org_id_str_annotation._DOMAINS_ROOT",
        tmp_path / "domains",
    )
    with pytest.raises(AssertionError, match="annotation lies"):
        test_no_org_id_str_lying_annotation()
```

The second test is optional — if monkeypatching the module-level `_DOMAINS_ROOT` is awkward, just document the manual smoke validation in the PR description.

## ACCEPTANCE

- `_DOMAINS_ROOT` resolved via `Path(__file__).resolve().parent.parent.parent.parent / "backend" / "app" / "domains"`
- `assert _DOMAINS_ROOT.is_dir()` guard added at top of test
- 1 new meta-test (`test_guard_path_resolves_to_real_directory`) passes
- Existing test still passes from BOTH cwd contexts (repo root + backend)
- Lint clean

## PR DESCRIPTION

Title: `chore(wealth): PR-Q108 — Codex P2 — annotation guard test path resolution`

Body sketch:

```markdown
## Codex Auto Review on PR-Q103 (Wave 6 S09 C-15) — 1 P2 catch

Q103's static guard test scanned `Path("backend/app/domains")` — a
relative path that only resolves from repo root. CI runs pytest with
`cwd=backend`, so the path never existed and the test passed silently
regardless of whether new offenders were introduced. Guard ineffective.

## Fix

Anchor path via `Path(__file__).resolve().parent.parent.parent.parent /
"backend" / "app" / "domains"`. Add `assert _DOMAINS_ROOT.is_dir()` to
fail loudly if the directory layout ever changes.

## Test plan

- [x] Meta-test confirms path resolves to real directory with >50 .py files
- [x] Existing guard runs identically from repo-root and cwd=backend
- [x] make lint clean
```

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.

## DISPATCH NOTES (for Andrei)

Branch: `chore/pr-q108-annotation-test-path-fix`
After agent push, return to me — I open the PR.
