# Credit Frontend — UX Principles & Component Specifications
# Private Credit OS — Implementation Guide

**Audience:** Credit analysts, Investment Committee members, portfolio managers,
fund administrators, document reviewers.
**Standard:** Every screen must meet the bar of a professional credit workflow tool —
think Bloomberg for deal management. Information-dense, action-oriented, audit-ready.
Never decorative, never ambiguous about what happens next.

**Last updated:** 2026-03-17

---

## Core Philosophy

### 1. Every screen answers one question: "What requires action now?"
The analyst opens the platform to work, not to browse. The default state of every
view must surface pending actions before surfacing data.

- Dashboard opens on: pending reviews, overdue conditions, upcoming obligations
- Deal detail opens on: current stage, blocking items, pending IC votes
- Document review opens on: checklist completion status, pending decision

Never default to a chart or summary when there are pending actions.

### 2. Deal stage is always visible and unambiguous
A deal in SCREENING looks different from a deal in IC_REVIEW looks different from
APPROVED. Stage is not a badge in a corner — it is the primary visual identity
of every deal card and deal header.

Never use raw enum values. Translate to professional credit language:
- `SCREENING` → "Initial Screening"
- `ANALYSIS` → "Credit Analysis"
- `IC_REVIEW` → "IC Review"
- `APPROVED` → "Approved — Pending Conversion"
- `CONDITIONAL` → "Approved with Conditions"
- `REJECTED` → "Declined"
- `CONVERTED` → "Active Portfolio Asset"

### 3. IC decisions are irrevocable — the UI must reflect that
Approve, Reject, and Convert are not the same as Save or Edit.
These actions have legal and financial consequences.

Every IC action requires:
- ConfirmDialog with explicit description of consequences
- Mandatory comments/rationale field (cannot be left empty)
- Display of who is acting and in what capacity
- Visible audit trail entry immediately after the action

### 4. Document lineage is not optional — it is compliance
Every document in the system has a chain: upload → ingestion → classification →
review → decision. Users must be able to trace that chain at any point.
This is how the fund demonstrates process to auditors and regulators.

### 5. Credit numbers always carry their basis
A yield without tenor is decoration. A LTV without collateral description is noise.
Every credit metric must show its basis:

- Yield: `12.5% p.a. / PIK 2% / senior secured`
- LTV: `62% / collateral: commercial real estate / appraisal 2025-11-12`
- Term: `36 months / amortizing / balloon 40%`
- Covenant: `DSCR ≥ 1.25x / tested quarterly`

### 6. The IC Memo is a first-class document, not a modal
IC Memo generation is a core value proposition of the platform. It deserves a
dedicated, full-width, printable view — not a dialog or a side panel.
The memo viewer must match the quality standard of a human-written credit memo.

### 7. Narrative level determines density — not data availability
Three distinct levels govern how much information is visible at once. Apply the
appropriate level based on the user's intent on that screen.

**Level 1 — Overview screens** (Dashboard, Pipeline list)
Synthesize and surface exceptions only. The user's question is "what requires
action now?" Every item that is not urgent or exceptional is secondary.
- Task Inbox is the dominant element on the dashboard
- Deal cards show stage, amount, age, and action-required flag only
- No expanded detail by default

**Level 2 — Workbench screens** (Deal detail, Document review, Portfolio table)
Operational. The user is actively working a specific deal or document.
- Full credit terms visible without scrolling
- Checklist, voting status, and document list visible simultaneously
- Actions immediately accessible in the header — never buried

**Level 3 — Decision pack screens** (IC Memo viewer, Report pack, Investor statement)
Linear, printable, authoritative. The user is producing or reviewing a formal record.
- Single-column layout, no competing UI elements
- Typography hierarchy favors document readability
- Print/export must produce a coherent, standalone document


---

## Global UI Rules

### Color system (strict semantic meaning — never decorative)
```
--color-stage-screening:   #6b7280   /* gray   — early stage, low commitment */
--color-stage-analysis:    #3b82f6   /* blue   — active work in progress */
--color-stage-ic:          #8b5cf6   /* purple — elevated, committee attention */
--color-stage-conditional: #f59e0b   /* amber  — approved but conditions pending */
--color-stage-approved:    #22c55e   /* green  — cleared for conversion */
--color-stage-rejected:    #ef4444   /* red    — declined */
--color-stage-converted:   #0d9488   /* teal   — active in portfolio */

--color-review-pending:    #f59e0b   /* amber  — awaiting action */
--color-review-approved:   #22c55e   /* green  */
--color-review-rejected:   #ef4444   /* red    */
--color-review-flagged:    #f97316   /* orange — requires attention */

--color-obligation-ok:     #22c55e
--color-obligation-due:    #f59e0b   /* due within 7 days */
--color-obligation-overdue:#ef4444

--color-ai-generated:      #8b5cf6   /* purple — any AI-generated content */
```

### Typography rules
- Deal amounts: `font-variant-numeric: tabular-nums` always
- Stage labels: always full text, never abbreviations in primary UI
- Dates: always DD MMM YYYY (e.g., "14 Feb 2026") — never ambiguous formats
- AI-generated content: always marked with purple `AI` badge — never presented
  as human-authored without explicit label
- Rationale/comments fields: monospace font — these are formal records

### Interaction rules
- Click on any deal card → opens deal detail (never navigate to new page from list)
- Click on any document → opens document viewer inline (slide panel)
- Click on any IC vote → opens vote detail with voter, timestamp, rationale
- All destructive actions: ConfirmDialog, mandatory rationale, immediate audit entry
- Tables: click column to sort, shift-click for secondary sort
- Stage filter always visible at top of pipeline — never buried in a sidebar

### Density follows narrative level — not data volume
Do not apply the same information density uniformly across all screens.
See Core Philosophy §7 for the three-level model. In practice:
- Dashboard → Level 1: only exceptions and actions surface by default
- Deal detail, Document review → Level 2: full operational density
- IC Memo, Report pack → Level 3: linear, printable, no competing UI

---

## View 1: Dashboard (`routes/dashboard/+page.svelte`)

### Layout

```
┌─────────────────────────────────────────────────────────┐
│ ACTION REQUIRED BANNER (conditional — when items exist) │
├─────────────────────────────────────────────────────────┤
│  PIPELINE        │  DOCUMENT REVIEWS  │  OBLIGATIONS    │
│  SUMMARY         │  PENDING           │  DUE SOON       │
│  (3 KPI cards)   │  (count + list)    │  (count + list) │
├──────────────────┴────────────────────┴─────────────────┤
│  TASK INBOX (pending IC votes, pending reviews,         │
│  overdue conditions — sorted by urgency)                │
├─────────────────────────────────────────────────────────┤
│  COMPLIANCE ALERTS  │  MACRO SNAPSHOT                   │
│                     │  (compact, for context)           │
└─────────────────────────────────────────────────────────┘
```

### Action Required Banner
Appears when any of: pending IC votes, overdue obligations, documents awaiting
review assignment. Always shown at the top — not dismissible during the session.

```
┌─────────────────────────────────────────────────────────┐
│ ⚡ 3 ITEMS REQUIRE YOUR ATTENTION                       │
│  2 IC votes pending   │  1 document review unassigned   │
│  [Go to Task Inbox →]                                   │
└─────────────────────────────────────────────────────────┘
```

### Pipeline KPI Cards (compact, 3-column)

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ PIPELINE     │  │ IN IC REVIEW │  │ CONVERTED    │
│ 14 deals     │  │ 3 deals      │  │ YTD          │
│ R$ 482M      │  │ R$ 127M      │  │ 8 deals      │
│ +2 this mo.  │  │ avg 12d      │  │ R$ 234M      │
└──────────────┘  └──────────────┘  └──────────────┘
```

Currency always shown. "avg Nd" = average days in current stage.


### Task Inbox

Single prioritized list of all pending actions across the fund, sorted by urgency.
This is the operational heart of the dashboard.

```
TASK INBOX — 7 items
──────────────────────────────────────────────────────────────────────────────
Priority  Type                  Deal / Document            Due / Age
──────────────────────────────────────────────────────────────────────────────
⚡ URGENT  IC Vote               BridgeInvest Sr. Secured   Pending 3 days
⚡ URGENT  Obligation Overdue    Construtora ABC — CRI       2 days overdue
⚠  DUE     Document Review       BridgeInvest — Due Dilig.  Due today
⚠  DUE     IC Condition          Grupo XYZ — DSCR covenant  Due in 2 days
○  PENDING  Review Unassigned    TechCo Sr. Loan — Financ.  Submitted 1d ago
○  PENDING  IC Vote              Logística Sul — Mezz        Pending 1 day
○  PENDING  Report Pack          Q1 2026 Investor Report    Not yet generated
──────────────────────────────────────────────────────────────────────────────
```

- Click any row → opens the relevant deal/document/obligation directly
- "URGENT" = overdue or pending > 48h
- "DUE" = due within 48h
- "PENDING" = active, not yet urgent

---

## View 2: Deal Pipeline (`routes/funds/[fundId]/pipeline/+page.svelte`)

### Layout

Stage filter bar always visible at top. Default view: Kanban by stage.
Toggle to list view for bulk operations.

```
Stage: [All] [Screening] [Analysis] [IC Review ●3] [Conditional ●1] [Approved]
Sort: [Requested Amount ▾]   View: [Kanban | List]   [+ New Deal]
```

### Kanban View

Each column = one stage. Cards sorted by amount descending within column.

```
INITIAL SCREENING (4)          CREDIT ANALYSIS (3)         IC REVIEW (3)
────────────────────────       ────────────────────────     ────────────────────────
┌──────────────────────┐       ┌──────────────────────┐     ┌──────────────────────┐
│ BridgeInvest         │       │ Grupo XYZ            │     │ Construtora ABC  ●   │
│ Senior Secured CRI   │       │ Senior Loan          │     │ CRI Sênior           │
│ R$ 45M  │ 18 mo      │       │ R$ 72M  │ 24 mo      │     │ R$ 38M  │ 36 mo      │
│ RE / São Paulo       │       │ Industrial / Sul      │     │ RE / Nordeste        │
│ Submitted 3d ago     │       │ In analysis 8d        │     │ ⚡ IC vote pending   │
└──────────────────────┘       └──────────────────────┘     └──────────────────────┘
```

Card rules:
- Border color = stage color
- "⚡" icon when action is required on this deal
- Sector and geography always shown (credit context)
- Time in current stage shown when > 5 business days

### List View

For bulk operations, export, and sorting by multiple dimensions.

```
Deal                    Borrower     Type          Amount    Tenor  Stage            Age
────────────────────────────────────────────────────────────────────────────────────────
BridgeInvest Sr. CRI    BridgeInvest RE / Sênior   R$ 45M   18mo   IC Review  ⚡   12d
Grupo XYZ Loan          Grupo XYZ    Ind. / Sênior  R$ 72M   24mo   Analysis         8d
Construtora ABC CRI     Const. ABC   RE / Sênior    R$ 38M   36mo   IC Review        5d
...
```

---

## View 3: Deal Detail (`routes/funds/[fundId]/pipeline/[dealId]/+page.svelte`)

This is the most important view. It is the command center for a single deal.

### Header (always visible, sticky)

```
┌─────────────────────────────────────────────────────────────────────┐
│ BridgeInvest — Senior Secured CRI          [● IC REVIEW]            │
│ R$ 45,000,000  │  18 months  │  Real Estate / São Paulo             │
│ Submitted: 2026-02-12  │  In IC Review: 12 days  │  Lead: A. Silva  │
│                                                                     │
│ [Generate IC Memo]  [View Documents]  [Stage Actions ▾]             │
└─────────────────────────────────────────────────────────────────────┘
```

Stage Actions dropdown shows only valid next actions for current stage:
- In IC_REVIEW: "Approve", "Approve with Conditions", "Reject"
- In CONDITIONAL: "Resolve Condition", "Convert to Portfolio Asset"
- In APPROVED: "Convert to Portfolio Asset"

Never show actions that are invalid for the current stage.

### Tab Navigation

```
[Overview]  [Credit Analysis]  [IC Memo]  [Documents]  [Conditions]  [Timeline]
```


### Tab: Overview

Left column (40%): deal summary card with all key credit terms.
Right column (60%): stage timeline + IC voting status.

**Deal Summary Card — all fields mandatory, no "N/A" allowed**
```
Borrower:         BridgeInvest Fundo CRI LTDA
Instrument:       CRI — Certificado de Recebíveis Imobiliários
Amount:           R$ 45,000,000
Yield:            CDI + 4.5% p.a. / senior secured
LTV:              58% / collateral: commercial office / appraisal 2025-10-20
Tenor:            18 months / bullet
Covenants:        LTV ≤ 65% (tested monthly) / DSCR ≥ 1.20x (tested quarterly)
Guarantees:       Corporate guarantee — BridgeInvest Holding S.A.
Sector:           Real Estate / Commercial
Geography:        São Paulo – SP
Originator:       Netz Asset Management
```

**Stage Timeline**
```
● Submitted      2026-02-12
● Screening      2026-02-14  (2d)   A. Silva
● Analysis       2026-02-20  (6d)   M. Costa
● IC Review  ●   2026-03-01  (12d)  [pending]
○ Decision
○ Conversion
```

**IC Voting Status** (shown when stage = IC_REVIEW)
```
IC VOTE — BridgeInvest Sr. CRI
──────────────────────────────────────────
Voter             Vote      Date      Notes
──────────────────────────────────────────
A. Ferreira       ✓ Approve 2026-03-10  "Strong collateral coverage"
R. Mendes         ○ Pending —           —
P. Oliveira       ○ Pending —           —
──────────────────────────────────────────
Quorum: 2/3 required  │  1/3 voted  │  Threshold not reached
```

### Tab: IC Memo

Full-width, printable view. Never a modal or side panel.

Header of memo view:
```
┌─────────────────────────────────────────────────────────┐
│ IC MEMO — BridgeInvest Senior Secured CRI               │
│ Generated: 2026-03-08 14:32  │  Model: gpt-4o           │
│ [AI] AI-generated — reviewed by A. Silva on 2026-03-09  │
│                                                         │
│ [Regenerate]  [Download PDF]  [Print]                   │
└─────────────────────────────────────────────────────────┘
```

- AI badge always visible on AI-generated content — never hidden
- "Reviewed by" field mandatory before the memo can be used in IC voting
- Sections: Executive Summary, Borrower Profile, Transaction Structure,
  Credit Analysis, Collateral Analysis, Risk Factors, Recommendation
- Each section collapsible but expanded by default
- Print view: removes all UI chrome, retains section headers and content

### Tab: Conditions (shown only when stage = CONDITIONAL)

```
IC CONDITIONS — 2 pending / 3 total
──────────────────────────────────────────────────────────────────
#  Condition                          Status    Due         Notes
──────────────────────────────────────────────────────────────────
1  Updated appraisal report           ✓ Done    2026-03-05  "Received"
2  Corporate guarantee from holding   ○ Pending 2026-03-20  —
3  Environmental clearance letter     ○ Pending 2026-03-20  —
──────────────────────────────────────────────────────────────────
```

Each pending condition: checkbox (IC member only) + notes field + due date.
Checking a condition: ConfirmDialog with rationale field. Immutable after check.

---

## View 4: Document Review (`routes/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte`)

### Header

```
┌──────────────────────────────────────────────────────────────┐
│ DOCUMENT REVIEW — BridgeInvest Due Diligence Pack            │
│ Status: [● UNDER REVIEW]   Assigned: M. Costa   Age: 3 days  │
│                                                              │
│ [Assign Reviewer]  [Run AI Analysis]  [Decide ▾]             │
└──────────────────────────────────────────────────────────────┘
```

### Two-Column Layout

Left (35%): document viewer (PDF inline or file list).
Right (65%): checklist + AI analysis + decision.

**Checklist**
```
REVIEW CHECKLIST — 8/12 complete
────────────────────────────────────────────────────────────
✓  Corporate registration documents
✓  Last 3 years audited financial statements
✓  Collateral ownership deed
✓  Environmental clearance
○  Updated appraisal report (< 6 months)
○  Corporate organizational chart
○  Shareholders agreement
✓  Bank references (min. 2)
...
```

Each checkbox: interactive (reviewer only). Optimistic UI with per-item loading state.
Unchecking requires confirmation + reason.

**AI Analysis Panel** (after trigger)
Shows: document classification confidence, extracted key metrics, identified
risk flags, completeness score. Always labeled `[AI]`. Never auto-shown — only
after explicit "Run AI Analysis" trigger.

**Decision Panel**
```
DECISION
────────────────────────────────────────────
○ Approve
○ Approve with flags (list flags below)
○ Request revision
○ Reject

Rationale: [required — minimum 50 characters]

[Submit Decision]
```


---

## View 5: Portfolio (`routes/funds/[fundId]/portfolio/+page.svelte`)

### Layout

```
┌───────────────────────────────────────────────────────────────┐
│  PORTFOLIO SUMMARY  │  COMPLIANCE ALERTS  │  UPCOMING         │
│  (NAV, yield, count)│  (covenant breaches)│  OBLIGATIONS      │
├───────────────────────────────────────────────────────────────┤
│  ASSETS TABLE (full width, sortable, expandable rows)         │
└───────────────────────────────────────────────────────────────┘
```

### Assets Table

```
Asset                  Type    Amount   Yield         LTV   Maturity    Status
──────────────────────────────────────────────────────────────────────────────────
BridgeInvest CRI       CRI     R$45M   CDI+4.5%/sr   58%  2027-08-12  ✓ Current
Construtora ABC CRI    CRI     R$38M   CDI+5.2%/sr   62%  2027-06-30  ⚠ Monitor
Grupo XYZ Loan         Loan    R$72M   CDI+6.0%/mz   —    2028-02-28  ✓ Current
──────────────────────────────────────────────────────────────────────────────────
Total                          R$155M  Avg CDI+5.1%        WAL: 18.4mo
```

- Status: ✓ Current, ⚠ Monitor (covenant approaching), ✗ Breach, ⏰ Maturity < 90d
- Expand row → obligations schedule, covenant tests, payment history
- "WAL" (weighted average life) always shown in portfolio footer

### Obligations Sub-Table (expanded row)

```
▼ BridgeInvest CRI — Obligations
──────────────────────────────────────────────────────────────────
Date         Type              Amount     Status
──────────────────────────────────────────────────────────────────
2026-03-31   Interest payment  R$ 168,750  ⚠ Due in 14 days
2026-06-30   Interest payment  R$ 168,750  ○ Scheduled
2026-09-30   Interest payment  R$ 168,750  ○ Scheduled
2027-08-12   Principal + int.  R$45,168,750 ○ Scheduled
──────────────────────────────────────────────────────────────────
```

---

## View 6: Reporting (`routes/funds/[fundId]/reporting/+page.svelte`)

### Layout

```
┌─────────────────────────────────────────────┐
│  REPORT PACKS   │  NAV SNAPSHOTS            │
│  (list + gen.)  │  (timeline + create)      │
├─────────────────┴────────────────────────────┤
│  INVESTOR STATEMENTS  │  EVIDENCE PACKS     │
└───────────────────────┴─────────────────────┘
```

### Report Pack Row

```
Pack                    Period      Status       Actions
──────────────────────────────────────────────────────────────────────
Q1 2026 Investor Pack   Jan–Mar 26  ○ Not gen.   [Generate]
Q4 2025 Investor Pack   Oct–Dec 25  ✓ Published  [View] [Download]
Q3 2025 Investor Pack   Jul–Sep 25  ✓ Published  [View] [Download]
```

Generate: ActionButton → long-running → SSE progress bar.
Publish: ConfirmDialog with "This will be visible to investors — confirm."

---

## Component Anti-Patterns (NEVER DO)

1. **Never show a deal amount without currency and tenor.**
   Bad: "45,000,000"
   Good: "R$ 45,000,000 / 18 months / senior secured"

2. **Never expose raw stage enums.**
   Bad: "IC_REVIEW"
   Good: "IC Review" with purple stage badge

3. **Never allow IC actions without a rationale field.**
   Approve, Reject, Convert: all require a mandatory written rationale.
   Minimum 50 characters. This is a legal record.

4. **Never present AI-generated content without a label.**
   IC Memo, AI Analysis, document classification: always show `[AI]` badge.
   Reviewed memos show: "Reviewed by [name] on [date]"

5. **Never hide the stage timeline.**
   How long a deal has been in each stage is an operational metric.
   It must always be one click away from any deal view.

6. **Never use generic empty states in the Task Inbox.**
   Bad: "No pending tasks"
   Good: "No pending actions — all reviews assigned, IC votes current,
          obligations on track. Last checked: today 08:14."

7. **Never show a covenant without its test frequency.**
   Bad: "LTV ≤ 65%"
   Good: "LTV ≤ 65% / tested monthly"

8. **Never auto-trigger IC Memo generation.**
   The analyst must explicitly request it. Generation is a billable AI operation
   and produces a formal document — it is never triggered automatically.

9. **Never show document review checklist as read-only by default.**
   If the user has reviewer role and the review is under review, the checklist
   is interactive immediately. Read-only is the exception, not the default.

10. **Never paginate the obligation schedule.**
    A borrower's full payment schedule must be visible in one scroll.
    Pagination hides future obligations and breaks cash flow analysis.

---

## Accessibility & Compliance Requirements

- All IC decisions: logged with timestamp, user identity, rationale — immutable
- All AI-generated content: labeled, with generation timestamp and model version
- Document review decisions: full audit trail with reviewer, date, rationale
- All destructive actions: ConfirmDialog + rationale + audit log entry
- Currency amounts: always show currency symbol (R$, USD, etc.)
- Dates: always `DD MMM YYYY` format — never ambiguous
- WCAG 2.1 AA minimum for all text and interactive elements

---

## Localization Notes

- All amounts: `Intl.NumberFormat` with explicit currency code
- All dates: `Intl.DateTimeFormat` — always show full date, never relative-only
  (relative "3 days ago" always accompanied by absolute date on hover)
- Stage labels, status labels: paraglide-js i18n keys — never hardcoded
- Covenant descriptions: always in the language of the credit agreement
