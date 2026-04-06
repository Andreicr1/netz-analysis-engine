# Wealth Frontend — Route Map (post-consolidation)

> Updated 2026-04-06 after analytics absorption into Portfolio Workspace.

## Architecture

```
frontends/wealth/src/routes/
├── +layout.server.ts          ← Root SSR (Clerk auth token)
├── +layout.svelte             ← Root layout (providers)
├── +page.server.ts            ← Redirect → /dashboard
├── auth/callback/             ← Clerk OAuth callback
└── (app)/                     ← Authenticated shell (TopNav + Sidebar)
    ├── +layout.svelte         ← App shell layout
    ├── dashboard/
    ├── screener/              ← PILLAR: Fund Discovery
    ├── market/                ← PILLAR: Macro Intelligence
    ├── portfolio/             ← PILLAR: Construction & Policy
    ├── portfolios/            ← Legacy portfolio profiles (pending migration)
    ├── documents/             ← Document management
    ├── content/               ← Content production
    └── settings/              ← Org configuration
```

## Route Table

### Auth & Root

| Route | File | Purpose |
|-------|------|---------|
| `/` | `+page.server.ts` | Redirect → `/dashboard` |
| `/auth/callback` | `auth/callback/` | Clerk OAuth callback handler |

### Dashboard

| Route | File | Purpose |
|-------|------|---------|
| `/dashboard` | `dashboard/+page.svelte` | Main dashboard (portfolio summary, alerts, recent activity) |

### Screener (Fund Discovery Pipeline)

| Route | File | Purpose |
|-------|------|---------|
| `/screener` | `screener/+page.svelte` | **Level 1** — Manager Catalog (CatalogTable + ManagerDetailPanel Sheet) |
| `/screener/fund/[id]` | `screener/fund/[id]/+page.svelte` | **Level 3** — Fund Fact Sheet (NAV chart, sector allocation, scoring radar, holdings) |
| `/screener/runs/[runId]` | `screener/runs/[runId]/+page.svelte` | Screening run results (3-layer eliminatory → mandate → quant) |
| `/screener/dd-reports` | `screener/dd-reports/+page.svelte` | DD Report list (all funds with reports) |
| `/screener/dd-reports/[fundId]` | `screener/dd-reports/[fundId]/+page.svelte` | DD Reports for a specific fund |
| `/screener/dd-reports/[fundId]/[reportId]` | `screener/dd-reports/[fundId]/[reportId]/+page.svelte` | Full DD Report reader (8 chapters, SSE streaming, confidence scoring) |

**Deleted routes:**
- ~~`/screener/[cik]`~~ → was a 301 redirect to `/screener/fund/[cik]`, removed
- ~~`/screener/managers`~~ → manager list absorbed into root `/screener` (Level 1)
- ~~`/screener/managers/[crd]`~~ → manager detail absorbed into Sheet panel (Level 2)

### Market (Macro Intelligence)

| Route | File | Purpose |
|-------|------|---------|
| `/market` | `market/+page.svelte` | Macro intelligence hub (regional charts, FRED indicators, regime) |
| `/market/reviews/[reviewId]` | `market/reviews/[reviewId]/+page.svelte` | Macro committee review reader |

**Consolidation:** Previously at `/macro` and `/macro/reviews/[reviewId]`.

### Portfolio (App-in-App Workspace)

| Route | File | Purpose |
|-------|------|---------|
| `/portfolio` | `portfolio/+page.svelte` | **Portfolio Workspace** — unified App-in-App hub (models, universe, policy, analytics & risk, stress testing, overlap, rebalance). All sub-views are rendered as pill-tabbed panels within this single route. |

**Consolidation:** Previously split across `/portfolio/approved`, `/portfolio/builder`, `/portfolio/models/*`, `/portfolio/policy`. Analytics capabilities (attribution, drift, factor analysis, risk budget) previously at `/analysis` are now absorbed into the "Analytics & Risk" tab. Centralized at `/portfolio` as a single-page App-in-App workspace with internal pill navigation managed by components in `$lib/components/portfolio/`.

**Deleted routes (absorbed into Portfolio Workspace):**
- ~~`/analysis`~~ → Attribution, drift, factor analysis, risk budget absorbed into "Analytics & Risk" tab
- ~~`/analysis/[entityId]`~~ → Entity analytics (fund-level via screener drill-down)
- ~~`/analysis/entity-analytics`~~ → Cross-entity comparison
- ~~`/analysis/exposure`~~ → Exposure analysis
- ~~`/analysis/risk`~~ → Risk dashboard (SSE-driven CVaR/regime available via riskStore at layout level)

### Portfolios (Legacy)

| Route | File | Purpose |
|-------|------|---------|
| `/portfolios` | `portfolios/+page.svelte` | Client portfolio profiles list |
| `/portfolios/[profile]` | `portfolios/[profile]/+page.svelte` | Client portfolio profile detail |

> **Note:** This is the legacy profile-based portfolio view. Pending migration into `/portfolio/` pillar.

### Documents

| Route | File | Purpose |
|-------|------|---------|
| `/documents` | `documents/+page.svelte` | Document list (uploaded PDFs, pipeline status) |
| `/documents/upload` | `documents/upload/+page.svelte` | Document upload interface |
| `/documents/[documentId]` | `documents/[documentId]/+page.svelte` | Document viewer (chunks, metadata, classification) |

### Content

| Route | File | Purpose |
|-------|------|---------|
| `/content` | `content/+page.svelte` | Content production hub (fact sheets, flash reports, outlooks) |
| `/content/[id]` | `content/[id]/+page.svelte` | Content piece viewer/editor |

### Settings

| Route | File | Purpose |
|-------|------|---------|
| `/settings` | `settings/+page.svelte` | Settings landing (org info, preferences) |
| `/settings/config` | `settings/config/+page.svelte` | Vertical config editor (ConfigService profiles, calibration) |
| `/settings/system` | `settings/system/+page.svelte` | System diagnostics (workers, storage, vector stats) |

## Navigation Mapping (TopNav → Sidebar)

```
TopNav Pillars:
  Dashboard    → /dashboard
  Screener     → /screener, /screener/fund/*, /screener/dd-reports/*
  Market       → /market, /market/reviews/*
  Portfolio    → /portfolio (App-in-App workspace, includes Analytics & Risk)
  Documents    → /documents, /documents/upload
  Content      → /content
  Settings     → /settings, /settings/config, /settings/system
```

## Screener Drill-Down Flow

```
Level 1: /screener
  └─ CatalogTable (5,692 managers, server-paginated)
     └─ click row → ManagerDetailPanel (Sheet, right slide)

Level 2: ManagerDetailPanel (Sheet)
  └─ AI ADV Profile Summary (vector search by CRD)
  └─ Managed Funds list
     └─ click fund → /screener/fund/[id]

Level 3: /screener/fund/[id]
  └─ Fund Fact Sheet (NAV, sectors, scoring, holdings, peer)
  └─ Action: Run DD Report → /screener/dd-reports/[fundId]/[reportId]
```

## Route Count

| Pillar | Pages | Server Loads |
|--------|-------|-------------|
| Auth & Root | 2 | 2 |
| Dashboard | 1 | 1 |
| Screener | 6 | 6 |
| Market | 2 | 2 |
| Portfolio | 1 | 1 |
| Portfolios (legacy) | 2 | 2 |
| Documents | 3 | 2 |
| Content | 2 | 2 |
| Settings | 3 | 2 |
| **Total** | **22** | **20** |
