# Fix: AI Agent — Tool Call Labels + Citation Rendering + Search Scope

## Context

InvestIntell Wealth OS — AI Agent drawer (`AiAgentDrawer.svelte`) backed by
`app/domains/wealth/routes/agent.py` (SSE stream) and two Jinja2 prompts:
`ai_engine/prompts/services/wealth_agent_system.j2` and `wealth_agent_user.j2`.

Three distinct problems to fix:

---

## Problem 1 — Tool call labels are internal jargon, not user-facing copy

The backend emits `detail` strings like:
- "Generating query embedding…"
- "Query embedded"
- "Searching knowledge base…"
- "Found 20 relevant chunks"
- "Generating answer…"
- "Answer generated"

These are developer-facing. Users don't know what "embedding" means and shouldn't see it.

### Fix 1a — Backend: rewrite `detail` strings in `agent.py`

File: `backend/app/domains/wealth/routes/agent.py`

Replace all six `detail` values in the `event_generator()` function:

```python
# Embedding running
"detail": "Generating query embedding…"
→ "detail": "Analyzing question…"

# Embedding complete
"detail": "Query embedded"
→ "detail": "Question analyzed"

# Vector search running
"detail": "Searching knowledge base…"
→ "detail": "Searching funds, reports, and filings…"

# Vector search complete — keep the count but rephrase
"detail": f"Found {len(unique_chunks)} relevant chunks"
→ "detail": f"Found {len(unique_chunks)} relevant sources"

# LLM running
"detail": "Generating answer…"
→ "detail": "Composing answer…"

# LLM complete
"detail": "Answer generated"
→ "detail": "Answer ready"
```

### Fix 1b — Frontend: clean up tool call rendering in `AiAgentDrawer.svelte`

File: `frontends/wealth/src/lib/components/AiAgentDrawer.svelte`

The `.agent-tool` div currently shows the icon + `tc.detail` text for ALL tool calls,
including both running and complete states. Only running tool calls should be visible
while they are in progress. Once complete, they disappear — the answer itself is the
result, not a "done" badge.

Change the `{#each msg.toolCalls ...}` block:

```svelte
<!-- OLD: renders all tool calls including completed ones -->
{#each msg.toolCalls as tc (tc.tool + tc.status)}
    <div class="agent-tool" class:complete={tc.status === "complete"} class:running={tc.status === "running"}>
        {#if tc.status === "running"}
            <Loader2 size={12} strokeWidth={2} class="agent-tool-spin" />
        {:else}
            <Wrench size={12} strokeWidth={2} />
        {/if}
        <span>{tc.detail}</span>
    </div>
{/each}

<!-- NEW: only show running tool calls; completed ones vanish -->
{#each msg.toolCalls.filter(tc => tc.status === "running") as tc (tc.tool)}
    <div class="agent-tool running">
        <SpinnerGap size={12} weight="light" class="agent-tool-spin" />
        <span>{tc.detail}</span>
    </div>
{/each}
```

Note: `Loader2` is a lucide icon that may not exist after the icon migration.
Use `SpinnerGap` from `phosphor-svelte` instead (already imported at the top of the file).
Also remove the `Wrench` import if it becomes unused.

---

## Problem 2 — Inline citation IDs in answer text (e.g. "[dd_chapter_02ca3b53-…]")

The LLM is instructed to embed `[chunk_id]` inline in the answer text. These UUIDs
appear raw in the message bubble. Two things need to change:

### Fix 2a — System prompt: remove inline citation requirement

File: `backend/ai_engine/prompts/services/wealth_agent_system.j2`

The current prompt instructs the LLM to embed chunk IDs inline in the answer.
Remove that requirement. Citations belong only in the `citations` array, not in
the answer prose.

Replace the Response Format section:

```
## Response Format
Return a JSON object with exactly two keys:
{
  "answer": "Your answer in markdown format with inline citations like [chunk_id].",
  "citations": [
    {"chunk_id": "abc-123", "excerpt": "Brief quote from the source"}
  ]
}
```

With:

```
## Response Format
Return a JSON object with exactly two keys:
{
  "answer": "Your answer in plain prose. Do NOT embed chunk IDs, references, or brackets
             anywhere in the answer text. Write as if citations are shown separately.",
  "citations": [
    {"chunk_id": "abc-123", "excerpt": "One-sentence excerpt justifying this source"}
  ]
}
```

Keep the rest of the system prompt unchanged.

### Fix 2b — Frontend: rework citation rendering

File: `frontends/wealth/src/lib/components/AiAgentDrawer.svelte`

The current citation strip shows truncated chunk IDs like `dd_chapter_02ca3b…`.
Most answers will come from embedded tabular data (nav_timeseries, fund_risk_metrics,
sec_13f_holdings) that have no associated document — showing a chunk ID for these
is meaningless.

New rules:
1. Only render the citations block if at least one citation has a non-empty `excerpt`.
2. Show a short human-readable label derived from the `chunk_id` prefix, not the raw UUID.
3. Citations that look like pure data rows (no `excerpt`) are silently omitted.

Replace the citations rendering block:

```svelte
<!-- OLD -->
{#if msg.citations && msg.citations.length > 0}
    <div class="agent-citations">
        <span class="agent-citations-label">Sources ({msg.citations.length})</span>
        {#each msg.citations as cite (cite.chunk_id)}
            <div class="agent-citation" title={cite.excerpt || cite.chunk_id}>
                <FileText size={11} strokeWidth={1.5} />
                <span>{cite.chunk_id.slice(0, 12)}…</span>
            </div>
        {/each}
    </div>
{/if}

<!-- NEW -->
{#if msg.citations && msg.citations.length > 0}
    {@const documentedCites = msg.citations.filter(c => c.excerpt && c.excerpt.trim().length > 0)}
    {#if documentedCites.length > 0}
        <div class="agent-citations">
            <span class="agent-citations-label">Sources</span>
            {#each documentedCites as cite (cite.chunk_id)}
                <div class="agent-citation" title={cite.excerpt}>
                    <FileText size={11} weight="light" />
                    <span>{citationLabel(cite.chunk_id)}</span>
                </div>
            {/each}
        </div>
    {/if}
{/if}
```

Add the `citationLabel` helper function in the `<script>` block:

```ts
// Derive a short human-readable label from chunk_id
// Examples:
//   "dd_chapter_02ca3b53-ccce-46e9-b636-99b6d3241ac5" → "DD Report"
//   "macro_review_628a30aa-3223-44b4-af25-695f81bc9edc" → "Macro Review"
//   "adv_brochure_1954bd14-aa2f-4451-b5dc-90a2c6503293" → "ADV Brochure"
//   "wealth_chunk_abc123" → "Research"
function citationLabel(chunkId: string): string {
    if (chunkId.startsWith("dd_chapter")) return "DD Report";
    if (chunkId.startsWith("macro_review")) return "Macro Review";
    if (chunkId.startsWith("adv_brochure") || chunkId.startsWith("brochure")) return "ADV Brochure";
    if (chunkId.startsWith("fact_sheet")) return "Fact Sheet";
    if (chunkId.startsWith("prospectus")) return "Prospectus";
    if (chunkId.startsWith("flash_report")) return "Flash Report";
    if (chunkId.startsWith("spotlight")) return "Manager Spotlight";
    if (chunkId.startsWith("outlook")) return "Investment Outlook";
    return "Document";
}
```

---

## Problem 3 — Verify and document search scope in agent.py

The current agent searches three sources in `event_generator()`:
1. `search_fund_analysis_sync` — org-scoped (DD chapters, macro reviews) ← correct
2. `search_fund_firm_context_sync` — firm context (ADV brochures) ← only if CRD provided
3. `search_esma_funds_sync` — global fund search ← only if no instrument_id

### Fix 3 — Add a comment block documenting the search scope

File: `backend/app/domains/wealth/routes/agent.py`

After the deduplication block (after `unique_chunks = unique_chunks[:20]`), add:

```python
# ── Search scope summary ──────────────────────────────────────────────────────
# org_chunks:    wealth_vector_chunks WHERE organization_id = org_id
#                entity_types: dd_chapter, macro_review, fact_sheet, portfolio
#                (org-scoped — only this tenant's produced content)
#
# firm_chunks:   wealth_vector_chunks WHERE entity_type IN ('firm', 'adv_brochure')
#                AND (sec_crd = ? OR esma_manager_id = ?)
#                (global — SEC ADV data shared across tenants, triggered by CRD/ESMA)
#
# global_chunks: wealth_vector_chunks WHERE entity_type IN ('fund', 'esma_fund', 'etf')
#                AND organization_id IS NULL
#                (global — public fund registry data, triggered when no instrument_id)
#
# The agent does NOT search: nav_timeseries, fund_risk_metrics, macro_data,
# sec_13f_holdings or any other hypertable. Those are queried via dedicated
# routes, not via the vector search. If users ask about current NAV or risk
# metrics, the agent should acknowledge this limitation.
# ─────────────────────────────────────────────────────────────────────────────
```

No behavior changes — this is documentation only for future maintainers.

---

## Definition of Done

- [ ] `pnpm --filter netz-wealth-os run check` passes
- [ ] Agent running state shows "Analyzing question…" / "Searching funds, reports, and filings…" / "Composing answer…"
- [ ] Running tool calls disappear once complete — no "complete" badges in the UI
- [ ] Answer text contains no `[chunk_id]` brackets
- [ ] Citations strip: only renders if at least one citation has an `excerpt`
- [ ] Citations show human-readable labels ("DD Report", "ADV Brochure") not UUID prefixes
- [ ] Empty-state answer for tabular data queries shows no citation strip at all
- [ ] `citationLabel()` function handles all known chunk_id prefixes

## What NOT to do

- Do NOT change the SSE event protocol — `tool_call`, `chunk`, `citations`, `done` events stay as-is
- Do NOT remove the `citations` array from the LLM response format — only remove inline `[id]` from answer prose
- Do NOT filter citations on the backend — filtering is purely a frontend concern
- Do NOT change `pgvector_search_service.py` — search scope is correct, fix is documentation only
- Do NOT add a "Sources" header when `documentedCites` is empty
- Do NOT touch any other routes or services
