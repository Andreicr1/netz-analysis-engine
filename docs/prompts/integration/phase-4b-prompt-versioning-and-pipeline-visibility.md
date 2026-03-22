# Phase 4B — Prompt Versioning Fix + Document Pipeline Visibility

**Status:** Ready
**Estimated scope:** ~200 lines changed
**Risk:** Low (small fixes + read-only UI additions)
**Prerequisite:** None

---

## Context

Two small admin/ops items:

1. **Prompt versioning fix:** Admin PromptEditor has TODOs — `actor_id` and `change_summary` not returned by backend `/versions` endpoint.
2. **Pipeline visibility:** Document ingestion pipeline runs in background but no frontend page shows processing status.

---

## Task 1: Prompt Versioning Fix

### Step 1.1 — Backend: add fields to version response

Read `backend/app/domains/admin/routes/prompts.py`. Find the prompt versions endpoint and its response schema. Add `actor_id` and `change_summary` to the response.

Check the prompt version DB model to verify these columns exist. If they do:

```python
# In the version response schema
actor_id: str | None = None
change_summary: str | None = None
```

If `change_summary` doesn't exist in the model, add it as an optional field that can be passed during version creation.

### Step 1.2 — Backend: accept `change_summary` on create

If creating a new prompt version, the request body should accept `change_summary`:

```python
class PromptVersionCreate(BaseModel):
    content: str
    change_summary: str | None = None
```

### Step 1.3 — Frontend: fix PromptEditor TODOs

In `frontends/admin/src/lib/components/PromptEditor.svelte`:

- **Line ~47:** Replace `// TODO: pending backend — actor_id not returned by /versions endpoint` with actual actor display
- **Line ~49:** Replace `// TODO: pending backend — change_summary not returned by /versions endpoint` with actual summary display

```svelte
<!-- Version history item -->
<div class="flex justify-between">
  <span>{version.change_summary || 'No summary'}</span>
  <span class="text-muted">{version.actor_id || 'Unknown'}</span>
  <span class="text-muted">{formatDateTime(version.created_at)}</span>
</div>
```

### Step 1.4 — Frontend: editable summary on create

When creating/saving a new prompt version, add a text input for `change_summary`:

```svelte
<input
  type="text"
  placeholder="What changed? (optional)"
  bind:value={changeSummary}
/>
```

---

## Task 2: Document Pipeline Visibility

### Step 2.1 — Determine pipeline status data source

Read the existing document models and routes to understand how pipeline status is tracked. Check:
- `backend/app/domains/credit/` — documents routes/models
- `backend/app/domains/wealth/` — documents routes/models
- Look for `pipeline_status`, `processing_stage`, or similar fields on document models

The pipeline stages are: uploaded → OCR → classified → chunked → embedded → indexed.

### Step 2.2 — Credit frontend: Pipeline status component

Create `frontends/credit/src/routes/(team)/funds/[fundId]/documents/PipelineStatus.svelte`:

```svelte
<script>
  let { stage, error = null } = $props();

  const stages = ['uploaded', 'ocr', 'classified', 'chunked', 'embedded', 'indexed'];
  const currentIndex = stages.indexOf(stage);
</script>

<div class="flex items-center gap-1">
  {#each stages as s, i}
    <div class="flex items-center gap-1">
      <div class="w-2 h-2 rounded-full {i <= currentIndex ? 'bg-accent' : 'bg-muted'}" />
      <span class="text-xs {i === currentIndex ? 'font-medium' : 'text-muted'}">{s}</span>
    </div>
    {#if i < stages.length - 1}
      <div class="w-4 h-px {i < currentIndex ? 'bg-accent' : 'bg-muted'}" />
    {/if}
  {/each}
</div>

{#if error}
  <div class="text-xs text-danger mt-1">{error}</div>
{/if}
```

### Step 2.3 — Integrate into documents page

**Credit:** In the documents table/list (find exact path under `frontends/credit/src/routes/(team)/funds/[fundId]/documents/`), add a "Status" column that renders `PipelineStatus` component per document.

**Wealth:** In `frontends/wealth/src/routes/(team)/documents/` (if exists), add inline pipeline status column.

### Step 2.4 — Provenance label

Per UX Doctrine §17: pipeline stages are "deterministic process indicators" — not AI-generated.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/domains/admin/routes/prompts.py` | Add actor_id + change_summary to version response |
| `backend/app/domains/admin/schemas/prompts.py` | Add fields to version schema |
| `frontends/admin/src/lib/components/PromptEditor.svelte` | Fix TODOs at lines ~47, ~49 |
| `frontends/credit/.../documents/PipelineStatus.svelte` | New component |
| Credit documents page | Add pipeline status column |
| Wealth documents page (if exists) | Add pipeline status column |

## Acceptance Criteria

- [ ] Version history shows who changed what and when (actor + summary)
- [ ] `change_summary` editable on version create
- [ ] Each document shows current pipeline stage
- [ ] Failed stages show error details in red
- [ ] UX Doctrine §17: pipeline stages labeled as deterministic process indicators
- [ ] `make check` passes

## Gotchas

- PromptEditor path may differ — search for `PromptEditor` component in admin frontend
- Pipeline status field may not exist on document models — check ORM first. If missing, this task requires a migration (flag as separate work)
- Credit and wealth document pages may have different structures — check both
- Use `formatDateTime` from `@netz/ui` for version timestamps
