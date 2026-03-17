# Admin Frontend — UX Principles & Component Specifications
# Netz Platform Operations — Implementation Guide

**Audience:** Platform operators, Netz IT team, system administrators.
**Standard:** Operational control panel — think Datadog/PagerDuty level of clarity.
System state must be immediately legible. Degradation surfaces itself. Actions are
deliberate, confirmed, and logged. Never requires guesswork about what is running.

**Last updated:** 2026-03-17

---

## Core Philosophy

### 1. System state is the first thing visible on every load
The operator opens the admin panel to know if everything is running. The health
status of services, workers, and pipelines must be the default view — not a
submenu under "Monitoring".

If any service is degraded, the operator sees it within 3 seconds of opening
the panel. No hunting required.

### 2. Configuration changes are consequential — treat them as such
A misconfigured prompt or a broken JSON override can silently corrupt IC memo
generation for all tenants. Every config change requires:
- Validation before save (never save invalid JSON/YAML)
- Diff view showing exactly what changed from the current state
- Confirmation with description of impact scope (which tenants, which features)
- Immediate audit log entry

Config saves that bypass validation are not permitted.

### 3. Every destructive action is explicit and logged
Delete config override, revert prompt, seed tenant, delete asset — these are
not undoable. The UI must make the consequence clear before execution, not after.

Pattern for all destructive actions:
1. ActionButton triggers ConfirmDialog
2. ConfirmDialog states: what will be deleted/changed + scope of impact
3. User confirms → action executes → Toast with result
4. Audit log entry created immediately (visible in the relevant entity's history)

### 4. Operators are technical — do not simplify away useful information
Unlike the credit and wealth frontends, admin users understand JSON, YAML,
HTTP status codes, worker logs, and error traces. Do not hide technical detail
behind friendly summaries. Show the actual error, the actual config key,
the actual log line.

"Service unavailable" is not acceptable when "Redis connection timeout at
10.0.0.5:6379 — retried 3/3" is available.

### 5. Tenant context is always explicit
The admin panel operates across all tenants. Every action that is tenant-scoped
must display the tenant name and org_id prominently. Operators must never
wonder "which tenant am I looking at?"

When an action affects all tenants (e.g., updating a global config default),
show "Affects: ALL TENANTS" in the confirmation dialog — never let this be implicit.


---

## Global UI Rules

### Color system (strict semantic meaning)
```
--color-health-ok:       #22c55e   /* green  — service healthy */
--color-health-degraded: #f59e0b   /* amber  — partial failure, degraded */
--color-health-down:     #ef4444   /* red    — service down, critical */
--color-health-unknown:  #6b7280   /* gray   — not yet checked / no data */

--color-config-override: #3b82f6   /* blue   — tenant override active */
--color-config-default:  #6b7280   /* gray   — using global default */
--color-config-invalid:  #ef4444   /* red    — invalid config detected */

--color-scope-tenant:    #8b5cf6   /* purple — affects single tenant */
--color-scope-global:    #f97316   /* orange — affects all tenants */

--color-action-safe:     #22c55e
--color-action-warn:     #f59e0b
--color-action-destruct: #ef4444
```

### Typography rules
- Error messages: monospace, full trace — never truncated in the primary display
- Config/prompt content: monospace always — these are code, not prose
- Tenant slugs and org_ids: monospace, always shown alongside display names
- Log lines: monospace, timestamps in ISO 8601
- JSON/YAML editors: syntax highlighting required — no plain textarea

### Interaction rules
- All config editors: validate on change (debounced 500ms), never on blur only
- All destructive actions: ConfirmDialog — no exceptions
- Health page: auto-refresh every 30 seconds — no manual refresh required
- Worker logs: real-time SSE stream — never requires page reload to update
- Tables: sortable columns, filter by tenant where applicable

### Theme
Admin frontend uses light theme (white background). This is intentional:
operators are in office environments, often with multiple monitors. Dark theme
is not the default. Provide dark theme as a user preference but never default to it.

---

## View 1: Health Monitor (`routes/health/+page.svelte`)

This is the default landing page for the admin panel.

### Layout

```
┌─────────────────────────────────────────────────────────┐
│ SYSTEM HEALTH — Last checked: today 14:32:08  [Refresh] │
├───────────────────────┬─────────────────────────────────┤
│  SERVICES (6)         │  WORKERS (4)                    │
├───────────────────────┴─────────────────────────────────┤
│  PIPELINE STATUS (last 24h runs)                        │
├─────────────────────────────────────────────────────────┤
│  WORKER LOG FEED (real-time SSE)                        │
└─────────────────────────────────────────────────────────┘
```

### Services Grid

One card per service. 3-column grid. Auto-refreshes every 30s.

```
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ ● PostgreSQL     │  │ ● Redis          │  │ ⚠ Azure AI Search│
│   OK             │  │   OK             │  │   DEGRADED       │
│   12ms latency   │  │   1.2ms latency  │  │   487ms latency  │
│   Checked 14:32  │  │   Checked 14:32  │  │   ↑ from 120ms   │
└──────────────────┘  └──────────────────┘  └──────────────────┘
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ ● Azure Blob     │  │ ● OpenAI API     │  │ ✗ Twilio         │
│   OK             │  │   OK             │  │   DOWN           │
│   Checked 14:32  │  │   220ms p50      │  │   Connection ref.│
└──────────────────┘  └──────────────────┘  └──────────────────┘
```

- Card border = health color
- Degraded/Down cards: show last known error, not just status
- Click any card → opens service detail with full history (last 24h)
- "Connection ref." = truncated error label — click to expand full error

### Workers Status

```
WORKERS — 4 registered
──────────────────────────────────────────────────────────────────
Worker              Status    Last Heartbeat  Queue Depth  Processed
──────────────────────────────────────────────────────────────────
ingestion-worker-1  ● Running  14:32:01        3 pending    1,247 today
ingestion-worker-2  ● Running  14:31:58        0 pending      891 today
ic-memo-worker-1    ● Running  14:32:00        1 pending      43 today
risk-worker-1       ⚠ Stale   14:28:15        0 pending      12 today
──────────────────────────────────────────────────────────────────
```

"Stale" = heartbeat > 2 minutes ago. Shows exact last heartbeat timestamp.
Click worker row → opens log feed filtered to that worker.

### Worker Log Feed (real-time SSE)

```
WORKER LOGS — Live  ● Connected  [Filter: all workers ▾]  [Clear]
──────────────────────────────────────────────────────────────────
14:32:08.412  ingestion-worker-1  INFO   Processing document doc_abc123
14:32:08.891  ingestion-worker-1  INFO   Chunk 1/8 embedded successfully
14:32:09.112  ic-memo-worker-1    INFO   IC memo generation started — deal_xyz
14:32:09.540  ingestion-worker-1  ERROR  Chunk 4/8: OpenAI timeout (15s)
14:32:09.541  ingestion-worker-1  WARN   Retrying chunk 4/8 (attempt 2/3)
──────────────────────────────────────────────────────────────────
```

- ERROR lines: red background
- WARN lines: amber background
- INFO lines: default
- Full log line shown — never truncated
- Filter by worker, by level (INFO/WARN/ERROR), by time range


---

## View 2: Tenant Management (`routes/tenants/+page.svelte` and `[orgId]/`)

### Tenant List

```
TENANTS — 8 active
──────────────────────────────────────────────────────────────────────────
Tenant          Slug         org_id           Plan      Status   Last Active
──────────────────────────────────────────────────────────────────────────────
Netz Asset      netz-asset   org_abc123...    Enterprise ● Active  today
Previse Capital previse       org_def456...   Pro        ● Active  yesterday
Demo Tenant     demo-01      org_ghi789...    Trial      ● Active  3 days ago
──────────────────────────────────────────────────────────────────────────────
                                                        [+ Create Tenant]
```

- org_id always shown (monospace, truncated with copy-to-clipboard)
- Plan badge colored: Enterprise = purple, Pro = blue, Trial = gray
- "Create Tenant" opens Dialog form — never a new page

### Create Tenant Dialog

Fields: `name`, `slug` (auto-generated from name, editable), `clerk_org_id`,
`plan_tier`. Slug: validated in real-time (alphanumeric + hyphens only, unique).
On success: navigates to new tenant detail page.

### Tenant Detail (`routes/tenants/[orgId]/+page.svelte`)

Header always shows: tenant name + slug + org_id (monospace) + plan + status.

**Tabs: [Overview] [Configuration] [Branding] [Seed & Setup]**

**Tab: Overview**
Edit form for: `name`, `plan_tier`, `status`. ActionButton to save.
Read-only: `org_id`, `clerk_org_id`, `created_at`.

**Tab: Branding**
Asset upload per type (logo, favicon, email header).
- Accepted formats: PNG, JPEG, ICO only — no SVG (XSS risk, enforced)
- Client-side magic byte validation before upload
- Preview rendered immediately with `<img>` tag
- ConfirmDialog for delete: "Delete [asset_type] for [tenant name]?
  This cannot be undone."
- `X-Netz-Request: 1` header sent on all multipart uploads (CSRF defense)

**Tab: Seed & Setup**
```
SEED TENANT — Netz Asset
────────────────────────────────────────────────────────────
This will create default configuration overrides, prompt
templates, and sample data for this tenant.

Scope: tenant netz-asset (org_abc123)
WARNING: Existing overrides will be replaced.

[Seed Tenant Defaults]  ← triggers ConfirmDialog before execution
```

---

## View 3: Configuration Manager (`routes/config/[vertical]/+page.svelte`)

### Config List (per vertical)

```
CREDIT CONFIGURATION — 12 keys   [vertical: credit ▾]
──────────────────────────────────────────────────────────────────────────────
Config Key              Tenant Override?  Status    Last Modified
──────────────────────────────────────────────────────────────────────────────
ic_memo_template        ● 3 overrides     ✓ Valid   2026-03-10 by A. Ferreira
document_review_rules   ● 1 override      ✓ Valid   2026-02-28 by R. Mendes
pipeline_stages         ○ Using default   ✓ Valid   —
risk_limits             ● 2 overrides     ✗ INVALID 2026-03-15  [Fix →]
──────────────────────────────────────────────────────────────────────────────
[View Invalid Configs →]  (shown when count > 0, red badge)
```

"Invalid" configs shown prominently with direct link to the editor.

### Config Editor (`ConfigEditor.svelte`)

Full-width, two-panel layout: editor left, diff right.

```
┌─────────────────────────────────┬────────────────────────────────┐
│ EDITOR                          │ DIFF vs. current               │
│ Tenant: Netz Asset              │                                │
│ Vertical: credit                │ - "max_pages": 50              │
│ Config: ic_memo_template        │ + "max_pages": 75              │
│                                 │                                │
│ {                               │ No other changes               │
│   "max_pages": 75,              │                                │
│   "sections": [...]             │                                │
│ }                               │                                │
│                                 │                                │
│ ✓ Valid JSON                    │                                │
│                                 │                                │
│ [Validate]  [Save]  [Delete]   │                                │
└─────────────────────────────────┴────────────────────────────────┘
```

Rules:
- Validate runs on every keystroke (debounced 500ms) — Save disabled until valid
- Save requires `If-Match` header (optimistic locking — enforced by backend)
- 409 Conflict: Toast "Config modified by another user" + reload editor
- 428 Precondition Required: "Please reload to get current version"
- Delete override: ConfirmDialog "Revert [key] for [tenant] to global default?"
- Update global default: ConfirmDialog "This will affect ALL tenants using the
  default. [N] tenants currently override this key."


---

## View 4: Prompt Manager (`routes/prompts/[vertical]/+page.svelte`)

### Prompt List

```
PROMPTS — credit vertical   [vertical: credit ▾]
──────────────────────────────────────────────────────────────────────────────
Prompt Name              Version  Last Modified        Last Preview
──────────────────────────────────────────────────────────────────────────────
ic_memo_main             v7       2026-03-09 A. Silva  2026-03-09
ic_memo_risk_section     v3       2026-02-20 R. Mendes 2026-02-21
document_classifier      v2       2026-01-15 A. Silva  2026-01-16
deal_summary_extraction  v1       2025-12-01 System    never
──────────────────────────────────────────────────────────────────────────────
```

Click row → opens PromptEditor for that prompt.

### Prompt Editor (`PromptEditor.svelte`)

This is the gold standard mutation component in the project. All other editors
follow its pattern (validate → preview → save → audit).

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ic_memo_main  │  vertical: credit  │  Version: v7  │  [History ▾]        │
├──────────────────────────────────┬───────────────────────────────────────┤
│ EDITOR                           │ PREVIEW OUTPUT                        │
│                                  │ (rendered after [Run Preview])        │
│ You are a senior credit analyst  │                                       │
│ at Netz Asset Management...      │ [Run Preview]                         │
│                                  │                                       │
│ [Validate]  [Run Preview]        │                                       │
│ [Save]      [Revert to v6 ▾]    │                                       │
└──────────────────────────────────┴───────────────────────────────────────┘
```

Rules:
- Validate: checks template syntax (Jinja2 variable references)
- Run Preview: calls `POST /admin/prompts/{vertical}/{name}/preview` — shows
  rendered output with sample data. Required before Save is recommended.
- Save: always creates a new version (immutable history)
- Revert: ConfirmDialog "Revert to version [N]? This will create version [N+1]
  with the content of v[N]." Never destructive of history.

**Version History Panel (lazy-loaded on "History" click)**
```
PROMPT HISTORY — ic_memo_main
──────────────────────────────────────────────────────────────────
Version  Date                Modified by    Change summary
──────────────────────────────────────────────────────────────────
v7       2026-03-09 14:22    A. Silva       "Added DSCR section"
v6       2026-02-15 09:11    R. Mendes      "Restructured risk factors"
v5       2026-01-30 16:45    A. Silva       "Initial risk section"
──────────────────────────────────────────────────────────────────
[Revert to this version] per row
```

---

## Component Anti-Patterns (NEVER DO)

1. **Never hide system errors behind friendly messages.**
   Bad: "Something went wrong. Please try again."
   Good: "Redis ECONNREFUSED 10.0.0.5:6379 — retried 3/3. Last attempt: 14:32:09."

2. **Never save config without validation.**
   The Save button is disabled until the JSON/YAML is valid.
   There is no "save anyway" override.

3. **Never show a config action without specifying scope.**
   Bad: "Delete override"
   Good: "Delete override for tenant netz-asset (org_abc123)"
   For global actions: "Update default — affects ALL tenants"

4. **Never auto-refresh tenant data in a form the operator is editing.**
   If the operator has unsaved changes in a form, do not refresh the page data.
   Show a banner: "Newer data available — [Reload to update] (unsaved changes
   will be lost)"

5. **Never show worker logs truncated.**
   The log line that explains the failure is often at the end of a long trace.
   Show full log lines. Wrap rather than truncate.

6. **Never omit org_id from any tenant-scoped view.**
   Operators often work with multiple tenants. Display name alone is not enough.
   Always show slug and org_id (monospace) alongside the display name.

7. **Never allow SVG uploads for branding assets.**
   PNG, JPEG, ICO only. SVG is an XSS vector in `<img>` tags.
   Enforce at upload time with client-side type check + server-side magic bytes.

8. **Never show health status without a last-checked timestamp.**
   Bad: "PostgreSQL ● OK"
   Good: "PostgreSQL ● OK — checked 14:32:08 (12ms)"
   Stale health data (> 60s) shows amber regardless of last known status.

9. **Never make the prompt editor a modal or side panel.**
   Prompts can be several hundred tokens. They need full-width space.
   The editor always occupies the main content area.

10. **Never default the config editor to read-only.**
    Operators open the config editor to edit. Read-only is the exception.
    Show the form, not a display view that requires clicking "Edit".

### Alert fatigue discipline — amber that is always amber becomes gray

The health monitor's value depends entirely on the operator trusting that amber
means something. If amber fires continuously for low-priority issues, the operator
habituates and stops processing it. Real incidents then surface in the noise.

Rules:
- **Amber (degraded) must be time-bounded.** Any service in degraded state for
  more than 2 hours without acknowledgment escalates to a persistent banner at the
  top of the health page: "Azure AI Search degraded for 2h 14m — [Acknowledge]"
- **Acknowledged alerts are visually suppressed** (gray, not amber) until status
  changes. Suppression requires a reason and expires after 24h.
- **Worker "stale" status** (heartbeat > 2min) immediately shows amber on the
  worker card. If stale > 10min with no recovery, escalates to red.
- **Low-priority warnings** (e.g., high latency but service healthy, queue depth
  growing but within bounds) use a distinct visual weight — smaller badge, no
  border color change — to distinguish from genuine degradation.
- **Never show more than 3 amber/red alerts simultaneously** without grouping.
  If 4+ services are degraded, group into "4 services degraded — [View all]"
  rather than filling the screen with red cards that compete equally.
- The goal: when the operator sees red, they act immediately. This only works if
  red is rare and unambiguous.

---

## Accessibility & Audit Requirements

- All config saves: audit log with timestamp, user, before/after diff (stored server-side)
- All prompt saves: version history is immutable — never delete versions
- All destructive actions: ConfirmDialog + audit log entry
- Health auto-refresh: `aria-live="polite"` on status indicators
- JSON editors: keyboard navigable, syntax errors announced to screen readers
- All modals: focus trap, Escape to close, focus returns to trigger on close
- WCAG 2.1 AA minimum

---

## Localization Notes

- Dates: ISO 8601 in logs (`2026-03-17T14:32:08Z`), `DD MMM YYYY HH:mm` in UI
- Error messages: English only — technical operators, no i18n needed for errors
- UI labels: paraglide-js i18n keys for all user-facing strings
- Config keys, prompt names, org_ids: never translated — always shown as-is
- Log lines: always shown verbatim — never translated or reformatted
