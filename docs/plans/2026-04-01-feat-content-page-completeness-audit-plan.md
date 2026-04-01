---
title: "feat: Content Page Completeness — Preview, PDF Viewer, Monthly Report Wiring"
type: feat
status: active
date: 2026-04-01
deepened: 2026-04-01
---

# Content Page Completeness — Preview, PDF Viewer, Monthly Report Wiring

## Enhancement Summary

**Deepened on:** 2026-04-01
**Sections enhanced:** 4 phases + security + architecture
**Research agents used:** Svelte 5 patterns, PDF preview/presigned URLs, learnings/solutions, macro PDF templates, XSS security

### Key Improvements from Research
1. **DOMPurify defense-in-depth** — already installed (v3.3.3) but unused; activate in shared `renderMarkdown()` to complement backend nh3 sanitization
2. **`StorageClient.generate_read_url()` already exists** — both Local and R2 implementations support presigned read URLs, eliminating need for a new backend pattern in P3
3. **`createSSEStream()` utility** from `@investintell/ui` — use instead of manual `fetch()` + `ReadableStream` for content generation SSE (P2.4); has exponential backoff, heartbeat timeout, max 4 concurrent connections
4. **Macro PDF reuses `content_report.py`** — call `render_content_report()` directly with macro narrative markdown instead of building a new template from scratch
5. **Resilient loaders** — `Promise.allSettled` for page data loading (learned from `endpoint-coverage-multi-agent-review` solution)

### New Considerations Discovered
- `renderMarkdown()` regex is safe-by-construction but fragile — extracting to shared module + adding DOMPurify creates proper defense-in-depth
- SSE client has max 4 concurrent connections per tab — content page must disconnect SSE on navigation away
- CI pipeline requires `svelte-kit sync` before `svelte-check` — new routes must pass type-check
- Backend nh3 sanitizes at persist boundary (`sanitize_llm_text()`) in all 5 engines (outlook, flash, spotlight, DD chapters, critic) — frontend DOMPurify is redundant but defense-in-depth best practice

---

## Overview

The `/content` page is the client-facing hub for generated investment content (Outlooks, Flash Reports, Manager Spotlights). A full audit revealed **7 gaps** that prevent the page from functioning as a proper IC (Investment Committee) review workbench:

1. **No in-app content preview** — users cannot read `content_md` before approving
2. **No PDF viewer** — all PDFs are download-only, no in-app preview
3. **Monthly Report has no frontend** — backend complete, frontend missing
4. **Macro Committee Review has no PDF** — JSON only, no formal distribution
5. **`GET /content/{id}` endpoint missing** — no way to fetch full content
6. **Content generation uses polling** instead of SSE
7. **Document page shows only metadata** — no file preview

The most critical gap: **users approve content blindly** — they cannot read the generated markdown before clicking "Approve". This breaks the IC governance workflow.

## Proposed Solution

Four phases, ordered by user impact:

| Phase | Scope | Impact |
|-------|-------|--------|
| **P0** | Content detail route + markdown preview + PDF inline viewer | Unblocks IC approval workflow |
| **P1** | Monthly Report frontend wiring | Exposes fully-built backend feature |
| **P2** | Macro Review PDF + Content SSE | Formal distribution + responsive UX |
| **P3** | Document preview + Content search/filter | Polish |

---

## Phase 0 — Content Preview + PDF Viewer (P0)

**Goal:** IC members can read generated content before approving, and preview PDFs in-app.

### 0.1 Backend: `GET /content/{id}` endpoint

`ContentRead` schema already exists in `backend/app/domains/wealth/schemas/content.py:27-29` with `content_md: str | None` and `content_data: dict | None`. Only the route is missing.

**File:** `backend/app/domains/wealth/routes/content.py`

Add between the `list_content` endpoint (line ~242) and the `approve_content` endpoint (line ~247):

```python
@router.get(
    "/{content_id}",
    response_model=ContentRead,
    summary="Get content detail with markdown body",
)
async def get_content(
    content_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> ContentRead:
    _require_feature()
    result = await db.execute(
        select(WealthContent).where(WealthContent.id == content_id),
    )
    content = result.scalar_one_or_none()
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")
    return ContentRead.model_validate(content)
```

**Import:** Add `ContentRead` to the existing import from `schemas.content`.

#### Research Insights

**Route ordering caution:** This `GET /{content_id}` endpoint must be placed AFTER the `GET /` (list) endpoint but BEFORE any `POST /{content_id}/approve` endpoint. FastAPI resolves routes in declaration order — if placed before the list endpoint, `/content` would try to parse "content" as a UUID and 422.

**Resilient loader pattern:** The frontend `+page.server.ts` should use error handling that doesn't break the page:
```typescript
const content = await api.get<ContentFull>(`/content/${params.id}`).catch(() => null);
if (!content) throw error(404, "Content not found");
```

### 0.2 Frontend: Content detail route `/content/[id]`

Create a new route that fetches the full content and renders it with the same markdown approach used by DD Reports.

**New files:**
- `frontends/wealth/src/routes/(app)/content/[id]/+page.server.ts`
- `frontends/wealth/src/routes/(app)/content/[id]/+page.svelte`

**`+page.server.ts`:**
```typescript
import { error } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";
import type { ContentFull } from "$lib/types/content";

export const load: PageServerLoad = async ({ parent, params }) => {
  const { token, actor } = await parent();
  const api = createServerApiClient(token);
  const content = await api.get<ContentFull>(`/content/${params.id}`).catch(() => null);
  if (!content) throw error(404, "Content not found");
  return { content, actorId: actor?.user_id ?? null };
};
```

**`+page.svelte`:** Reader layout with:
- Sticky header: title, type badge, status badge, language
- Main body: rendered `content_md` via `renderMarkdown()` with DOMPurify sanitization
- Sidebar/footer: `content_data` as collapsible key-value pairs (same `flattenObject()` pattern from DD report evidence at `dd-reports/[fundId]/[reportId]/+page.svelte:225-236`)
- Action bar: Approve button (with ConsequenceDialog, self-approval block), Download PDF button
- Back link to `/content`

**Reference implementation:** DD report detail viewer at `dd-reports/[fundId]/[reportId]/+page.svelte`:
- Approval flow with ConsequenceDialog: lines 49-80, 447-499
- Evidence display with `flattenObject()`: lines 225-236, 359-388
- Markdown rendering: lines 208-221

#### Research Insights

**Approval pattern from DD Reports** (critical for content detail page):
```typescript
// Role-based + self-approval check (from dd-reports/[fundId]/[reportId]/+page.svelte:51-67)
const IC_ROLES = ["admin", "super_admin", "investment_team"];
let canApprove = $derived(
  (content.status === "draft" || content.status === "review") &&
  actorRole !== null &&
  IC_ROLES.includes(actorRole) &&
  actorId !== content.created_by
);
```

**ConsequenceDialog** reuse — same component used in DD reports and content list page. Include metadata array showing content type and language:
```typescript
metadata={[
  { label: "Type", value: contentTypeLabel(content.content_type) },
  { label: "Language", value: content.language.toUpperCase() },
]}
```

### 0.3 Extract shared `renderMarkdown` utility

The same markdown rendering function exists inline in the DD report viewer. Extract it to a shared module so both pages (and future pages) reuse it.

**New file:** `frontends/wealth/src/lib/utils/render-markdown.ts`

```typescript
import DOMPurify from "dompurify";

const ALLOWED_TAGS = [
  "h1", "h2", "h3", "h4", "h5", "h6",
  "p", "strong", "em", "code", "ul", "ol", "li",
  "a", "sup", "sub", "br", "blockquote", "pre",
  "table", "thead", "tbody", "tr", "th", "td",
];
const ALLOWED_ATTR = ["href", "title", "class", "colspan", "rowspan"];

/**
 * Safe regex-based markdown → HTML renderer with DOMPurify defense-in-depth.
 * Backend nh3 sanitizes at persist boundary; this is the frontend safety net.
 * Supports: headings, bold, italic, code, lists, paragraphs.
 * Output uses .rw-* class names for scoped styling.
 */
export function renderMarkdown(md: string | null): string {
  if (!md) return '<p class="rw-empty">Content not yet generated.</p>';
  const html = md
    .replace(/^### (.+)$/gm, '<h3 class="rw-h3">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 class="rw-h2">$1</h2>')
    .replace(/^# (.+)$/gm, '<h1 class="rw-h1">$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, '<code class="rw-code">$1</code>')
    .replace(/^- (.+)$/gm, '<li class="rw-li">$1</li>')
    .replace(/(<li[^>]*>.*<\/li>\n?)+/g, '<ul class="rw-ul">$&</ul>')
    .replace(/^(?!<[hul]|<li|<strong|<em|<code)(.+)$/gm, '<p class="rw-p">$1</p>')
    .replace(/\n{2,}/g, "");
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
  });
}

/**
 * Recursively flatten a nested object into dot-notation key-value pairs.
 * Reused from DD report evidence display.
 */
export function flattenObject(
  obj: Record<string, unknown>,
  prefix = "",
): Array<{ key: string; value: string }> {
  const entries: Array<{ key: string; value: string }> = [];
  for (const [k, v] of Object.entries(obj)) {
    const label = prefix ? `${prefix} › ${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) {
      entries.push(...flattenObject(v as Record<string, unknown>, label));
    } else {
      entries.push({ key: label, value: String(v ?? "—") });
    }
  }
  return entries;
}
```

**New file:** `frontends/wealth/src/lib/utils/render-markdown.css`
- Move `.rw-h1`, `.rw-h2`, `.rw-h3`, `.rw-code`, `.rw-ul`, `.rw-li`, `.rw-p`, `.rw-empty` styles from DD report viewer (`dd-reports/[fundId]/[reportId]/+page.svelte:676-729`).

**Update:** `dd-reports/[fundId]/[reportId]/+page.svelte` to import `renderMarkdown` and `flattenObject` from the shared utility instead of defining inline.

#### Research Insights

**Security: DOMPurify defense-in-depth** — Backend already sanitizes via nh3 at persist boundary (`sanitize_llm_text()` in all 5 engines: `investment_outlook.py:22`, `flash_report.py`, `manager_spotlight.py`, `dd_report/chapters.py`, `critic/parser.py`). The nh3 allowlist matches our DOMPurify config: safe Markdown tags only, no `<script>`, `<style>`, `<iframe>`, `<object>`, `<embed>`, `<form>`. Adding DOMPurify at the render boundary is redundant but follows defense-in-depth principle — if backend sanitization has a bug, frontend catches it.

**Why DOMPurify over regex-only:** The current `renderMarkdown()` regex is safe-by-construction (only produces known HTML), but it's fragile — any future modification could introduce an XSS vector. DOMPurify.sanitize() as the final step ensures output is always safe regardless of regex changes.

**`ALLOWED_ATTR` must include `class`** — the regex adds `class="rw-h1"` etc., and DOMPurify would strip those without explicit allowlisting.

**`flattenObject()` extraction** — same recursive helper exists at `dd-reports/[fundId]/[reportId]/+page.svelte:225-236`. Extract alongside `renderMarkdown` to eliminate both duplications.

### 0.4 Content card click-through

**File:** `frontends/wealth/src/routes/(app)/content/+page.svelte`

Make each `.ct-card` clickable — wrap the card title in an `<a href="/content/{item.id}">` so users can navigate to the detail view. Keep the card actions (Approve, Download, Retry) as they are.

#### Research Insights

**SvelteKit navigation:** Use `<a>` tag (not `goto()`) for progressive enhancement — works without JS. The card title `.ct-title` (line ~244) is the natural click target:
```svelte
<a href="/content/{item.id}" class="ct-title-link">
  <h3 class="ct-title">{item.title ?? contentTypeLabel(item.content_type)}</h3>
</a>
```

**Prevent event bubbling** on action buttons (Approve, Download, Retry) — they're inside the card but should NOT navigate. They already use `onclick` handlers which stop at the button, but verify no parent `<a>` wraps the actions area.

### 0.5 Frontend: ContentFull type

**File:** `frontends/wealth/src/lib/types/content.ts`

Add:

```typescript
export interface ContentFull extends ContentSummary {
  content_md: string | null;
  content_data: Record<string, unknown> | null;
}
```

### 0.6 PDF Inline Preview

Instead of installing `pdfjs-dist` (heavy, 2.5MB), use a lightweight `<object>` approach with blob URLs. The browser's native PDF renderer handles display.

**New component:** `frontends/wealth/src/lib/components/PdfPreview.svelte`

```svelte
<script lang="ts">
  import { onDestroy } from "svelte";

  interface Props {
    blobUrl: string | null;
    filename?: string;
  }
  let { blobUrl, filename = "document.pdf" }: Props = $props();

  // Cleanup blob URL on destroy to prevent memory leaks
  onDestroy(() => {
    if (blobUrl) URL.revokeObjectURL(blobUrl);
  });
</script>

{#if blobUrl}
  <div class="pdf-preview">
    <object data={blobUrl} type="application/pdf" title={filename}>
      <p class="pdf-fallback">
        PDF preview not available in this browser.
        <a href={blobUrl} download={filename}>Download PDF</a>
      </p>
    </object>
  </div>
{/if}

<style>
  .pdf-preview {
    width: 100%;
    border: 1px solid var(--ii-border-subtle);
    border-radius: var(--ii-radius-md, 12px);
    overflow: hidden;
  }
  .pdf-preview object {
    width: 100%;
    height: 80vh;
    min-height: 600px;
  }
  .pdf-fallback {
    padding: var(--ii-space-stack-lg, 24px);
    text-align: center;
    color: var(--ii-text-muted);
    font-size: var(--ii-text-small, 0.8125rem);
  }
  .pdf-fallback a {
    color: var(--ii-brand-primary);
    text-decoration: underline;
  }
</style>
```

**Usage in content detail page:** Add a "Preview PDF" / "Read Content" tab toggle. "Read Content" shows rendered `content_md`; "Preview PDF" fetches blob and renders `PdfPreview`. PDF preview only available when `status >= "approved"` (download endpoint gates on approval status).

**Usage in DD report page:** Add "Preview Fact Sheet" button alongside existing "Download PDF" button in `dd-reports/[fundId]/[reportId]/+page.svelte`.

#### Research Insights

**Browser compatibility:** `<object type="application/pdf">` works in Chrome, Edge, Firefox (all have built-in PDF renderers). Safari on iOS does NOT render inline PDFs — the `<p>` fallback with download link handles this gracefully.

**Blob URL lifecycle:** The component manages its own cleanup via `onDestroy`. The caller creates the blob URL via `URL.createObjectURL(blob)` from `api.getBlob()` — same pattern used in 4 places in the codebase already (`content/+page.svelte:160`, `dd-reports/.../+page.svelte:138`, `LongFormReportPanel.svelte:228`, `table-export.ts:45`).

**Security of blob URLs:** Blob URLs are same-origin, ephemeral, and cannot be shared across tabs/users. They're revoked on component destroy. No presigned URL needed for this pattern — the auth check happens at `getBlob()` fetch time.

**Alternative considered:** `<iframe src={blobUrl}>` also works but `<object>` has better fallback semantics (content inside the tag is shown when the object fails to load).

### 0.7 Acceptance Criteria

- [x] `GET /content/{id}` returns `ContentRead` with `content_md` + `content_data`
- [x] `/content/[id]` page renders markdown body with same quality as DD report viewer
- [x] Cards on `/content` are clickable → navigate to `/content/[id]`
- [x] `renderMarkdown()` extracted to shared utility with DOMPurify sanitization
- [x] `flattenObject()` extracted alongside `renderMarkdown` to shared utility
- [x] DD report viewer updated to import from shared utility (no behavior change)
- [x] PDF preview works via `<object>` tag with blob URL (approved content only)
- [x] `PdfPreview.svelte` component created and reusable
- [x] Approve/Download actions work from detail page with ConsequenceDialog
- [x] Self-approval block enforced on detail page
- [ ] `svelte-kit sync && svelte-check` passes with new routes

---

## Phase 1 — Monthly Report Frontend Wiring (P1)

**Goal:** Expose the fully-built Monthly Report backend via the portfolios page.

### 1.1 Monthly Report Panel Component

**New file:** `frontends/wealth/src/lib/components/MonthlyReportPanel.svelte`

Follow the same pattern as `LongFormReportPanel.svelte` (SSE-driven generation with PDF download):

1. **Generate button** → `POST /reporting/model-portfolios/{portfolioId}/monthly-report`
2. **SSE stream** → `GET .../monthly-report/stream/{jobId}` via `fetch()` + `ReadableStream`
3. **PDF download** → `GET .../monthly-report/{jobId}/pdf` via `api.getBlob()`
4. **Status display:** generating spinner → "done" with download button → error with retry

The component is simpler than `LongFormReportPanel` since monthly reports don't have per-chapter progress — just started/done/error events.

**Props:**
```typescript
interface Props {
  portfolioId: string;
  portfolioName: string;
}
```

#### Research Insights

**SSE implementation choice:** Use the manual `fetch()` + `ReadableStream` pattern from `LongFormReportPanel.svelte:94-170` rather than `createSSEStream()` from `@investintell/ui`. Reason: `createSSEStream` has reconnection logic (exponential backoff, max 5 retries) which is appropriate for long-lived dashboard streams, but report generation is a one-shot operation — reconnecting to a completed job is pointless. The manual pattern aborts cleanly and shows a final state.

**Reference SSE frame parsing** from `LongFormReportPanel.svelte:120-155`:
```typescript
// Parse SSE frames: "event:" for type, "data:" for payload, empty line = end of event
for (const line of lines) {
  if (line.startsWith("event:")) {
    currentEventType = line.slice(6).trim();
  } else if (line.startsWith("data:")) {
    const d = line.slice(5).trim();
    currentData += currentData ? `\n${d}` : d;
  } else if (line === "" || line.startsWith(":")) {
    // End of event frame or heartbeat comment
    if (currentData) {
      try { handleSSEEvent(currentEventType, JSON.parse(currentData)); }
      catch { /* malformed JSON — skip */ }
    }
    currentEventType = "message";
    currentData = "";
  }
}
```

**Backend events for monthly report** (from `routes/monthly_report.py:168-243`):
- `"started"` → `{"portfolio_id": str}`
- `"done"` → `{"status": "completed", "pdf_storage_key": str, "size_bytes": int}`
- `"error"` → `{"error": str}`

**429 handling:** Backend semaphore (max 2) returns HTTP 429 when full. Frontend should show user-friendly message:
```typescript
if (e instanceof Error && e.message.includes("429")) {
  error = "Too many concurrent reports. Please wait for ongoing reports to finish.";
}
```

**AbortController pattern** — one per stream, cleaned up on new generation and in finally block (from `LongFormReportPanel.svelte:51,60,96,162`).

### 1.2 Wire into Portfolios Page

**File:** `frontends/wealth/src/routes/(app)/portfolios/[profile]/+page.svelte`

Add `MonthlyReportPanel` as a third block in the "Reports" tab (after Fact Sheets and Long-Form Report, around line ~750):

```svelte
<!-- Monthly Report -->
<div class="reports-block">
  <h3>Monthly Client Report</h3>
  <MonthlyReportPanel
    portfolioId={modelPortfolio.id}
    portfolioName={modelPortfolio.display_name}
  />
</div>
```

### 1.3 Acceptance Criteria

- [x] `MonthlyReportPanel.svelte` triggers generation, streams progress, downloads PDF
- [x] Panel appears in `/portfolios/[profile]` Reports tab alongside Fact Sheet + Long-Form
- [x] SSE connection uses `fetch()` + `ReadableStream` with auth headers (not EventSource)
- [x] AbortController used for cleanup on unmount and new generation
- [x] Error state shows retry button
- [x] 429 response shows human-friendly message
- [x] Semaphore (max 2) respected — backend returns 429 on overflow

---

## Phase 2 — Macro Review PDF + Content SSE (P2)

**Goal:** Macro committee reviews get PDF distribution; content generation gets real-time progress.

### 2.1 Macro Committee PDF — Reuse `content_report.py`

Instead of creating a new template from scratch, reuse the existing `render_content_report()` function from `backend/vertical_engines/wealth/pdf/templates/content_report.py:372-401`. This function accepts markdown content and renders it as a styled PDF with Playfair Display headings, Inter body text, Tufte tables, and pull quotes.

**New file:** `backend/vertical_engines/wealth/pdf/macro_pdf.py`

```python
"""Macro Committee Review → PDF via content_report template."""
from __future__ import annotations

from datetime import date
from typing import Any

from vertical_engines.wealth.pdf.templates.content_report import render_content_report
from vertical_engines.wealth.pdf.html_renderer import html_to_pdf

def _report_json_to_markdown(report_json: dict[str, Any], language: str = "pt") -> str:
    """Convert MacroReview.report_json into readable markdown."""
    lines: list[str] = []

    # Regime section
    regime = report_json.get("regime")
    if regime:
        lines.append("# Regime Assessment")
        lines.append(f"**Global Regime:** {regime.get('global', '—')}")
        regional = regime.get("regional", {})
        if regional:
            lines.append("\n## Regional Regimes\n")
            for region, regime_val in regional.items():
                lines.append(f"- **{region}:** {regime_val}")
        reasons = regime.get("composition_reasons", {})
        if reasons:
            lines.append("\n## Composition Rationale\n")
            for key, val in reasons.items():
                lines.append(f"> {val}")

    # Score deltas
    deltas = report_json.get("score_deltas", [])
    if deltas:
        lines.append("\n# Regional Score Changes\n")
        lines.append("| Region | Previous | Current | Delta | Flagged |")
        lines.append("| --- | --- | --- | --- | --- |")
        for d in deltas:
            flag = "⚠" if d.get("flagged") else ""
            lines.append(
                f"| {d['region']} | {d['previous_score']:.1f} "
                f"| {d['current_score']:.1f} | {d['delta']:+.1f} | {flag} |"
            )

    # Global indicators
    gi = report_json.get("global_indicators_delta", {})
    if gi:
        lines.append("\n# Global Indicators\n")
        for key, val in gi.items():
            label = key.replace("_", " ").title()
            lines.append(f"- **{label}:** {val:+.2f}" if isinstance(val, (int, float)) else f"- **{label}:** {val}")

    # Staleness alerts
    alerts = report_json.get("staleness_alerts", [])
    if alerts:
        lines.append(f"\n# Data Quality Alerts\n")
        lines.append(f"{len(alerts)} series with stale data: {', '.join(alerts[:10])}")

    return "\n".join(lines)


async def generate_macro_review_pdf(
    report_json: dict[str, Any],
    *,
    as_of_date: date,
    language: str = "pt",
) -> bytes:
    md = _report_json_to_markdown(report_json, language)
    html = render_content_report(
        md,
        title="Macro Committee Review",
        subtitle=as_of_date.isoformat(),
        language=language,
    )
    return await html_to_pdf(html, format="A4", print_background=True, margin_mm=0)
```

#### Research Insights

**Why reuse `content_report.py`:** The template already handles markdown-to-HTML conversion (`_md_to_html()` at lines 86-206), Tufte table styling, pull quotes, bilingual date formatting, and the navy/copper header design. Building a separate macro template would duplicate ~300 lines of CSS/HTML for minimal visual difference.

**`render_content_report()` signature** (from `content_report.py:372-401`):
```python
def render_content_report(
    content_md: str,
    *,
    title: str,
    subtitle: str = "",
    language: Language = "en",
    scoring_components: dict[str, float] | None = None,  # Optional radar chart
) -> str:
```

**`_md_to_html()` handles tables** — Tufte-style `| cell |` rows → `<table class="tt">` with clean thead/tbody, no borders, alternating background. This directly supports the score deltas table in the macro report.

**`html_to_pdf()` from `html_renderer.py`** — Playwright Chromium with `--no-sandbox`, `wait_until="domcontentloaded"`, `print_background=True` for dark headers. Returns raw `bytes`.

### 2.2 Macro PDF Download Endpoint

**File:** `backend/app/domains/wealth/routes/macro.py`

Add endpoint:

```python
@router.get(
    "/reviews/{review_id}/download",
    summary="Download macro committee review as PDF",
)
async def download_macro_review(
    review_id: uuid.UUID,
    language: str = Query(default="pt"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> Response:
    _require_ic_role(actor)
    result = await db.execute(
        select(MacroReview).where(MacroReview.id == review_id),
    )
    review = result.scalar_one_or_none()
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.status not in ("approved", "pending"):
        raise HTTPException(status_code=400, detail="Review must be approved or pending")

    from vertical_engines.wealth.pdf.macro_pdf import generate_macro_review_pdf
    pdf_bytes = await generate_macro_review_pdf(
        review.report_json,
        as_of_date=review.as_of_date,
        language=language,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="macro-review-{review.as_of_date}.pdf"',
        },
    )
```

#### Research Insights

**Status gate:** Allow download for both `"approved"` and `"pending"` reviews. IC members need to preview the PDF before approving — unlike content reports which only allow download after approval.

**Import placement:** Lazy import of `generate_macro_review_pdf` inside the endpoint function to avoid importing Playwright at module load time (Playwright launch is heavy).

### 2.3 Frontend: Download button in CommitteeReviews

**File:** `frontends/wealth/src/lib/components/macro/CommitteeReviews.svelte`

Add a "Download PDF" button to each review card (lines ~380-389, in the actions area). Uses `api.getBlob(`/macro/reviews/${id}/download`)` pattern. Available for both `"pending"` and `"approved"` reviews.

```svelte
{#if review.status === "approved" || review.status === "pending"}
  <Button size="sm" variant="outline"
    onclick={() => downloadReviewPdf(review.id, review.as_of_date)}
    disabled={downloadingId === review.id}>
    {downloadingId === review.id ? "Downloading…" : "Download PDF"}
  </Button>
{/if}
```

### 2.4 Content Generation SSE

Replace the 5-second polling with SSE streaming for content generation.

**Backend changes** (`backend/app/domains/wealth/routes/content.py`):

1. Modify `POST /content/{type}` triggers to return `job_id` alongside content summary:
   - `job_id = str(uuid.uuid4())`
   - `await register_job_owner(job_id, str(org_id))`
   - Return: `{"id": str(content.id), "job_id": job_id, ...ContentSummary fields}`

2. Add SSE stream endpoint:
   ```python
   @router.get("/{content_id}/stream/{job_id}")
   async def stream_content_generation(
       content_id: uuid.UUID,
       job_id: str,
       request: Request,
       db: AsyncSession = Depends(get_db_with_rls),
       user: CurrentUser = Depends(get_current_user),
       org_id: uuid.UUID | None = Depends(get_org_id),
   ) -> EventSourceResponse:
       _require_feature()
       if not await verify_job_owner(job_id, str(org_id)):
           raise HTTPException(403, "Not authorized for this job")
       return await create_job_stream(request, job_id)
   ```

3. Modify `_run_content_generation()` background tasks to publish events:
   - `await publish_event(job_id, "started", {"content_type": content_type})`
   - `await publish_terminal_event(job_id, "done", {"status": "review", "content_id": str(content.id)})`
   - `await publish_terminal_event(job_id, "error", {"error": str(e)})`

**Frontend changes** (`content/+page.svelte`):

1. Update `POST` response handling to capture `job_id` from generation response
2. Replace `setInterval(invalidateAll, 5000)` polling with manual `fetch()` + `ReadableStream` SSE (same pattern as `LongFormReportPanel.svelte`)
3. On terminal event (`done` or `error`), call `invalidateAll()` to refresh the list
4. **Preserve polling as fallback** — if SSE stream fails to connect (e.g. proxy issues), fall back to current 5s polling

#### Research Insights

**Backend job tracking** reuses existing infrastructure (`core/jobs/tracker.py`):
- `register_job_owner(job_id, org_id, ttl=3600)` → Redis SET with TTL
- `publish_event(job_id, event_type, data)` → Redis PUBLISH on `job:{job_id}:events`
- `publish_terminal_event(job_id, event_type, data, grace_ttl=120)` → PUBLISH + schedule cleanup
- `create_job_stream(request, job_id)` → `EventSourceResponse` with 15s heartbeat

**SSE connection limit:** `createSSEStream` enforces max 4 concurrent SSE connections per tab. Content page should disconnect SSE when user navigates away — use `onDestroy` with `abortController.abort()`. Content generation is typically fast (30-90s), so connections are short-lived.

**Polling fallback is critical** — enterprise networks often have HTTP proxies that buffer SSE streams. The fallback ensures content status always updates even if SSE is blocked. Implementation: start SSE, set a 10s timer; if no event received, fall back to polling.

### 2.5 Acceptance Criteria

- [x] `GET /macro/reviews/{id}/download` returns PDF for approved/pending reviews
- [x] Macro committee PDF renders regional scores, regime, narrative via `content_report.py` template
- [x] CommitteeReviews.svelte shows "Download PDF" button on approved/pending reviews
- [ ] Content generation publishes SSE events (started, done, error) via Redis pub/sub
- [ ] Frontend uses manual `fetch()` + `ReadableStream` SSE for content generation
- [ ] Polling fallback preserved — falls back to 5s polling if SSE fails to connect within 10s
- [ ] SSE connection cleaned up on navigation away (AbortController + onDestroy)

---

## Phase 3 — Document Preview + Content Search (P3)

**Goal:** Documents page shows file preview; content page gets search/filter.

### 3.1 Document File Preview

**File:** `frontends/wealth/src/routes/(app)/documents/[documentId]/+page.svelte`

Add a preview section below the metadata panel:
- For PDFs: use the `PdfPreview.svelte` component from P0.6
- For images: `<img>` tag
- For text/JSON: `<pre>` block

**Backend:** Use the existing `StorageClient.generate_read_url()` method — it already exists in both `LocalStorageClient` (returns `file://` URI) and `R2StorageClient` (returns presigned S3 URL with configurable TTL).

**File:** `backend/app/domains/wealth/routes/documents.py`

```python
@router.get("/wealth/documents/{document_id}/preview-url")
async def get_document_preview_url(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    # Fetch document + latest version
    result = await db.execute(
        select(WealthDocument).where(WealthDocument.id == document_id),
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Get latest version's blob path
    version = await _get_latest_version(db, document_id)
    if not version or not version.blob_path:
        raise HTTPException(status_code=404, detail="No file available")

    storage = create_storage_client()
    url = storage.generate_read_url(version.blob_path, expires_in=300)  # 5 min TTL
    return {"url": url, "content_type": doc.content_type, "filename": doc.filename}
```

#### Research Insights

**`StorageClient.generate_read_url()` API** (from `storage_client.py:96-97`):
```python
# Abstract method — both Local and R2 implement it
def generate_read_url(self, path: str, *, expires_in: int = 3600) -> str: ...
```

**LocalStorageClient** (dev) returns `file://` URI — works in `<object>` tag for local dev.
**R2StorageClient** (prod) returns presigned S3 URL via `boto3.generate_presigned_url("get_object", ...)` — works in `<object>` tag cross-origin.

**Short TTL (300s = 5 min):** Presigned URLs should expire quickly to limit exposure. Frontend fetches a fresh URL each time the preview is opened.

**Security:** The `<object>` tag with a presigned URL does NOT leak auth tokens — the URL itself contains the authorization (S3 query string signature). The RLS check happens at the `get_document_preview_url` endpoint level.

### 3.2 Content Search and Filter

**File:** `frontends/wealth/src/routes/(app)/content/+page.svelte`

Add to the existing tab bar area:
- **Text search:** Filter cards by title (client-side, since content list is typically small)
- **Date range filter:** Created after / before date pickers
- **Sort:** Most recent first (default), oldest first, alphabetical

These are client-side filters on the already-loaded `content` array — no backend changes needed unless the list grows beyond ~500 items.

#### Research Insights

**Client-side filtering is sufficient:** Content generation is IC-team-driven, not automated. Typical volume: 2-5 items/week per org. Even after a year, ~250 items easily fits in a single page load. If volume exceeds ~500, add `limit`/`offset` to `GET /content` and move filtering server-side.

**Search UX:** Use a simple `<input>` with `$derived` filter — matches the pattern used in `dd-reports/+page.svelte` for report search:
```typescript
let searchQuery = $state("");
let filtered = $derived.by(() => {
  let items = activeTab === "all" ? content : content.filter(c => c.content_type === activeTab);
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    items = items.filter(c => (c.title ?? "").toLowerCase().includes(q));
  }
  return items;
});
```

### 3.3 Acceptance Criteria

- [ ] Document detail page shows file preview for PDFs and images
- [ ] Preview uses presigned URL from `StorageClient.generate_read_url()` (5 min TTL)
- [ ] Preview works in both dev (LocalStorage file:// URI) and prod (R2 presigned S3 URL)
- [ ] Content page has search input filtering by title
- [ ] Content page has date range filter
- [ ] Sorting options: newest, oldest, alphabetical

---

## Out of Scope

- **Content editing** — content is AI-generated, not user-editable (approval workflow handles quality)
- **PDF template redesign** — 37 layout issues documented in `docs/prompts/wealth-pdf-layout-redesign.md` are tracked separately
- **Playwright migration of ReportLab content PDFs** — tracked in `docs/prompts/sprint-pdf-playwright-migration-wave2.md`
- **AI Agent drawer integration** — content preview could feed into Fund Copilot, but that's a separate feature
- **Content versioning** — each generation creates a new row; no in-place version history needed now
- **Full markdown library** (marked, remark) — regex-based renderer + DOMPurify is sufficient for the limited markdown subset LLMs produce

## Technical Considerations

### Architecture

- **Shared `renderMarkdown()`** eliminates the current code duplication between DD report viewer and the new content viewer. Future pages (long-form chapter viewer, macro review reader) can import the same utility. DOMPurify adds defense-in-depth at the render boundary.
- **`PdfPreview.svelte`** uses browser-native PDF rendering via `<object>` tag — zero additional dependencies. Falls back gracefully to a download link if the browser doesn't support inline PDF (Safari iOS).
- **SSE for content generation** reuses the existing `core/jobs/tracker.py` + `core/jobs/sse.py` infrastructure — same `register_job_owner` / `publish_event` / `create_job_stream` pattern used by DD Reports, Long-Form, and Monthly Reports.
- **Macro PDF reuses `content_report.py`** — converts `report_json` to markdown, passes to existing template. No new CSS/HTML template needed.

### Performance

- Content detail page loads a single item (`GET /content/{id}`) — negligible backend cost.
- PDF preview fetches the blob once and caches as `URL.createObjectURL()` — no repeated downloads.
- SSE replaces 5s polling — reduces backend load from ~12 req/min to 1 persistent connection per generating item.
- Macro PDF generation uses Playwright — first call incurs ~2s browser launch, subsequent calls reuse the browser process.

### Security

- **Backend nh3 sanitization** at persist boundary in all 5 engines (`investment_outlook.py`, `flash_report.py`, `manager_spotlight.py`, `dd_report/chapters.py`, `critic/parser.py`) — strips `<script>`, `<style>`, `<iframe>`, `<object>`, `<embed>`, `<form>` tags.
- **Frontend DOMPurify sanitization** in `renderMarkdown()` — defense-in-depth layer with matching allowlist.
- `GET /content/{id}` is RLS-scoped — tenant isolation enforced by `get_db_with_rls`.
- PDF preview blob URL is ephemeral (revoked on component destroy) — no persistent shareable link.
- Document preview URL uses presigned URL with short TTL (5 min) — no auth token in URL.
- Macro PDF download is IC-role-gated (same as review generation).

## System-Wide Impact

### Interaction Graph

- `GET /content/{id}` → RLS session → `WealthContent` query → `ContentRead` serialization. No side effects.
- Content SSE: `POST /content/outlooks` → `register_job_owner` → Redis SET → `asyncio.create_task` → `_run_outlook()` → `publish_event` → Redis PUBLISH → SSE subscriber. Same chain as DD Reports.
- Macro PDF: `GET /macro/reviews/{id}/download` → `generate_macro_review_pdf()` → `render_content_report()` (HTML) → `html_to_pdf()` (Playwright) → PDF bytes. Same chain as fact sheet generation.

### Error Propagation

- Content detail 404 → SvelteKit `throw error(404)` → error page (standard pattern).
- SSE connection failure → frontend falls back to polling (preserve existing `setInterval` as backup).
- Macro PDF Playwright failure → return 500 with structlog error. No ReportLab fallback for macro — but `render_content_report()` is well-tested across 3 content types already.
- Document preview presigned URL expired → frontend shows "Preview expired, click to refresh" and re-fetches URL.

### State Lifecycle Risks

- **Content SSE job registration:** If background task crashes before publishing terminal event, job stays in Redis until TTL expires (1h). Frontend SSE will timeout at 45s heartbeat and fall back to polling. No orphaned state in DB — content row already exists with `status="draft"`.
- **PDF preview blob URLs:** Revoked on component `onDestroy`. If user navigates away without destroy, browser GC handles it.
- **Presigned URL for document preview:** Expires after 5 min. If user stays on page longer, preview will stop loading. Add a "Refresh" button that re-fetches the URL.

### API Surface Parity

- `GET /content/{id}` mirrors `GET /dd-reports/{id}` — both return full entity with body content.
- `GET /content/{id}/stream/{job_id}` mirrors `GET /dd-reports/{id}/stream` — same SSE pattern.
- `GET /macro/reviews/{id}/download` mirrors `GET /content/{id}/download` — same PDF blob response.
- `GET /wealth/documents/{id}/preview-url` — new pattern (presigned URL), but follows `StorageClient` abstraction.

### Integration Test Scenarios

1. **Generate → Preview → Approve:** Trigger outlook, wait for SSE "done", navigate to `/content/[id]`, read markdown, approve. Verify `content_md` renders correctly and status transitions to "approved".
2. **PDF Preview after approval:** Approve content, click "Preview PDF", verify `<object>` tag loads blob. Click "Download", verify file downloads.
3. **Monthly Report E2E:** Navigate to `/portfolios/[profile]`, click "Generate Monthly Report", verify SSE progress, download PDF.
4. **Macro PDF Download:** Generate macro review, approve, click "Download PDF", verify PDF contains regime + scores table.
5. **SSE failure fallback:** Block SSE endpoint, trigger content generation, verify polling kicks in after 10s timeout.
6. **DOMPurify sanitization:** Inject `<script>alert(1)</script>` into content_md (bypassing backend), verify `renderMarkdown()` strips it.
7. **Document preview presigned URL:** Open document detail, verify PDF loads in `<object>` tag. Wait 6 min, verify preview shows "expired" state with refresh button.

## File Change Map

### New Files

| File | Purpose |
|------|---------|
| `frontends/wealth/src/routes/(app)/content/[id]/+page.server.ts` | Content detail data loader |
| `frontends/wealth/src/routes/(app)/content/[id]/+page.svelte` | Content detail view with markdown reader |
| `frontends/wealth/src/lib/utils/render-markdown.ts` | Shared markdown → HTML renderer with DOMPurify |
| `frontends/wealth/src/lib/utils/render-markdown.css` | Shared `.rw-*` styles for rendered markdown |
| `frontends/wealth/src/lib/components/PdfPreview.svelte` | Inline PDF preview via `<object>` tag |
| `frontends/wealth/src/lib/components/MonthlyReportPanel.svelte` | Monthly report SSE generation panel |
| `backend/vertical_engines/wealth/pdf/macro_pdf.py` | Macro review → markdown → PDF via content_report template |

### Modified Files

| File | Change |
|------|--------|
| `backend/app/domains/wealth/routes/content.py` | Add `GET /{id}`, SSE stream endpoint, job tracking in background tasks |
| `backend/app/domains/wealth/routes/macro.py` | Add `GET /reviews/{id}/download` PDF endpoint |
| `frontends/wealth/src/routes/(app)/content/+page.svelte` | Make cards clickable, replace polling with SSE + fallback |
| `frontends/wealth/src/routes/(app)/dd-reports/[fundId]/[reportId]/+page.svelte` | Import shared `renderMarkdown` + `flattenObject`, add PDF preview button |
| `frontends/wealth/src/routes/(app)/portfolios/[profile]/+page.svelte` | Add MonthlyReportPanel in Reports tab |
| `frontends/wealth/src/lib/components/macro/CommitteeReviews.svelte` | Add "Download PDF" button on approved/pending reviews |
| `frontends/wealth/src/lib/types/content.ts` | Add `ContentFull` interface |
| `frontends/wealth/src/routes/(app)/documents/[documentId]/+page.svelte` | Add file preview section (P3) |
| `backend/app/domains/wealth/routes/documents.py` | Add `GET /{id}/preview-url` endpoint using `StorageClient.generate_read_url()` (P3) |

## Dependencies

- **P0 has no external dependencies** — uses existing patterns, DOMPurify already installed
- **P1 depends on P0** only for the shared `renderMarkdown` utility (optional — can copy inline if P0 not yet merged)
- **P2.1-2.3 (Macro PDF)** are independent of P0/P1
- **P2.4 (Content SSE)** depends on P0.1 (GET endpoint) being available
- **P3.1 (Document preview)** depends on P0.6 (`PdfPreview.svelte` component)
- **P3.2 (Content search)** is independent

## Sources & References

### Internal References

- DD Report markdown renderer: `frontends/wealth/src/routes/(app)/dd-reports/[fundId]/[reportId]/+page.svelte:208-221`
- DD Report `.rw-*` styles: same file, lines 676-729
- DD Report `flattenObject()`: same file, lines 225-236
- DD Report approval flow: same file, lines 49-80
- LongFormReportPanel SSE pattern: `frontends/wealth/src/lib/components/LongFormReportPanel.svelte:94-170`
- SSE client utility: `packages/investintell-ui/src/lib/utils/sse-client.svelte.ts`
- ContentRead schema: `backend/app/domains/wealth/schemas/content.py:27-29`
- Monthly report routes: `backend/app/domains/wealth/routes/monthly_report.py`
- Job tracker: `backend/app/core/jobs/tracker.py`
- SSE stream factory: `backend/app/core/jobs/sse.py`
- PDF HTML renderer: `backend/vertical_engines/wealth/pdf/html_renderer.py`
- Content PDF template: `backend/vertical_engines/wealth/pdf/templates/content_report.py:372-401`
- StorageClient presigned URLs: `backend/app/services/storage_client.py:96-97`
- nh3 sanitization: `backend/ai_engine/governance/output_safety.py`

### Learnings Applied

- LLM output sanitization (nh3 persist boundary): `docs/solutions/security-issues/llm-output-sanitization-nh3-persist-boundary-PipelineStorage-20260315.md`
- Frontend wiring patterns: `docs/solutions/architecture-patterns/endpoint-coverage-multi-agent-review-frontend-wiring-20260317.md`
- Phantom calls / missing UI: `docs/solutions/integration-issues/phantom-calls-missing-ui-wealth-frontend-20260319.md`
- Design decisions (tokens, discriminated unions): `docs/solutions/design-decisions/2026-03-17-wealth-frontend-review-decisions.md`
- CI typecheck: `docs/solutions/build-errors/ci-frontend-typecheck-failures-CIFrontendPipeline-20260323.md`

### Related Documentation

- PDF layout issues: `docs/prompts/wealth-pdf-layout-redesign.md` (37 issues tracked separately)
- Playwright migration: `docs/prompts/sprint-pdf-playwright-migration-wave2.md`
- Wealth frontend design decisions: `docs/solutions/design-decisions/2026-03-17-wealth-frontend-review-decisions.md`
