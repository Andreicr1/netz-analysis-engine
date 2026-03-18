# Frontend Type Inventory

**Generated:** 2026-03-18
**Branch:** `fix/backend-authz-isolation`
**Scope:** Credit, Wealth, Admin, Shared/Core (@netz/ui)
**Cross-references:** `docs/plans/ux-remediation-plan.md`, `docs/audit/endpoint_coverage_audit.md`, `docs/audit/backend-architecture-audit-v1.md`

---

## 1. Inventory Method

### Sources inspected
- `packages/ui/src/types/api.d.ts` — OpenAPI-generated type stub
- `frontends/credit/src/lib/types/api.ts` — hand-written Credit response types (302 lines)
- `frontends/wealth/src/lib/types/api.ts` — hand-written Wealth response types (83 lines)
- `frontends/admin/src/lib/types.ts` — hand-written Admin types (78 lines)
- `packages/ui/src/lib/utils/types.ts` — shared navigation/branding types
- `packages/ui/src/lib/utils/auth.ts` — Actor identity type
- `packages/ui/src/lib/utils/api-client.ts` — error classes, NetzApiClient
- `packages/ui/src/lib/utils/sse-client.svelte.ts` — SSE types
- `packages/ui/src/lib/utils/poller.svelte.ts` — polling types
- `packages/ui/src/lib/components/AuditTrailPanel.svelte` — audit entry types
- `packages/ui/src/lib/components/ConsequenceDialog.svelte` — mutation dialog types
- `packages/ui/src/lib/components/AlertFeed.svelte` — WealthAlert discriminated union
- `frontends/wealth/src/lib/stores/risk-store.svelte.ts` — risk state types
- All `+page.server.ts` and `+layout.server.ts` loaders across three frontends
- All Svelte component files with API data consumption
- `Makefile` line 74-75 (`make types` command)

### Canonical evidence (higher trust)
- Explicitly defined and exported TypeScript interfaces/types in dedicated type files
- Imports verified in consumer files (loaders, stores, components)
- Backend endpoint existence verified via `endpoint_coverage_audit.md`

### Lower-trust evidence
- Inline interfaces in loader files (may drift from backend)
- `Record<string, unknown>` usage (no shape validation)
- `as any` / `as unknown` casts (type safety bypassed)
- Types defined but not imported by any verified consumer

---

## 2. Type Source Map

### Generated types location
| Source | Path | Status |
|---|---|---|
| OpenAPI auto-generated | `packages/ui/src/types/api.d.ts` | **EMPTY STUB** — `paths {}`, `components {}`, `operations {}` |
| Generation command | `npx openapi-typescript http://localhost:8000/openapi.json -o packages/ui/src/types/api.d.ts` | Exists in Makefile (`make types`) but never populated |

### Shared domain type locations
| Source | Path | Scope |
|---|---|---|
| Credit vertical types | `frontends/credit/src/lib/types/api.ts` | 30+ interfaces/types covering dashboard, deals, IC memo, portfolio, documents, reviews, reporting, copilot |
| Wealth vertical types | `frontends/wealth/src/lib/types/api.ts` | 9 interfaces covering regime, content, macro, instruments, DD reports, funds |
| Admin types | `frontends/admin/src/lib/types.ts` | 9 interfaces covering health, tenants, config, prompts |
| Shared navigation/branding | `packages/ui/src/lib/utils/types.ts` | `NavItem`, `BrandingConfig`, `ContextNav` |
| Auth/Actor | `packages/ui/src/lib/utils/auth.ts` | `Actor` (user_id, organization_id, organization_slug, role, email, name) |
| Audit trail | `packages/ui/src/lib/components/AuditTrailPanel.svelte` | `AuditTrailEntry`, `AuditTrailFieldChange`, `AuditTrailStatus` |
| Mutation dialog | `packages/ui/src/lib/components/ConsequenceDialog.svelte` | `ConsequenceDialogPayload`, `ConsequenceDialogMetadataItem` |
| Alert types | `packages/ui/src/lib/components/AlertFeed.svelte` | `WealthAlert` (5-variant discriminated union) |
| Risk store | `frontends/wealth/src/lib/stores/risk-store.svelte.ts` | `CVaRStatus`, `CVaRPoint`, `DriftAlert`, `BehaviorAlert`, `RegimeData`, `RiskStoreState`, `RiskStoreConfig`, `StoreStatus` |
| SSE client | `packages/ui/src/lib/utils/sse-client.svelte.ts` | `SSEStatus`, `SSEEvent`, `SSEConfig<T>`, `SSEConnection<T>`, `SSESnapshotConfig<T>`, `SSESnapshotConnection<T>` |
| Poller | `packages/ui/src/lib/utils/poller.svelte.ts` | `PollerConfig<T>`, `PollerState<T>` |
| API errors | `packages/ui/src/lib/utils/api-client.ts` | `AuthError`, `ForbiddenError`, `ValidationError`, `ServerError`, `ConflictError` |

### API client type boundaries
- `NetzApiClient` methods are fully generic (`get<T>()`, `post<T>()`, etc.)
- Callers supply type parameter at call site: `api.get<{ items: Fund[] }>("/funds")`
- Request bodies are `unknown` — no request payload type validation
- No path autocomplete or endpoint-shape enforcement (OpenAPI types empty)

### Route/store/component consumer boundaries
- **Server loaders** (`+page.server.ts`): Use `api.get<T>()` with inline or imported types, return data via `Promise.allSettled`
- **Client components**: Use `createClientApiClient(getToken)` via Svelte context, type responses at call site
- **Stores** (`risk-store.svelte.ts`): Define and export their own state types, used by components via context
- **Components**: Accept data via `$props()` with `interface Props`, mostly untyped or loosely typed from loader data

---

## 3. Domain Inventory: Credit

### Dashboard types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| `PortfolioSummary` | `credit/src/lib/types/api.ts:5` | `GET /dashboard/portfolio-summary` | `dashboard/+page.svelte` | CANONICAL_AND_CONSUMED | |
| `PipelineSummary` | `credit/src/lib/types/api.ts:12` | `GET /dashboard/pipeline-summary` | `dashboard/+page.svelte` | CANONICAL_AND_CONSUMED | |
| `PipelineAnalytics` | `credit/src/lib/types/api.ts:20` | `GET /dashboard/pipeline-analytics` | `dashboard/+page.svelte` | CANONICAL_AND_CONSUMED | |
| `MacroSnapshot` | `credit/src/lib/types/api.ts:25` | `GET /dashboard/macro-snapshot` | `dashboard/+page.svelte` | CANONICAL_AND_CONSUMED | |
| `TaskItem` | `credit/src/lib/types/api.ts:32` | `GET /dashboard/task-inbox` | `dashboard/+page.svelte` | CANONICAL_AND_CONSUMED | |
| Compliance alerts response | — | `GET /dashboard/compliance-alerts` | `dashboard/+page.server.ts` | MISSING | Loader fetches but no typed response |
| FRED macro history/series | — | `GET /dashboard/macro-history`, `macro-fred-series`, `fred-search`, `macro-fred-multi` | `dashboard/+page.svelte` (partial) | MISSING | `fred-search` called from client but response typed as `unknown[]` via cast |

### Deal / Fund types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| `DealDetail` | `credit/src/lib/types/api.ts:52` | `GET /funds/{fund_id}/deals/{deal_id}` | `pipeline/[dealId]/+page.svelte` | PARTIAL_OR_DRIFTING | Loader casts result to `Record<string, unknown>` — type exists but not used by loader |
| `DealType` | `credit/src/lib/types/api.ts:42` | — | Component-level rendering | CANONICAL_AND_CONSUMED | Union type |
| `DealStage` | `credit/src/lib/types/api.ts:44` | — | `DealStageTimeline.svelte`, filtering | CANONICAL_AND_CONSUMED | Union type |
| `RejectionCode` | `credit/src/lib/types/api.ts:48` | — | Deal detail rendering | CANONICAL_AND_CONSUMED | Union type |
| `StageTimeline` | `credit/src/lib/types/api.ts:70` | `GET /funds/{fund_id}/deals/{deal_id}/stage-timeline` | `DealStageTimeline.svelte` | CANONICAL_AND_CONSUMED | |
| `StageTimelineNode` | `credit/src/lib/types/api.ts:78` | — | `DealStageTimeline.svelte` | CANONICAL_AND_CONSUMED | |
| `StageTimelineEvent` | `credit/src/lib/types/api.ts:85` | — | `DealStageTimeline.svelte` | CANONICAL_AND_CONSUMED | |
| `StageTimelineEntry` | `credit/src/lib/types/api.ts:92` | — | — | CANONICAL_BUT_UNUSED | Defined but no verified consumer |
| Deal create request | — | `POST /funds/{fund_id}/deals` | — | MISSING | Endpoint exists, no request type, no frontend consumer (disconnected) |
| Deal decision request | — | `PATCH /funds/{fund_id}/deals/{deal_id}/decision` | — | MISSING | Endpoint exists, no request type, no frontend consumer (disconnected) |
| Deal convert request | — | `POST /funds/{fund_id}/deals/{deal_id}/convert` | — | MISSING | Endpoint exists, no request type, no frontend consumer (disconnected) |
| IC condition resolve request | — | `PATCH /funds/{fund_id}/deals/{deal_id}/ic-memo/conditions` | — | MISSING | Endpoint exists, no request type, no frontend consumer (disconnected) |

### IC Memo types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| `ICMemoDetail` | `credit/src/lib/types/api.ts:100` | `GET /funds/{fund_id}/deals/{deal_id}/ic-memo` | Deal detail page | CANONICAL_AND_CONSUMED | `condition_history: Record<string, unknown>[]` — weak subtype |
| `ICCondition` | `credit/src/lib/types/api.ts:114` | — | `ICMemoDetail.conditions`, `VotingStatusDetail.conditions.items` | CANONICAL_AND_CONSUMED | |
| `VotingStatusDetail` | `credit/src/lib/types/api.ts:124` | `GET /funds/{fund_id}/deals/{deal_id}/ic-memo/voting-status` | Deal detail page | CANONICAL_AND_CONSUMED | `conditionHistory: Record<string, unknown>[]` — weak subtype |
| `ICMemo` | `credit/src/lib/types/api.ts:277` | `POST /funds/{fund_id}/deals/{deal_id}/ic-memo` (generate) | `ICMemoViewer.svelte` | CANONICAL_AND_CONSUMED | Simpler than `ICMemoDetail` — used for generation response |
| `ICMemoChapter` | `credit/src/lib/types/api.ts:282` | — | `ICMemo.chapters` | CANONICAL_AND_CONSUMED | |
| `VotingStatus` | `credit/src/lib/types/api.ts:289` | — | — | CANONICAL_BUT_UNUSED | Simpler alternative to `VotingStatusDetail` — appears unused |
| IC memo generate request | — | `POST /funds/{fund_id}/deals/{deal_id}/ic-memo` | `ICMemoViewer.svelte` | MISSING | Endpoint called but no request body type |

### Portfolio types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| `PaginatedResponse<T>` | `credit/src/lib/types/api.ts:157` | Various list endpoints | Loaders | CANONICAL_AND_CONSUMED | Generic wrapper |
| `PortfolioAsset` | `credit/src/lib/types/api.ts:168` | `GET /funds/{fund_id}/portfolio/assets` (inferred) | Portfolio page | CANONICAL_AND_CONSUMED | |
| `PortfolioObligation` | `credit/src/lib/types/api.ts:179` | `GET /funds/{fund_id}/obligations` | Portfolio page | CANONICAL_AND_CONSUMED | |
| `PortfolioAlert` | `credit/src/lib/types/api.ts:191` | `GET /funds/{fund_id}/alerts` | Portfolio page | CANONICAL_AND_CONSUMED | |
| `PortfolioAction` | `credit/src/lib/types/api.ts:198` | `GET /funds/{fund_id}/portfolio/actions` | Portfolio page | CANONICAL_AND_CONSUMED | |
| `AssetType` | `credit/src/lib/types/api.ts:162` | — | Component rendering | CANONICAL_AND_CONSUMED | Same values as `DealType` — potential duplication |
| `Strategy` | `credit/src/lib/types/api.ts:163` | — | Component rendering | CANONICAL_AND_CONSUMED | |
| `ObligationType` | `credit/src/lib/types/api.ts:164` | — | Component rendering | CANONICAL_AND_CONSUMED | |
| `ObligationStatus` | `credit/src/lib/types/api.ts:165` | — | Component rendering | CANONICAL_AND_CONSUMED | |
| `ActionStatus` | `credit/src/lib/types/api.ts:166` | — | Component rendering | CANONICAL_AND_CONSUMED | |
| Asset create request | — | `POST /funds/{fund_id}/assets` | — | MISSING | Disconnected endpoint |
| Obligation create request | — | `POST /funds/{fund_id}/assets/{asset_id}/obligations` | — | MISSING | Disconnected endpoint |
| Obligation update request | — | `PATCH /funds/{fund_id}/obligations/{obligation_id}` | — | MISSING | Disconnected endpoint |
| Action update request | — | `PATCH /funds/{fund_id}/portfolio/actions/{action_id}` | — | MISSING | Disconnected endpoint |

### Document / Review types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| `DocumentItem` | `credit/src/lib/types/api.ts:211` | `GET /documents` | Documents list page | CANONICAL_AND_CONSUMED | |
| `ReviewItem` | `credit/src/lib/types/api.ts:221` | `GET /funds/{fund_id}/document-reviews` | Reviews list page | CANONICAL_AND_CONSUMED | |
| `ReviewSummary` | `credit/src/lib/types/api.ts:229` | `GET /funds/{fund_id}/document-reviews/summary` | Reviews summary | CANONICAL_AND_CONSUMED | |
| `ReviewDetail` | `credit/src/lib/types/api.ts:236` | `GET /funds/{fund_id}/document-reviews/{review_id}` | Review detail page | CANONICAL_AND_CONSUMED | |
| `ReviewAssignment` | `credit/src/lib/types/api.ts:242` | — | `ReviewDetail.assignments` | CANONICAL_AND_CONSUMED | |
| `ReviewChecklist` | `credit/src/lib/types/api.ts:247` | `GET /funds/{fund_id}/document-reviews/{review_id}/checklist` | Review detail page | CANONICAL_AND_CONSUMED | |
| `ChecklistItem` | `credit/src/lib/types/api.ts:251` | — | `ReviewChecklist.items` | CANONICAL_AND_CONSUMED | |
| Review decide request | — | `POST /funds/{fund_id}/document-reviews/{review_id}/decide` | Review detail page | MISSING | Endpoint called but request body not typed |
| Review assign request | — | `POST .../assign` | — | MISSING | Disconnected endpoint |
| Review finalize request | — | `POST .../finalize` | — | MISSING | Disconnected endpoint |
| Review resubmit request | — | `POST .../resubmit` | — | MISSING | Disconnected endpoint |
| Review AI analyze request | — | `POST .../ai-analyze` | — | MISSING | Disconnected endpoint |
| Checklist check/uncheck | — | `POST .../checklist/{item_id}/check|uncheck` | — | MISSING | Disconnected endpoints |
| Document detail response | — | `GET /documents/{document_id}` | `documents/[documentId]/+page.server.ts` | PHANTOM_CONSUMER | Loader fetches but casts to `Record<string, unknown>` — no type |
| Document versions response | — | `GET /documents/{document_id}/versions` | `documents/[documentId]/+page.server.ts` | PHANTOM_CONSUMER | Same cast pattern |

### Reporting types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| `NavSnapshot` | `credit/src/lib/types/api.ts:258` | `GET /funds/{fund_id}/reports/nav/snapshots` | Reporting page | CANONICAL_AND_CONSUMED | |
| `ReportPack` | `credit/src/lib/types/api.ts:265` | `GET /funds/{fund_id}/reports/monthly-pack/list` | Reporting page | CANONICAL_AND_CONSUMED | Status union: `"DRAFT" | "GENERATED" | "PUBLISHED"` |
| Report pack generate request | — | `POST /funds/{fund_id}/report-packs/{pack_id}/generate` | — | MISSING | Disconnected endpoint |
| Report pack publish request | — | `POST /funds/{fund_id}/report-packs/{pack_id}/publish` | — | MISSING | Disconnected endpoint |
| Evidence pack response | — | `POST /funds/{fund_id}/reports/evidence-pack` | Reporting page | MISSING | Endpoint called but response not typed |

### Copilot types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| `Citation` | `credit/src/lib/types/api.ts:297` | `POST /ai/answer` | `CopilotChat.svelte` | CANONICAL_AND_CONSUMED | |
| AI answer response | — | `POST /ai/answer` | `CopilotChat.svelte` | PARTIAL_OR_DRIFTING | Inline type at call site: `{ answer?: string; citations?: unknown[] }` — `citations` not typed as `Citation[]` |

### Investor portal types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| Investor documents | — | `GET /funds/{fund_id}/investor/documents` | `(investor)/documents/+page.server.ts` | PHANTOM_CONSUMER | `Record<string, unknown>[]` — no type |
| Investor report packs | — | `GET /funds/{fund_id}/investor/report-packs` | `(investor)/report-packs/+page.server.ts` | PHANTOM_CONSUMER | `Record<string, unknown>[]` — no type |
| Investor statements | — | `GET /funds/{fund_id}/investor/statements` | `(investor)/statements/+page.server.ts` | PHANTOM_CONSUMER | `Record<string, unknown>[]` — no type |

---

## 4. Domain Inventory: Wealth

### Regime / Risk types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| `RegimeData` | `wealth/src/lib/types/api.ts:5` AND `risk-store.svelte.ts:45` | `GET /risk/regime` | Dashboard, Risk page, risk-store | PARTIAL_OR_DRIFTING | **Duplicated** — identical definition in two files |
| `CVaRStatus` | `risk-store.svelte.ts:15` | `GET /risk/{profile}/cvar` | Dashboard, Risk page via store | CANONICAL_AND_CONSUMED | Store-local, not in `api.ts` |
| `CVaRPoint` | `risk-store.svelte.ts:26` | `GET /risk/{profile}/cvar/history` | Risk page via store | CANONICAL_AND_CONSUMED | Store-local |
| `DriftAlert` | `risk-store.svelte.ts:31` | `GET /analytics/strategy-drift/alerts` | Risk page via store | CANONICAL_AND_CONSUMED | Store-local |
| `BehaviorAlert` | `risk-store.svelte.ts:37` | — | Risk page via store | CANONICAL_AND_CONSUMED | Store-local |
| `StoreStatus` | `risk-store.svelte.ts:13` | — | Layout + all risk consumers | CANONICAL_AND_CONSUMED | `"loading" | "ready" | "error" | "stale"` |
| `RiskStoreState` | `risk-store.svelte.ts:51` | — | Context consumers | CANONICAL_AND_CONSUMED | Composite |
| `RiskStoreConfig` | `risk-store.svelte.ts:66` | — | Layout initialization | CANONICAL_AND_CONSUMED | |
| Risk SSE event shape | — | `GET /risk/stream` (SSE) | — | MISSING | Disconnected endpoint — no SSE event type defined |
| Drift scan trigger | — | `POST /analytics/strategy-drift/scan` | — | MISSING | Disconnected endpoint |
| Instrument drift detail | — | `GET /analytics/strategy-drift/{instrument_id}` | — | MISSING | Disconnected endpoint |

### Content types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| `ContentSummary` | `wealth/src/lib/types/api.ts:13` | `GET /content` | Content page | CANONICAL_AND_CONSUMED | |
| Content generation request | — | `POST /content/outlooks`, `flash-reports`, `spotlights` | — | MISSING | 3 disconnected endpoints |
| Content approve request | — | `POST /content/{content_id}/approve` | — | MISSING | Disconnected endpoint |
| Content download | — | `GET /content/{content_id}/download` | — | MISSING | Disconnected endpoint |

### Macro types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| `MacroScores` | `wealth/src/lib/types/api.ts:25` | `GET /macro/scores` | Macro Intelligence page | CANONICAL_AND_CONSUMED | |
| `RegimeHierarchy` | `wealth/src/lib/types/api.ts:30` | `GET /macro/regime` | Macro Intelligence page | CANONICAL_AND_CONSUMED | |
| `MacroReview` | `wealth/src/lib/types/api.ts:35` | `GET /macro/reviews` | Macro Intelligence page | CANONICAL_AND_CONSUMED | |
| Macro review generate | — | `POST /macro/reviews/generate` | — | MISSING | Disconnected endpoint |
| Macro review approve/reject | — | `PATCH /macro/reviews/{review_id}/approve|reject` | — | MISSING | Disconnected endpoints |

### Instrument types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| `Instrument` | `wealth/src/lib/types/api.ts:44` | `GET /instruments` | Instruments page | CANONICAL_AND_CONSUMED | Used via cast: `as unknown as Instrument` in DataTable row click |
| Instrument create/sync | — | `POST /instruments`, `POST /instruments/bulk-sync` | — | MISSING | Disconnected endpoints |
| Instrument search | — | `POST /instruments/search-external` | — | MISSING | Disconnected endpoint |

### DD Report types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| `DDReportSummary` | `wealth/src/lib/types/api.ts:56` | `GET /dd-reports/funds/{fund_id}` | DD Reports list page | CANONICAL_AND_CONSUMED | |
| `DDReportChapter` | `wealth/src/lib/types/api.ts:63` | `GET /dd-reports/{report_id}/stream` (SSE) | FundDetailPanel | CANONICAL_AND_CONSUMED | |
| DD report full detail | — | `GET /dd-reports/{report_id}` | `dd-reports/[fundId]/[reportId]/+page.server.ts` | PHANTOM_CONSUMER | Loader fetches but casts to `Record<string, unknown>` |
| DD report generate | — | `POST /dd-reports/funds/{fund_id}` | — | MISSING | Disconnected endpoint |
| DD report regenerate | — | `POST /dd-reports/{report_id}/regenerate` | — | MISSING | Disconnected endpoint |

### Fund types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| `FundDetail` | `wealth/src/lib/types/api.ts:72` | `GET /funds/{fund_id}` | Fund detail page | CANONICAL_AND_CONSUMED | |
| Fund stats response | — | `GET /funds/{fund_id}/stats` | `funds/[fundId]/+page.server.ts` | PHANTOM_CONSUMER | Fetched, untyped, result discarded on error |
| Fund performance response | — | `GET /funds/{fund_id}/performance` | `funds/[fundId]/+page.server.ts` | PHANTOM_CONSUMER | Fetched, untyped |
| Fund holdings response | — | `GET /funds/{fund_id}/holdings` | `funds/[fundId]/+page.server.ts` | PHANTOM_CONSUMER | Fetched, untyped |

### Portfolio / Rebalance types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| Portfolio detail response | — | `GET /portfolios/{profile}` | `portfolios/[profile]/+page.server.ts` | PHANTOM_CONSUMER | Fetched, untyped |
| Portfolio snapshot | — | `GET /portfolios/{profile}/snapshot` | `portfolios/[profile]/+page.server.ts` | PHANTOM_CONSUMER | Fetched, untyped |
| Portfolio history | — | `GET /portfolios/{profile}/history` | `portfolios/[profile]/+page.server.ts` | PHANTOM_CONSUMER | Fetched, untyped |
| Rebalance trigger/approve/execute | — | `POST .../rebalance`, `approve`, `execute` | — | MISSING | 3 disconnected endpoints |
| Rebalance event detail | — | `GET .../rebalance/{event_id}` | — | MISSING | Disconnected endpoint |

### Allocation types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| Strategic/tactical/effective response | — | `GET /allocation/{profile}/strategic|tactical|effective` | Allocation page | PHANTOM_CONSUMER | Fetched, untyped, null fallback |
| Allocation write request | — | `PUT /allocation/{profile}/strategic|tactical` | — | MISSING | Disconnected endpoints |

### Analytics types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| Correlation response | — | `GET /analytics/correlation` | Analytics page | PHANTOM_CONSUMER | Fetched, untyped |
| Correlation-regime response | — | `GET /analytics/correlation-regime/{profile}` | Analytics page | PHANTOM_CONSUMER | Fetched, untyped |
| Backtest request/response | — | `POST /analytics/backtest`, `GET .../backtest/{run_id}` | — | MISSING | Disconnected endpoints |
| Optimization request | — | `POST /analytics/optimize`, `optimize/pareto` | — | MISSING | Disconnected endpoints |
| Attribution response | — | `GET /analytics/attribution/funds/{fund_id}/period` | — | MISSING | Disconnected endpoint |

### Screener types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| Screener run/results response | — | `POST /screener/run`, `GET /screener/runs`, `GET /screener/results` | Screener page | PHANTOM_CONSUMER | Fetched but untyped |
| Screener run detail | — | `GET /screener/runs/{run_id}` | — | MISSING | Disconnected endpoint |
| Instrument screening history | — | `GET /screener/results/{instrument_id}` | — | MISSING | Disconnected endpoint |

### Exposure types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| Exposure matrix/metadata | — | `GET /wealth/exposure/matrix`, `metadata` | Exposure page | PHANTOM_CONSUMER | Fetched, untyped |

### Model Portfolio types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| Model portfolio list/detail | — | `GET /model-portfolios`, `GET /model-portfolios/{id}` | Model Portfolios page | PHANTOM_CONSUMER | Fetched, untyped |
| Track record response | — | `GET /model-portfolios/{id}/track-record` | Model Portfolio detail | PHANTOM_CONSUMER | Fetched, untyped |
| Model portfolio create | — | `POST /model-portfolios` | — | MISSING | Disconnected endpoint |
| Model portfolio actions | — | `validate`, `backtest`, `allocate`, `rebalance` | — | MISSING | 4 disconnected endpoints |

### Fact Sheet types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| Fact sheet response | — | `GET /fact-sheets/model-portfolios/{portfolio_id}` | Investor fact-sheets page | PHANTOM_CONSUMER | Fetched, cast to `Record<string, unknown>[]` |
| Fact sheet generate/download | — | `POST .../fact-sheets/...`, `GET .../download` | — | MISSING | Disconnected endpoints |

---

## 5. Domain Inventory: Admin

### Health types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| `ServiceHealth` | `admin/src/lib/types.ts:3` | `GET /admin/health/services` | Health page | CANONICAL_AND_CONSUMED | |
| `WorkerStatus` | `admin/src/lib/types.ts:10` | `GET /admin/health/workers` | Health page | CANONICAL_AND_CONSUMED | |
| Pipeline stats response | — | `GET /admin/health/pipelines` | Health page | PARTIAL_OR_DRIFTING | Fetched but typed inline in loader, not shared |
| Worker log SSE event | — | `GET /admin/health/workers/logs` (SSE) | `WorkerLogFeed.svelte` | PARTIAL_OR_DRIFTING | `JSON.parse(raw) as unknown` — no typed event envelope |

### Tenant types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| `TenantListItem` | `admin/src/lib/types.ts:18` | `GET /admin/tenants/` | Tenants list page | PARTIAL_OR_DRIFTING | Type defined but loader uses `Record<string, unknown>[]` instead |
| `TenantDetail` | `admin/src/lib/types.ts:28` | `GET /admin/tenants/{org_id}` | Tenant detail layout | PARTIAL_OR_DRIFTING | Type defined but loader uses `let tenant = null` — untyped |
| `TenantAsset` | `admin/src/lib/types.ts:36` | — | `TenantDetail.assets` | CANONICAL_BUT_UNUSED | No direct consumer verified beyond TenantDetail |
| Tenant create request | — | `POST /admin/tenants/` | — | MISSING | Disconnected endpoint |
| Tenant update request | — | `PATCH /admin/tenants/{org_id}` | — | MISSING | Disconnected endpoint |
| Tenant seed request | — | `POST /admin/tenants/{org_id}/seed` | — | MISSING | Disconnected endpoint |
| Tenant asset upload | — | `POST /admin/tenants/{org_id}/assets` | Branding page (upload) | PARTIAL_OR_DRIFTING | Upload via `FormData` — no typed response |
| Tenant asset delete | — | `DELETE /admin/tenants/{org_id}/assets/{asset_type}` | — | MISSING | Disconnected endpoint |

### Config types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| `ConfigListItem` | `admin/src/lib/types.ts:45` | `GET /admin/configs/` | Config list page | PARTIAL_OR_DRIFTING | Type exists but loader casts to `as any[]` |
| `ConfigDiff` | `admin/src/lib/types.ts:53` | `GET /admin/configs/{vertical}/{config_type}/diff` | ConfigDiffViewer | CANONICAL_AND_CONSUMED | Contains `Record<string, unknown>` fields — intentionally generic for JSON configs |
| Config save request | — | `PUT /admin/configs/{vertical}/{config_type}` | — | MISSING | ConfigEditor reads and validates but does NOT save (critical gap per audit) |
| Config delete request | — | `DELETE /admin/configs/{vertical}/{config_type}` | — | MISSING | Disconnected endpoint |
| Config validate request | — | `POST /admin/configs/validate` | ConfigEditor | PARTIAL_OR_DRIFTING | Endpoint called but request/response shape not typed |
| Invalid configs response | — | `GET /admin/configs/invalid` | Health page loader | PARTIAL_OR_DRIFTING | Fetched but cast to `as any[]` |

### Prompt types
| Type | Source | Endpoint(s) | Consumer(s) | Classification | Notes |
|---|---|---|---|---|---|
| `PromptListItem` | `admin/src/lib/types.ts:60` | `GET /admin/prompts/{vertical}` | Prompts list page | PARTIAL_OR_DRIFTING | Type exists but loader uses `unknown[]` |
| `PromptDetail` | `admin/src/lib/types.ts:68` | `GET /admin/prompts/{vertical}/{name}` | PromptEditor | CANONICAL_AND_CONSUMED | |
| `PromptPreviewResponse` | `admin/src/lib/types.ts:75` | `POST /admin/prompts/{vertical}/{name}/preview` | PromptEditor | CANONICAL_AND_CONSUMED | |
| Prompt save request | — | `PUT /admin/prompts/{vertical}/{name}` | PromptEditor | MISSING | Endpoint called but no request type |
| Prompt revert request | — | `DELETE /admin/prompts/{vertical}/{name}` | PromptEditor | MISSING | Endpoint called but no request type |
| Prompt version history | — | `GET .../versions` | — | MISSING | Disconnected endpoint |
| Prompt revert to version | — | `POST .../revert/{version}` | — | MISSING | Disconnected endpoint |

---

## 6. Shared / Cross-Domain Type Inventory

### Actor / Scope
| Type | Source | Consumer(s) | Classification | Notes |
|---|---|---|---|---|
| `Actor` | `packages/ui/src/lib/utils/auth.ts:12` | All frontends via `locals.actor` | CANONICAL_AND_CONSUMED | `role` is `string` not union — no type safety on role checks |
| `organization_id` | Part of `Actor` | All RLS-scoped API calls | CANONICAL_AND_CONSUMED | Passed via JWT, not form field |
| `BrandingConfig` | `packages/ui/src/lib/utils/types.ts` | All frontends root layout | CANONICAL_AND_CONSUMED | 28 properties — color tokens, fonts, logos, org metadata |

### Audit / History
| Type | Source | Consumer(s) | Classification | Notes |
|---|---|---|---|---|
| `AuditTrailEntry` | `packages/ui/src/lib/components/AuditTrailPanel.svelte` | Credit deal page, planned for Wealth/Admin | CANONICAL_AND_CONSUMED | Missing `actorCapacity`, `actorEmail`, `immutable`, `sourceSystem` per remediation plan |
| `AuditTrailFieldChange` | Same file | AuditTrailPanel internal | CANONICAL_AND_CONSUMED | |
| `AuditTrailStatus` | Same file | AuditTrailPanel internal | CANONICAL_AND_CONSUMED | `"success" | "warning" | "error" | "info" | "pending"` |

### Status / Stage
| Type | Source | Consumer(s) | Classification | Notes |
|---|---|---|---|---|
| `DealStage` | `credit/src/lib/types/api.ts:44` | Credit pipeline/deal pages | CANONICAL_AND_CONSUMED | 8-variant union |
| `DealType` / `AssetType` | `credit/src/lib/types/api.ts:42,162` | Credit deal/portfolio | PARTIAL_OR_DRIFTING | **Duplicated** — same 4 values defined as two separate types |
| `ObligationStatus` | `credit/src/lib/types/api.ts:165` | Credit portfolio | CANONICAL_AND_CONSUMED | 4-variant union |
| `ActionStatus` | `credit/src/lib/types/api.ts:166` | Credit portfolio | CANONICAL_AND_CONSUMED | 3-variant union |
| `ReportPack.status` | `credit/src/lib/types/api.ts:270` | Credit reporting | CANONICAL_AND_CONSUMED | Inline union: `"DRAFT" | "GENERATED" | "PUBLISHED"` |
| `ServiceHealth.status` | `admin/src/lib/types.ts:5` | Admin health | CANONICAL_AND_CONSUMED | `"ok" | "degraded" | "down"` |
| `PromptListItem.source_level` | `admin/src/lib/types.ts:63` | Admin prompts | CANONICAL_AND_CONSUMED | `"org" | "global" | "filesystem"` |
| `StoreStatus` | `risk-store.svelte.ts:13` | Wealth risk consumers | CANONICAL_AND_CONSUMED | `"loading" | "ready" | "error" | "stale"` |
| No shared cross-domain status type | — | — | MISSING | Each domain defines its own status values; no shared `StatusConfig` type exists yet |

### Formatting-Sensitive Fields
| Field pattern | Where used | Notes |
|---|---|---|
| `total_aum: string \| null` | `PortfolioSummary` | String representation — frontend must parse for formatting |
| `amount: string \| null` | `DealDetail` | Same |
| `total_nav: string` | `NavSnapshot` | Same |
| `cvar_current: number \| null` | `CVaRStatus` | Numeric — uses shared formatters |
| `confidence: number \| null` | `RegimeData` | Numeric |
| `last_price: number \| null` | `Instrument` | Numeric |
| Various `*_at: string` timestamps | All types | ISO 8601 strings — require `formatDate`/`formatDateTime` |

### Job / Progress / SSE / Live Updates
| Type | Source | Consumer(s) | Classification | Notes |
|---|---|---|---|---|
| `SSEStatus` | `packages/ui/src/lib/utils/sse-client.svelte.ts` | Risk store, WorkerLogFeed | CANONICAL_AND_CONSUMED | `"connecting" | "connected" | "disconnected" | "error"` |
| `SSEEvent` | Same file | SSE consumers | CANONICAL_AND_CONSUMED | `{ type?: string; data: unknown }` — data is untyped |
| `SSEConfig<T>` | Same file | SSE consumers | CANONICAL_AND_CONSUMED | Generic config for typed SSE streams |
| `SSEConnection<T>` | Same file | SSE consumers | CANONICAL_AND_CONSUMED | Reactive connection handle |
| `SSESnapshotConfig<T>` | Same file | Risk store | CANONICAL_AND_CONSUMED | Subscribe-then-snapshot pattern |
| `PollerConfig<T>` / `PollerState<T>` | `packages/ui/src/lib/utils/poller.svelte.ts` | Risk store fallback | CANONICAL_AND_CONSUMED | |
| `WealthAlert` | `packages/ui/src/lib/components/AlertFeed.svelte` | Dashboard alert feed | CANONICAL_AND_CONSUMED | 5-variant discriminated union — well-typed |
| `ConsequenceDialogPayload` | `packages/ui/src/lib/components/ConsequenceDialog.svelte` | Mutation confirmation flows | CANONICAL_AND_CONSUMED | |
| IC memo generation SSE | `GET /jobs/{job_id}/stream` | ICMemoViewer | PARTIAL_OR_DRIFTING | SSE endpoint connected but event payload shape not typed |
| DD report generation SSE | `GET /dd-reports/{report_id}/stream` | FundDetailPanel | PARTIAL_OR_DRIFTING | SSE connected but event payload shape not typed |
| Risk live alerts SSE | `GET /risk/stream` | — | MISSING | Disconnected endpoint |
| Worker log SSE | `GET /admin/health/workers/logs` | WorkerLogFeed | PARTIAL_OR_DRIFTING | Connected but `JSON.parse(raw) as unknown` |

### Freshness / Timestamp Contracts
| Contract | Status | Notes |
|---|---|---|
| `computed_at` field in risk responses | MISSING | Remediation plan requires this but backend does not expose it yet |
| `next_expected_update` field | MISSING | Required by plan for holiday-aware freshness |
| `checked_at` in admin health responses | MISSING | Required by plan for health freshness |
| `created_at` / `updated_at` in most types | CANONICAL_AND_CONSUMED | ISO 8601 strings present across Credit/Admin types |

### Mutation Payload Types
| Type | Source | Consumer(s) | Classification | Notes |
|---|---|---|---|---|
| `ConsequenceDialogPayload` | `packages/ui/src/lib/components/ConsequenceDialog.svelte` | IC decision, review decision flows | CANONICAL_AND_CONSUMED | `{ rationale?: string; typedConfirmation?: string }` |
| No shared mutation request type | — | — | MISSING | Each mutation call uses inline `{ key: value }` — no typed request payloads |

### Error Types
| Type | Source | Consumer(s) | Classification | Notes |
|---|---|---|---|---|
| `AuthError` | `api-client.ts` | All frontends | CANONICAL_AND_CONSUMED | 401 |
| `ForbiddenError` | `api-client.ts` | All frontends | CANONICAL_AND_CONSUMED | 403 |
| `ValidationError` | `api-client.ts` | All frontends | CANONICAL_AND_CONSUMED | 422, `details: unknown` |
| `ConflictError` | `api-client.ts` | All frontends | CANONICAL_AND_CONSUMED | 409, `currentVersion?: number` |
| `ServerError` | `api-client.ts` | All frontends | CANONICAL_AND_CONSUMED | 5xx |

---

## 7. Missing or Weak Type Coverage

### Backend endpoints with no safe frontend-usable type coverage

**Credit (critical):**
- `POST /funds/{fund_id}/deals` — deal create (no request type)
- `PATCH /funds/{fund_id}/deals/{deal_id}/decision` — deal decision (no request type)
- `POST /funds/{fund_id}/deals/{deal_id}/convert` — deal conversion (no request type)
- `PATCH /funds/{fund_id}/deals/{deal_id}/ic-memo/conditions` — IC condition resolve (no request type)
- All 5 document review action endpoints (assign, finalize, resubmit, ai-analyze, checklist toggle)
- `POST /documents/upload` — alternative upload (no type)
- Evidence upload/complete endpoints (no types)

**Wealth (critical):**
- All 7 rebalance endpoints (trigger, approve, execute, detail)
- All 3 macro committee action endpoints (generate, approve, reject)
- All 4 analytics endpoints (backtest, optimize, optimize/pareto, backtest results)
- All 5 content generation endpoints (outlooks, flash-reports, spotlights, approve, download)
- All 5 instrument management endpoints
- Allocation write endpoints (`PUT strategic`, `PUT tactical`)
- All 4 model portfolio action endpoints
- Risk SSE stream event shape

**Admin:**
- All 5 tenant management write endpoints (create, edit, seed, asset upload, asset delete)
- Config save endpoint (`PUT /admin/configs/{vertical}/{config_type}`)
- Config delete endpoint
- Default update endpoint
- Prompt version history and revert endpoints

### Endpoints with partial request or response typing only
- `POST /admin/configs/validate` — called but request/response shapes not typed
- `PUT /admin/prompts/{vertical}/{name}` — called but no request type
- `POST /ai/answer` — response partially typed (citations as `unknown[]`)
- `POST /funds/{fund_id}/report-packs` — called but response not typed

### Areas using `any`/`unknown`/casts/manual shaping
| Pattern | Location(s) | Risk |
|---|---|---|
| `as any[]` | `admin/config/[vertical]/+page.server.ts:12-13` | Config and invalid-config lists bypass type safety |
| `as any` | `admin/health/+page.svelte:103` | DataTable column definition |
| `as any` | `admin/components/WorkerLogFeed.svelte:166` | SSE event construction |
| `as unknown as Instrument` | `wealth/instruments/+page.svelte:195` | DataTable row callback |
| `as unknown[]` | `credit/CopilotChat.svelte:38`, `credit/dashboard/+page.svelte:95` | Citation list, FRED observations |
| `Record<string, unknown>` as response type | 8 loader files across Credit/Wealth/Admin | Bypasses type safety for list/detail responses |
| `Record<string, unknown>` in type definitions | `ICMemoDetail.condition_history`, `VotingStatusDetail.conditionHistory`, `ConfigDiff.*`, `RiskStoreState.macroIndicators` | Weak subtype within otherwise typed structures |

### Areas where frontend language derives from raw backend enum leakage
- Credit `DealStage`, `DealType`, `RejectionCode` — raw SCREAMING_SNAKE values rendered to UI
- Wealth `ContentSummary.content_type`, `MacroReview.status` — raw string, no label mapping
- Admin `WorkerStatus.status`, `ConfigListItem.vertical` — raw strings in tables
- No domain-specific status-to-label mappers exist anywhere (planned in remediation plan §2.3)

---

## 8. Duplicated or Competing Types

| Concept | Definition 1 | Definition 2 | Risk |
|---|---|---|---|
| `RegimeData` | `wealth/src/lib/types/api.ts:5` | `wealth/src/lib/stores/risk-store.svelte.ts:45` | **Identical** — maintainability risk; one update misses the other |
| `DealType` vs `AssetType` | `credit/src/lib/types/api.ts:42` | `credit/src/lib/types/api.ts:162` | **Same 4 values** — semantic duplication; `DIRECT_LOAN | FUND_INVESTMENT | EQUITY_STAKE | SPV_NOTE` |
| `VotingStatus` vs `VotingStatusDetail` | `credit/src/lib/types/api.ts:289` | `credit/src/lib/types/api.ts:124` | Competing — `VotingStatus` is simplified version, `VotingStatusDetail` is full; `VotingStatus` appears unused |
| `ICMemo` vs `ICMemoDetail` | `credit/src/lib/types/api.ts:277` | `credit/src/lib/types/api.ts:100` | `ICMemo` for generation response, `ICMemoDetail` for read — valid separation but naming is confusing |
| Fund interface | Inline in `credit/funds/+page.server.ts` | `wealth/src/lib/types/api.ts:72` (`FundDetail`) | Credit defines `Fund` inline with `{ id, name, status }` only — diverges from Wealth's full `FundDetail` |
| Health inline types | Inline in `admin/health/+page.server.ts` | `admin/src/lib/types.ts` | Loader defines `ServiceHealthRow`, `WorkerStatusRow` inline but `ServiceHealth`, `WorkerStatus` exist in types file |

---

## 9. Phantom Calls and Contract Mismatches

### Phantom calls identified in endpoint_coverage_audit.md
| Frontend | Call | File | Backend Status | Type Status |
|---|---|---|---|---|
| Wealth | `GET /funds/{fundId}/risk` | `funds/[fundId]/+page.server.ts` | **No backend endpoint** | No type. **NOT FOUND** in current code — may have been cleaned up since audit |
| Wealth | `GET /funds/{fundId}/nav` | `funds/[fundId]/+page.server.ts` | **No backend endpoint** | No type. **NOT FOUND** in current code — may have been cleaned up since audit |

### Consumers operating without valid contracts
| Consumer | Call pattern | Issue |
|---|---|---|
| Wealth fund detail loader | `api.get(\`/funds/${fundId}/stats\`)` | Endpoint exists (`GET /funds/{fund_id}/stats`) but no response type — data arrives untyped |
| Wealth fund detail loader | `api.get(\`/funds/${fundId}/performance\`)` | Same — endpoint exists, no type |
| Wealth fund detail loader | `api.get(\`/funds/${fundId}/holdings\`)` | Same |
| Wealth portfolio profile loader | `api.get(\`/portfolios/${profile}\`)`, `snapshot`, `history` | 3 endpoints exist, no response types |
| Wealth allocation loader | 3 allocation endpoints | Connected endpoints, no response types |
| Wealth analytics loader | `correlation`, `correlation-regime` | Connected endpoints, no response types |
| Wealth screener loader | `screener/run`, `screener/runs`, `screener/results` | Connected endpoints, no response types |
| Wealth exposure loader | `exposure/matrix`, `exposure/metadata` | Connected endpoints, no response types |
| Wealth model portfolios loader | `model-portfolios`, detail, track-record | Connected endpoints, no response types |
| Credit investor portal | 3 investor endpoints | Connected but typed as `Record<string, unknown>[]` |
| Credit document detail | `GET /documents/{document_id}` | Connected but cast to `Record<string, unknown>` |
| Admin tenants loader | `GET /admin/tenants/` | Connected but typed as `Record<string, unknown>[]` instead of `TenantListItem[]` |
| Admin tenant detail | `GET /admin/tenants/{org_id}` | Connected but `let tenant = null` — untyped |

### Calls likely masked by Promise.allSettled
All multi-fetch loaders use `Promise.allSettled` with null/empty fallbacks. This means:
- Individual endpoint failures are silently swallowed
- Type mismatches produce null data without error
- Missing endpoints return null indistinguishable from genuinely empty data
- This is architecturally intentional (graceful degradation) but creates false confidence about data availability

---

## 10. Plan Readiness Map

Cross-referencing type readiness against `docs/plans/ux-remediation-plan.md` workstreams:

### Section 1: Immediate Risk Blocks

| Task | Type Readiness | Status |
|---|---|---|
| 1. Credit IC decision governance | PARTIALLY_READY | `ConsequenceDialogPayload`, `AuditTrailEntry` exist. **BLOCKED**: No mutation request types for `PATCH /decision`, `POST /convert`, `PATCH /conditions`. Backend must define payloads accepting rationale + actor metadata, then `make types`. |
| 2. Wealth freshness/state integrity | BLOCKED_BY_TYPES | `RiskStoreState` exists but `computed_at`, `next_expected_update` fields missing from all backend responses. No `ConnectionQuality` or `FreshnessLevel` types yet. |
| 3. Wealth drift-history | BLOCKED_BY_TYPES | `DriftAlert` exists in store but drift-history endpoint types missing. No typed event table row, period filter, or export response type. |
| 4. Admin change governance | PARTIALLY_READY | `ConfigDiff`, `ConsequenceDialogPayload` exist. **BLOCKED**: Config save (`PUT`) has no request type. Impact count and mutation history response types missing. |
| 5. Admin tenant scope clarity | READY | `TenantDetail`, `Actor`, `BrandingConfig` sufficient. `EntityContextHeader` is frontend-only. |

### Section 2: Shared Primitive Backlog

| Task | Type Readiness | Status |
|---|---|---|
| 1. AuditTrailPanel enhance | READY | `AuditTrailEntry` exists; enhancement adds fields (`actorCapacity`, `actorEmail`, `immutable`, `sourceSystem`) — frontend-only type change. |
| 2. ConsequenceDialog enhance | READY | `ConsequenceDialogPayload` exists; AlertDialog migration is frontend-only. |
| 3. StatusBadge domain-mapper | READY | Frontend-only — creates new `StatusConfig` type and domain maps. No backend dependency. |
| 4. Shared formatting layer | READY | `format.ts` already has cached formatters. Enhancement and ESLint enforcement are frontend-only. |
| 5. CodeEditor (admin-local) | READY | No type dependency — CodeMirror is local. |
| 6. EntityContextHeader | READY | Consumes existing `TenantDetail` / `Actor` / `BrandingConfig`. |
| 7. LongRunningAction | PARTIALLY_READY | `SSEConfig<T>`, `SSEConnection<T>` exist. Need typed job-progress event payloads from backend SSE streams. |
| 8. DataTable hardening | READY | Frontend-only enhancement. |
| 9. Optimistic mutation utility | READY | Frontend-only pattern. |

### Section 3: Domain Remediation Backlog

| Task | Type Readiness | Status |
|---|---|---|
| Credit 1: IC decision workflow | BLOCKED_BY_TYPES | Decision + conversion + condition mutation payloads missing |
| Credit 2: Document review governance | BLOCKED_BY_TYPES | Review decision payload missing; checklist toggle types missing |
| Credit 3: Data-contract expansion | BLOCKED_BY_TYPES | Tenor, basis, covenant, collateral fields not in `DealDetail` |
| Credit 4: Dashboard/pipeline reconstruction | READY | Read types sufficient; layout changes are frontend-only |
| Credit 5: Document lineage/AI provenance | BLOCKED_BY_TYPES | Classification, AI provenance, timeline types missing |
| Credit 6: Domain-language/formatting | READY | Frontend-only status mapping + formatter adoption |
| Credit 7: Memo/reporting workflow | PARTIALLY_READY | `ICMemoDetail`, `ReportPack` exist. Missing: memo reviewer metadata, report generation progress event type |
| Wealth 1: Live-risk state spine | BLOCKED_BY_TYPES | `computed_at`, `next_expected_update`, batched risk endpoint missing |
| Wealth 2: Drift-history workbench | BLOCKED_BY_TYPES | Drift history endpoint types missing |
| Wealth 3: Allocation editor governance | BLOCKED_BY_TYPES | Simulation endpoint, approval state, allocation write request types missing |
| Wealth 4: Backtest/Pareto | BLOCKED_BY_TYPES | Backtest request/response types missing |
| Wealth 5: Dashboard decision surface | PARTIALLY_READY | Some read types exist; needs `computed_at` for freshness |
| Wealth 6: Portfolio detail workbench | BLOCKED_BY_TYPES | Portfolio detail, snapshot, rebalance types untyped |
| Wealth 7: Domain-language/charts | READY | Frontend-only status mapping + formatter + chart fixes |
| Admin 1: Config editing | BLOCKED_BY_TYPES | Config save request type, impact count response, mutation history type missing |
| Admin 2: Tenant identity/scope | READY | Existing types sufficient |
| Admin 3: Health degraded-state | PARTIALLY_READY | `ServiceHealth` exists. `checked_at` field missing from response |
| Admin 4: Worker monitor upgrade | PARTIALLY_READY | `WorkerStatus` exists. Worker log SSE event type missing |
| Admin 5: Tenant IA completion | PARTIALLY_READY | Tenant types exist but CRUD request types missing |
| Admin 6: Prompt editing | PARTIALLY_READY | `PromptDetail`, `PromptPreviewResponse` exist. Version history type missing |
| Admin 7: Formatting/tokens | READY | Frontend-only |

### Summary
| Status | Count | % |
|---|---|---|
| READY | 14 | 40% |
| PARTIALLY_READY | 9 | 26% |
| BLOCKED_BY_TYPES | 12 | 34% |

---

## 11. High-Risk Findings

1. **OpenAPI type generation is non-functional.** `api.d.ts` is an empty stub. The `make types` pipeline exists but has never been run against a live backend. All 186 endpoints lack auto-generated TypeScript types. This is the single largest type-layer risk — every hand-written type could drift from the backend schema silently.

2. **12 remediation tasks are BLOCKED_BY_TYPES.** These represent the majority of critical/high-severity work in the remediation plan. No frontend implementation can safely begin until backend contracts are defined and `make types` is run.

3. **Wealth frontend has 15+ PHANTOM_CONSUMER endpoints.** These are loaders that fetch real endpoints but receive completely untyped data (`null` fallback). Any shape change on the backend will silently produce null data in the UI. Affected: fund stats/performance/holdings, portfolio detail/snapshot/history, allocation (3 endpoints), analytics (2), screener (3), exposure (2), model portfolios (3).

4. **`Record<string, unknown>` used as response type in 8 loader files.** This pattern defeats TypeScript's type safety entirely. Affected: investor documents/report-packs/statements (Credit), deal detail, document detail, DD report detail, investor reports/documents (Wealth), fact-sheets.

5. **Admin loaders don't use their own defined types.** `TenantListItem` and `TenantDetail` types exist in `admin/src/lib/types.ts` but the actual loaders use `Record<string, unknown>[]` or `null`. The types provide false confidence.

6. **`DealType` and `AssetType` are semantic duplicates.** Both define `DIRECT_LOAN | FUND_INVESTMENT | EQUITY_STAKE | SPV_NOTE`. If the backend changes one, the other will silently diverge.

7. **`RegimeData` is duplicated** across `wealth/src/lib/types/api.ts` and `wealth/src/lib/stores/risk-store.svelte.ts`. Both must be updated together.

8. **No mutation request types exist anywhere.** All POST/PUT/PATCH/DELETE calls use inline `{ key: value }` objects. There is no compile-time validation that request payloads match backend expectations.

9. **SSE event payloads are untyped.** IC memo generation, DD report generation, worker logs, and risk stream all use SSE but none have typed event schemas. The `SSEEvent.data` field is `unknown`.

10. **`computed_at` and `next_expected_update` don't exist in any backend response.** The remediation plan's freshness architecture depends entirely on these fields, which are not yet exposed.

---

## 12. Recommended Execution Preconditions

1. **Run `make types` against live backend** to populate `packages/ui/src/types/api.d.ts`. This is the prerequisite for all type-dependent remediation work.

2. **Wire admin loaders to use existing types.** Replace `Record<string, unknown>[]` with `TenantListItem[]` in `tenants/+page.server.ts`; replace `as any[]` with `ConfigListItem[]` in config loader. Zero backend change required.

3. **Wire credit loaders to use existing types.** Replace `Record<string, unknown>` cast in `pipeline/[dealId]/+page.server.ts` with `DealDetail`. Same for document detail loader.

4. **Unify `RegimeData` to single source.** Remove duplicate from `risk-store.svelte.ts`; import from `wealth/src/lib/types/api.ts`.

5. **Unify `DealType`/`AssetType`.** Keep one, alias the other.

6. **Add Wealth response types for connected endpoints.** At minimum: portfolio detail/snapshot/history, allocation strategic/tactical/effective, screener results/runs, exposure matrix/metadata, model portfolio list/detail/track-record, analytics correlation/correlation-regime. These loaders already call the endpoints — they just need types.

7. **Define mutation request types** for Sprint 1 critical paths: deal decision, deal convert, IC condition resolve, review decide, config save.

8. **Add `computed_at` field** to Wealth risk and macro endpoint responses before starting freshness remediation.

9. **Type SSE event payloads** for IC memo stream, DD report stream, and worker log stream.

10. **Remove `VotingStatus`** (unused simpler version) to avoid confusion with `VotingStatusDetail`.
