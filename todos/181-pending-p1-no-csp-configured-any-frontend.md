---
status: complete
priority: p1
issue_id: "181"
tags: [code-review, security, frontend]
dependencies: []
---

# No Content Security Policy (CSP) configured on any frontend

## Problem Statement

None of the three SvelteKit frontends (credit, wealth, admin) include a Content Security Policy. SvelteKit supports CSP natively via `kit.csp` in `svelte.config.js`. Without CSP, any XSS vulnerability has no defense-in-depth mitigation — a successful XSS payload has unrestricted access to script execution, inline scripts, and network requests.

## Findings

- `frontends/credit/svelte.config.js` — no `kit.csp` configuration
- `frontends/wealth/svelte.config.js` — no `kit.csp` configuration
- `frontends/admin/svelte.config.js` — no `kit.csp` configuration
- Combined with existing XSS vectors (todo #171 PromptEditor, DD report @html), this means there is zero browser-enforced restriction on script execution sources

## Proposed Solutions

### Option 1: Add CSP to all three svelte.config.js

**Approach:** Configure `kit.csp.directives` with restrictive defaults.

```javascript
kit: {
  csp: {
    directives: {
      'default-src': ['self'],
      'script-src': ['self'],
      'style-src': ['self', 'unsafe-inline'], // Tailwind inline styles
      'img-src': ['self', 'data:', 'blob:', 'https:'],
      'connect-src': ['self', 'https://api.clerk.com', 'wss:'],
      'frame-ancestors': ['none'],
    }
  }
}
```

**Pros:**
- Defense-in-depth against XSS
- Prevents framing attacks
- SvelteKit handles nonce generation automatically

**Cons:**
- `unsafe-inline` needed for Tailwind/ECharts inline styles
- May require testing with Clerk SDK

**Effort:** 2-3 hours (including testing)

**Risk:** Low — CSP is additive, can start with report-only mode

## Recommended Action

## Technical Details

**Affected files:**
- `frontends/credit/svelte.config.js`
- `frontends/wealth/svelte.config.js`
- `frontends/admin/svelte.config.js`

## Acceptance Criteria

- [ ] CSP configured in all three svelte.config.js
- [ ] All pages render correctly with CSP active
- [ ] Clerk auth flow works with CSP
- [ ] ECharts renders correctly (canvas, no inline scripts)
- [ ] SSE connections work within connect-src

## Work Log

### 2026-03-17 - Initial Discovery

**By:** Claude Code (codex review)

**Actions:**
- Identified missing CSP across all three frontends
- Cross-referenced with existing XSS findings (#171)
- Drafted CSP directive recommendations

## Notes

- Start with `Content-Security-Policy-Report-Only` header to identify violations before enforcement
- ECharts uses canvas renderer (no inline scripts), so script-src: 'self' should suffice
