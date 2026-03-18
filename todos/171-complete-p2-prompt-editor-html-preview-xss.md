---
id: 171
status: complete
priority: p2
tags: [code-review, security, admin]
created: 2026-03-17
---

# Admin PromptEditor {@html preview} — XSS risk

## Problem Statement

The admin PromptEditor component renders a preview using Svelte's `{@html}` directive without sanitization. While the admin panel is restricted to super admins, a multi-admin scenario allows one admin to craft a malicious Jinja2 template that executes JavaScript in another admin's browser session.

## Findings

- **File:** `frontends/admin/src/lib/components/PromptEditor.svelte` line 276
  - Uses `{@html preview}` to render the prompt template preview
  - The `preview` value comes from rendering the Jinja2 template

- **Mitigating factors:**
  - Admin panel is gated behind `require_super_admin` middleware
  - Backend uses `jinja2.SandboxedEnvironment` for template rendering
  - Attack surface is limited to admin-to-admin scenarios

- **Risk scenario:**
  - Admin A saves a prompt template containing `<script>` or event handler attributes
  - Admin B opens the prompt editor and the preview renders the malicious HTML
  - Admin B's session token or actions could be hijacked

## Proposed Solutions

**Option A — Client-side sanitization:**
- Install `DOMPurify` and sanitize the preview before passing it to `{@html}`
- `{@html DOMPurify.sanitize(preview)}`

**Option B — Backend sanitization:**
- Have the preview API endpoint return already-sanitized HTML
- Ensures even direct API consumers are protected

## Acceptance Criteria

- [ ] `{@html preview}` input is sanitized before rendering
- [ ] `<script>` tags and event handler attributes are stripped from preview output
- [ ] Legitimate Jinja2 template previews still render correctly (tables, formatting, etc.)
- [ ] No raw unsanitized HTML is rendered via `{@html}` anywhere in the admin frontend
