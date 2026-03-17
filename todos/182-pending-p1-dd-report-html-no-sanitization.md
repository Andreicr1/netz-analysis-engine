---
status: complete
priority: p1
issue_id: "182"
tags: [code-review, security, wealth, xss]
dependencies: []
---

# DD Report viewer renders @html without DOMPurify

## Problem Statement

The wealth DD report detail page (`frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte`) renders LLM-generated chapter content using `{@html}` with only a regex-based sanitizer. Regex HTML sanitization is fundamentally bypassable via mutation XSS (mXSS), encoding tricks, and SVG/MathML namespace escapes.

This is distinct from todo #080 (ICMemoViewer — fixed) and #171 (PromptEditor — pending). The DD report viewer is a separate rendering path for wealth-vertical content.

## Findings

- `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte:14-34` — hand-rolled `sanitizeHtml()` or `renderSafeMarkdown()` regex
- Regex patterns strip `<script>`, `on*` handlers, `javascript:` URIs
- Known bypasses: `<svg><style><a title="</style><img src=x onerror=alert(1)>">`, encoding tricks (`&#106;avascript:`), multi-line attribute edge cases
- Content originates from LLM generation (OpenAI) stored in database — attack vector via manipulated input documents

## Proposed Solutions

### Option 1: Replace regex with DOMPurify

**Approach:** Install `dompurify` + `@types/dompurify`, replace regex sanitizer with `DOMPurify.sanitize(html)`.

**Pros:**
- Industry-standard, handles all known bypass vectors including mXSS
- Drop-in replacement — same input/output signature
- Actively maintained by the Cure53 security team

**Cons:**
- Adds ~15KB to client bundle
- Requires SSR guard (`if (typeof window !== 'undefined')`)

**Effort:** 1 hour

**Risk:** Low

### Option 2: Use marked + DOMPurify pipeline

**Approach:** If content is Markdown, render via `marked` then sanitize with DOMPurify.

**Pros:**
- Safer than raw HTML rendering
- Markdown is the natural format for LLM output

**Cons:**
- Requires verifying that DD report content is Markdown, not raw HTML

**Effort:** 2 hours

**Risk:** Low

## Recommended Action

## Technical Details

**Affected files:**
- `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte`

**Related todos:**
- #080 (complete) — ICMemoViewer @html fixed
- #171 (pending) — PromptEditor @html

## Acceptance Criteria

- [ ] DOMPurify installed and used for DD report chapter rendering
- [ ] No regex-based HTML sanitization remains
- [ ] SSR-safe (browser-only guard)
- [ ] All DD report chapters render correctly after sanitization

## Work Log

### 2026-03-17 - Initial Discovery

**By:** Claude Code (codex review — security-sentinel agent)

**Actions:**
- Identified regex sanitizer in DD report viewer
- Cross-referenced with existing XSS todos (#080, #171)
- Confirmed this is a distinct rendering path not covered by prior fixes
