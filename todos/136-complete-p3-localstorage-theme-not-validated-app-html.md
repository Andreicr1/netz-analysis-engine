---
status: complete
priority: p3
issue_id: 136
tags: [code-review, security, defense-in-depth]
---

# Problem Statement

The inline script in `app.html` reads the `netz-theme` value from `localStorage` and passes it directly to `document.documentElement.setAttribute` without validating against a known-good allowlist. While `setAttribute` is safe against script injection (it sets an attribute value, not innerHTML), the absence of validation is inconsistent with the defense-in-depth approach applied to the server-side cookie handling (issue #129).

# Findings

- `frontends/wealth/src/app.html` lines 9-13 contain an inline `<script>` that reads `localStorage.getItem('netz-theme')` and calls `document.documentElement.setAttribute('data-theme', theme)`.
- No allowlist check is applied before the `setAttribute` call.
- `setAttribute` on a safe property like `data-theme` does not enable script execution, so this is not a direct XSS vector.
- However, an unexpected value (e.g., `"><img src=x onerror=...>`) set in localStorage could produce unexpected attribute values visible in the DOM, potentially triggering CSS-based attacks or breaking theme application silently.
- The server-side cookie (issue #129) and the client-side localStorage should apply the same validation logic for consistency.

# Proposed Solutions

Add a one-line allowlist check in the inline script:

```javascript
let theme = localStorage.getItem('netz-theme') || 'dark';
if (theme !== 'light' && theme !== 'dark') theme = 'dark';
document.documentElement.setAttribute('data-theme', theme);
```

This is a two-line change that brings `app.html` in line with the validation applied in `hooks.server.ts` (once #129 is resolved) and eliminates the possibility of unexpected attribute values.

# Technical Details

- **File:** `frontends/wealth/src/app.html` lines 9-13
- **Risk level:** Low (setAttribute is not an injection sink for scripts)
- **Rationale for fixing:** Consistency with server-side validation (#129) and defense-in-depth
- **Related issue:** #129 (theme cookie injection in hooks.server.ts)
- **Source:** security-sentinel
