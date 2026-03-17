---
status: complete
priority: p1
issue_id: "080"
tags: [code-review, security, xss, frontend]
dependencies: []
---

# XSS via {@html chapter.content} in ICMemoViewer

## Problem Statement

`ICMemoViewer.svelte:105` renders IC memo chapter content using `{@html chapter.content}`, which interprets raw HTML without any sanitization. IC memo content originates from LLM generation (OpenAI) and is stored in the database. If an attacker manipulates input documents to inject HTML/JS into LLM output, or if a compromised/malicious LLM response contains script tags, this becomes a stored XSS vulnerability in the context of the authenticated user's session.

This is the **only** `{@html}` usage across all frontends that renders user/LLM-generated content (the other two are `<style>` blocks for branding CSS variables).

## Findings

- `frontends/credit/src/lib/components/ICMemoViewer.svelte:105` — `{@html chapter.content}` renders LLM-generated HTML
- Chapter content flows: LLM generation → PostgreSQL → API response → Svelte `{@html}`
- No DOMPurify or equivalent sanitization anywhere in the pipeline
- LLM outputs can be manipulated via prompt injection in source documents
- Impact: session hijacking, data exfiltration, privilege escalation within the tenant

## Proposed Solutions

### Option 1: Sanitize with DOMPurify before rendering

**Approach:** Add DOMPurify to `@netz/ui`, create a `sanitizeHtml()` utility, use it in ICMemoViewer before `{@html}`.

**Pros:**
- Preserves HTML formatting (headers, lists, tables) that memos need
- Industry-standard library, well-tested
- Can whitelist specific tags/attributes

**Cons:**
- Adds ~15KB dependency
- Must be applied consistently everywhere `{@html}` is used

**Effort:** 1-2 hours

**Risk:** Low

---

### Option 2: Render as Markdown instead of HTML

**Approach:** Store memo chapters as Markdown, render client-side with a Markdown renderer (e.g., `marked` + DOMPurify, or `svelte-markdown`).

**Pros:**
- Markdown is inherently safer (limited attack surface)
- Better content portability
- Consistent rendering

**Cons:**
- Requires backend changes to emit Markdown instead of HTML
- More migration work if existing data is HTML

**Effort:** 4-6 hours

**Risk:** Medium

---

### Option 3: Server-side sanitization in the API response

**Approach:** Sanitize HTML on the backend (e.g., `bleach` or `nh3` for Python) before sending to frontend.

**Pros:**
- Defense in depth — content is safe regardless of frontend
- Single sanitization point

**Cons:**
- Adds Python dependency
- Still need frontend sanitization for defense-in-depth

**Effort:** 2-3 hours

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `frontends/credit/src/lib/components/ICMemoViewer.svelte:105`

**Related components:**
- IC memo generation pipeline (vertical_engines/credit/memo/)
- Backend memo API endpoints

## Acceptance Criteria

- [ ] All `{@html}` usages rendering user/LLM content use sanitization
- [ ] DOMPurify or equivalent integrated into @netz/ui
- [ ] XSS test case: `<script>alert(1)</script>` in chapter content is stripped
- [ ] Existing memo formatting (headers, lists, tables) still renders correctly

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Claude Code (ce:review PRs #37-#45)

**Actions:**
- Identified `{@html chapter.content}` in ICMemoViewer.svelte:105
- Grep confirmed 3 total `{@html}` usages across all frontends
- Verified no sanitization exists in the pipeline
- Classified as P1 — stored XSS with authenticated context

## Resources

- **PRs:** #37-#45 (Frontend Platform)
- **OWASP:** XSS Prevention Cheat Sheet
- **DOMPurify:** https://github.com/cure53/DOMPurify
