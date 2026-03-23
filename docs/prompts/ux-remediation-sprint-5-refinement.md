# UX Remediation Sprint 5 — Refinement (P4)

## Context

You are executing Sprint 5 of the Premium UX Remediation effort for the Netz Analysis Engine — a multi-tenant institutional investment platform with Credit and Wealth verticals.

Read these files before starting any work:
- `CLAUDE.md` — full project rules, architecture, critical constraints
- `docs/ux/premium-ux-remediation-execution-backlog.md` — full backlog (you are executing Phase 5: BL-18 through BL-22)

**Sprint 1 (P0 Critical Safety) is complete.** BL-01 through BL-05: approval friction, ConsequenceDialog, mandatory rationale, enum validation.

**Sprint 2 (P1 Governance Integrity) is complete.** BL-06 and BL-07: `DDReportStatus` and `UniverseDecision` enums, `CheckConstraint` via migration `0022_wealth_status`, audit trail logging with `write_audit_event()`, audit trail query endpoints.

**Sprint 3 (P2 System Legibility) is complete.** BL-08 through BL-12: Evidence Pack Inspectors for IC Memos and DD Reports, AI Content Markers, Classification Layer badges, StatusBadge dev warning.

**Sprint 4 (P3 Structural Consistency) is complete.** BL-13 through BL-17:
- BL-13: SLA-Aware Loading States — `LongRunningAction` in `@netz/ui` now supports `slaSeconds` and `slaMessage` props with elapsed timer + SLA warning. IC memo generation uses `slaSeconds={180}`. DD report page shows SLA-aware regeneration banner with elapsed time and "Taking longer than expected" at 3min. "generating" status shows refresh button.
- BL-14: Streaming Error Recovery — DD report regeneration errors show inline retry button. `createSSEStream` already has exponential backoff (5 retries). `LongRunningAction` surfaces errors with Retry button. Partial content preserved on error.
- BL-15: Conviction Confidence Calibration — `confidence_score` and `decision_anchor` added to frontend `DDReportSummary` type. DD report detail page shows confidence bar with color gradient (Low/warning <60, Moderate/info 60-80, High/success >80) and AI recommendation badge (APPROVE/green, CONDITIONAL/warning, REJECT/danger).
- BL-16: Negative Screening Emphasis — Eliminated instruments in screener table show dimmed opacity, strikethrough name, and inline elimination reason ("L1 fail: {criterion}"). L1 pass shows subtle "OK" label. Eliminated rows have danger-tinted background.
- BL-17: Override Audit Narrative — ConsequenceDialog for DD report approve/reject now shows AI recommendation as `metadata` (label + value grid). Override detection: if user approves when AI says REJECT/CONDITIONAL, or rejects when AI says APPROVE, a warning banner appears in the dialog footer. Backend audit trail captures `decision_anchor` and `confidence_score` in `before` snapshot. Override events use distinct action labels (`dd_report.approve.override`, `dd_report.reject.override`).

---

## What you are fixing

This sprint covers **BL-18 through BL-22** — Refinement and Perception items.

### BL-18 — Remove Internal-Only Noise from Investor Surfaces

**Problem:** Investor pages may display operational metadata (ingestion status, pipeline stage, classification layer) that is meaningful to internal users but noise for investors.

**Backlog reference:** BL-18 in `docs/ux/premium-ux-remediation-execution-backlog.md`

**Scope:** Audit all `(investor)` route pages in both frontends. Remove operational fields that have no investor meaning.

**Acceptance criteria:**
- No investor page displays: ingestion status, classification layer, classification confidence, pipeline stage, embedding metadata, or internal review status
- Investor pages display only: document name, date, type, download action, report content, portfolio positions, fund metrics
- Any operational field removal is verified against the investor API response (not just hidden in CSS)

---

### BL-19 — ESLint CI Enforcement for Frontends

**Problem:** `frontends/eslint.config.js` bans `.toFixed()`, `.toLocaleString()`, `new Intl.NumberFormat()`, and `new Intl.DateTimeFormat()`. But `make check` does not run ESLint on frontends. `frontends/wealth/src/lib/stores/stale.ts` (lines 14-23, 89) already violates these rules.

**Scope:** Build system. Add `pnpm lint` to `make check` or create `make lint-frontend`. Fix violations. Verify all frontends pass.

**Acceptance criteria:**
- `make check` (or `make check-full`) runs frontend ESLint and fails on violations
- `stale.ts` passes ESLint with no formatter violations
- No existing frontend file has ESLint violations (clean baseline before enforcement)

**Research needed:**
- Check whether Turborepo's existing `check` task includes ESLint or only `svelte-check`
- Run ESLint across all frontends to surface unknown violations before enforcement

---

### BL-20 — Branding Override Safety: Contrast Validation

**Problem:** `branding.ts` maps `BrandingConfig` fields to CSS custom properties via `Element.style.setProperty()`. A tenant with misconfigured branding can override tokens without contrast validation.

**Scope:** Backend validation on branding config save + frontend fallback.

**Acceptance criteria:**
- Branding configuration validates minimum contrast ratio (WCAG AA: 4.5:1) between text and surface colors
- Invalid configurations are rejected with specific error messages
- Alternatively: frontend fallback that detects insufficient contrast at runtime and reverts to default tokens

**Research needed:**
- Find `branding.ts` location in frontends
- Check if branding configuration is admin-only or tenant-self-service
- Check if there's a backend branding endpoint

---

### BL-21 — Sign-In Page Token Compliance

**Problem:** Sign-in pages contain ~10+ fallback hex colors in `var()` declarations, ~6 inline `rgba()` box-shadows, and ~15 hardcoded px spacing values. These violate single-source-of-truth token governance.

**Scope:** Frontend. Replace hardcoded values with token references.

**Acceptance criteria:**
- Zero hardcoded hex colors outside `var()` declarations in sign-in pages
- All spacing uses token references or Tailwind classes
- Sign-in pages render correctly in dark mode

**Research needed:**
- Find all sign-in pages across frontends (credit, wealth, admin)
- Inventory hardcoded values to determine scope

---

### BL-22 — ContextPanel Unused Code Cleanup

**Problem:** `ContextPanel.svelte` (186 lines) in `@netz/ui` is fully implemented but unused in any frontend.

**UPDATE:** As of Sprint 4, `ContextPanel` IS used in `frontends/wealth/src/routes/(team)/screener/+page.svelte` (lines 475-621, plus run detail and history panels). **Do NOT delete it.** Instead, add a doc comment explaining its active use case.

**Acceptance criteria:**
- ContextPanel has a JSDoc/comment explaining its use in the screener page
- Verify no other unused components exist in `@netz/ui`

---

## Execution strategy — parallel agents

Use `model: sonnet` for all agents.

### Phase 1 — Research (2 agents in parallel)

**Agent R1 — Investor pages and ESLint audit**
- Audit all `(investor)` route pages in both frontends for operational metadata
- Run ESLint across all frontends, surface violations
- Check Turborepo check task for ESLint inclusion

**Agent R2 — Branding, sign-in, and ContextPanel**
- Find branding.ts and branding backend endpoints
- Inventory sign-in page hardcoded values
- Verify ContextPanel usage across frontends

### Phase 2 — Implementation (based on research)

Parallelize: BL-18 (investor cleanup), BL-19 (ESLint), BL-20+BL-21 (tokens/branding), BL-22 (doc comment).

### Phase 3 — Verification

- Run `make check-all` (frontend checks)
- Run ESLint if wired
- Verify 0 errors across all packages

---

## Critical rules (from CLAUDE.md)

- **Frontends never cross-import:** `frontends/credit/` and `frontends/wealth/` share only via `@netz/ui` and the backend API
- **Frontend formatter discipline:** Use formatters from `@netz/ui` (`formatDate`, `formatNumber`, `formatPercent`, etc.). Never `.toFixed()`, `.toLocaleString()`, or inline `Intl`
- **Svelte 5 runes:** Use `$state`, `$derived`, `$effect` syntax
- Do not add features beyond scope. This sprint is strictly BL-18 through BL-22.

---

## What to do when this sprint is done

After completing all items and verifying:
1. Run `make check-all` to confirm frontend gates pass
2. Commit with a descriptive message covering BL-18 through BL-22
3. The UX Remediation backlog is complete after this sprint.
