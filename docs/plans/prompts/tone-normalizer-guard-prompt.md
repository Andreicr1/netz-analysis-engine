# Fix: Tone Normalizer Guard + Paired Logging

> Execute in a fresh session on branch `refactor/deep-review-legacy-blob-removal`.

---

## Problem

1. **Bug:** When chapter generation fails (HTTP 400, context overflow), `chapters.py` returns `"*Chapter N: Title — generation failed: ...*"` as `section_text`. This error placeholder flows into the tone normalizer, which sends it to the LLM as if it were real content. The LLM hallucinates an entire chapter about a different fund. Critical data integrity bug.

2. **No paired logging:** The tone normalizer doesn't log `deal_id` or `chapter_tag` with input/output lengths, making it impossible to reconstruct first-pass vs tone-normalized output for quality comparison.

## Files to Read

1. `backend/vertical_engines/credit/memo/tone.py` — the tone normalizer
2. `backend/vertical_engines/credit/memo/chapters.py` — search for `generation failed` to see the error format
3. `backend/vertical_engines/credit/deep_review/service.py` — search for `run_tone_normalizer` to see callers (sync ~line 969, async ~line 2113)

## Fix 1 — Guard in `tone.py:_run_pass1_chapter()`

Add a guard at the top of `_run_pass1_chapter()` that detects error placeholders and skips the LLM rewrite:

```python
_GENERATION_FAILED_MARKERS = ("generation failed", "LLM returned empty")

def _run_pass1_chapter(chapter_tag: str, text: str, *, deal_id: str = "") -> tuple[str, int, bool]:
    """..."""
    # Guard: skip rewrite for failed chapters — propagate error as-is
    if text.startswith("*") and any(m in text for m in _GENERATION_FAILED_MARKERS):
        logger.info(
            "tone_normalizer.chapter_diff",
            deal_id=deal_id,
            chapter_id=chapter_tag,
            pass_num=1,
            input_len=len(text),
            output_len=len(text),
            skipped=True,
        )
        return text, 0, True  # (text, delta, skipped)
    # ... rest of function
```

**Return type change:** `tuple[str, int]` → `tuple[str, int, bool]` (added `skipped` flag). Update all callers of `_run_pass1_chapter`.

## Fix 2 — Paired logging with deal_id

### 2a. Thread `deal_id` into the tone normalizer

**`run_tone_normalizer()` signature:** Add `deal_id: str = ""` parameter.

**`_pass1_async()` signature:** Add `deal_id: str = ""`, pass through to `_run_pass1_chapter`.

**`_run_pass2()` — add deal_id to logging** (not to LLM call).

### 2b. Add paired logging in `_run_pass1_chapter`

After the LLM call succeeds (line ~94), add:

```python
logger.info(
    "tone_normalizer.chapter_diff",
    deal_id=deal_id,
    chapter_id=chapter_tag,
    pass_num=1,
    input_len=len(text),
    output_len=len(revised),
    skipped=False,
)
```

Replace the existing `logger.debug("TONE_PASS1", ...)` with this — same info, better structure.

### 2c. Add paired logging in `_run_pass2`

After Passe 2 completes, log per-chapter excerpt stats:

```python
for ch_tag, text in chapters.items():
    logger.info(
        "tone_normalizer.chapter_diff",
        deal_id=deal_id,
        chapter_id=ch_tag,
        pass_num=2,
        input_len=len(text),
        output_len=len(text),  # pass2 doesn't rewrite chapters
        skipped=False,
    )
```

### 2d. Update callers in `service.py`

Both sync (~line 969) and async (~line 2113) callers of `run_tone_normalizer` must pass `deal_id=str(deal_id)`.

### 2e. Update `_pass1_async` to handle the new return tuple

`_run_pass1_chapter` now returns `(text, delta, skipped)`. Update `_pass1_async` to unpack correctly and collect skipped counts.

## Acceptance Criteria

- `make check` passes
- When a chapter has `"*Chapter N — generation failed*"`, tone normalizer logs `skipped=True` and returns the error text unchanged
- Every chapter processed by Passe 1 emits a `tone_normalizer.chapter_diff` log with `deal_id`, `chapter_id`, `pass_num`, `input_len`, `output_len`, `skipped`
- No change to the tone normalizer's return schema (`ToneReviewResult`)

## Commit

```
fix(memo): guard tone normalizer against failed chapter placeholders

Skip LLM rewrite when chapter text is an error placeholder ("generation
failed", "LLM returned empty"). Add paired logging with deal_id,
chapter_id, pass_num, input/output lengths for baseline comparison.
```
