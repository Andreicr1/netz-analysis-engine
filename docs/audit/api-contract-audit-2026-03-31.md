# API Contract Audit — 2026-03-31

**Baseline:** `docs/audit/endpoint_coverage_audit.md` (2026-03-27)
**Scope:** Wealth frontend — incremental since baseline + production errors
**Branch:** `main`

---

## Erros Confirmados em Produção

| Erro | Endpoint | Causa raiz | Fix |
|---|---|---|---|
| 404 | `POST /screener/import/EISAX` | `import_sec_security` only searches `sec_cusip_ticker_map` (equities/ETFs). Mutual fund tickers like EISAX are not in this table — they exist in `sec_fund_classes`. The function returns 404 before reaching fund enrichment logic. | Backend: add `sec_fund_classes` fallback lookup before 404 (synthetic row pattern). |
| 422 | `GET /sec/managers/897111/holdings?page=1&page_size=500` | Backend constraint `page_size: int = Query(50, ge=1, le=200)` rejects `page_size=500`. Frontend `SecHoldingsTable.svelte:33` sends `page_size: "500"` for virtual scroll. | Frontend: reduce `page_size` from 500 to 200 to match backend constraint. Component already handles partial results ("Showing X of Y"). |

---

## Novos Phantoms Identificados (pós 2026-03-23)

| Método | Path | Arquivo | Status |
|---|---|---|---|
| — | — | — | Nenhum novo phantom identificado. Todas as novas chamadas da API têm endpoints backend correspondentes. |

---

## Phantoms do Baseline Resolvidos

| Phantom (baseline) | Status |
|---|---|
| `POST /content/{param}{param}` | **Resolvido** — Content page reescrita. Agora chama corretamente `/content/flash-reports`, `/content/outlooks`, `/content/spotlights`, `/content/{id}/approve`. |
| `GET /wealth/exposure/matrix?dimension=...` (2x) | **Resolvido** — ExposureView.svelte usa query params inline no path. Endpoint existe e funciona. Falso positivo do scanner. |

---

## Phantoms do Baseline Ainda Ativos

| Método | Path | Arquivo | Prioridade |
|---|---|---|---|
| — | — | — | Nenhum phantom ativo restante. Os 3 phantom calls reais do baseline (content template + 2x exposure matrix) foram todos resolvidos. Os falsos positivos (21 `searchParams.get()`) permanecem como artefatos do scanner. |

---

## Endpoints Anteriormente Desconectados — Agora Conectados

Desde o baseline de 2026-03-27, as seguintes implementações conectaram endpoints que eram P1/P2/P3:

### P1 (Crítico) — Agora Conectados

| Endpoint | Componente/Página | Sprint |
|---|---|---|
| `POST /content/flash-reports` | `content/+page.svelte` — generateContent() | Content rewrite |
| `POST /content/outlooks` | `content/+page.svelte` — generateContent() | Content rewrite |
| `POST /content/spotlights` | `content/+page.svelte` — generateContent() | Content rewrite |
| `GET /content/{content_id}/download` | `content/+page.svelte` — via window.open link | Content rewrite |
| `GET /model-portfolios/{id}/views` | `[portfolioId]/+page.server.ts` — SSR loader | Portfolio Workbench |
| `POST /model-portfolios/{id}/stress-test` | `[portfolioId]/+page.svelte` — runCustomStress() | Portfolio Workbench |
| `POST /dd-reports/funds/{fund_id}` | `screener/+page.svelte`, `CatalogDetailPanel.svelte` | Screener redesign |
| `GET /dd-reports` (list) | `dd-reports/+page.server.ts` — SSR loader | DD Reports page |
| `POST /wealth/documents/upload-url` | `documents/upload/+page.svelte` — presigned URL flow | Document upload |
| `POST /wealth/documents/upload-complete` | `documents/upload/+page.svelte` — step 3 | Document upload |

### P2 (Valor) — Agora Conectados

| Endpoint | Componente/Página | Sprint |
|---|---|---|
| `GET /screener/catalog` | `screener/+page.server.ts` — SSR loader | Screener redesign |
| `GET /screener/catalog/facets` | `screener/+page.server.ts` — SSR loader | Screener redesign |
| `GET /analytics/entity/{entity_id}` | `entity-analytics/+page.server.ts` | Entity analytics page |

### P3 (Nice-to-Have) — Agora Conectados

| Endpoint | Componente/Página | Sprint |
|---|---|---|
| `GET /fact-sheets/{path}/download` | `[portfolioId]/+page.svelte` — api.getBlob() | Portfolio Workbench |
| `GET /portfolios/{profile}/rebalance` | `RebalancingTab.svelte` — via SSR data | Rebalancing tab |

---

## Novos Endpoints Conectados (não estavam no baseline)

| Método | Endpoint | Componente | Contexto |
|---|---|---|---|
| `GET` | `/model-portfolios/{id}/overlap` | `[portfolioId]/+page.server.ts` | Holdings overlap analysis |
| `POST` | `/model-portfolios/{id}/stress-test` | `[portfolioId]/+page.svelte` | Parametric stress scenario |
| `POST` | `/reporting/model-portfolios/{id}/long-form-report` | `LongFormReportPanel.svelte` | Long-form DD report SSE |
| `GET` | `/allocation/{profile}/effective` | `[profile]/+page.server.ts` | Effective allocation |
| `GET` | `/blended-benchmarks/blocks` | `[profile]/+page.server.ts` | Benchmark blocks |
| `GET` | `/sec/funds/{cik}` | `screener/[cik]/+page.server.ts` | Fund detail page |
| `GET` | `/sec/funds/{cik}/holdings` | `screener/[cik]/+page.server.ts` | N-PORT holdings |
| `GET` | `/sec/funds/{cik}/prospectus` | `screener/[cik]/+page.server.ts` | Prospectus data |
| `GET` | `/sec/funds/{cik}/peer-analysis` | `screener/[cik]/+page.server.ts` | Peer comparison |
| `GET` | `/sec/funds/{cik}/reverse-holdings` | `screener/[cik]/+page.server.ts` | Reverse CUSIP |
| `GET` | `/sec/funds/{cik}/holdings-history` | `screener/[cik]/+page.server.ts` | Ownership timeline |
| `GET` | `/sec/managers/{cik}` | `screener/+page.svelte` | Manager detail panel |
| `GET` | `/sec/managers/{crd}/funds` | `screener/+page.svelte` | Fund-type breakdown |
| `GET` | `/sec/holdings/reverse` | `SecHoldingsTable.svelte` | CUSIP popover |
| `GET` | `/sec/holdings/history` | `SecReverseLookup.svelte` | Quarterly history |
| `GET` | `/search` | `GlobalSearch.svelte` | Global search |
| `GET` | `/admin/configs/` | `settings/config/+page.server.ts` | Config management |
| `GET` | `/admin/health/services` | `settings/system/+page.server.ts` | System health |
| `GET` | `/admin/health/workers` | `settings/system/+page.server.ts` | Worker health |
| `GET` | `/admin/health/pipelines` | `settings/system/+page.server.ts` | Pipeline health |

---

## Endpoints de Alto Valor Ainda Desconectados (Wealth)

| Prioridade | Endpoint | Impacto |
|---|---|---|
| P1 | `DELETE /model-portfolios/{id}/views/{view_id}` | IC Views panel shows views but cannot delete them |
| P1 | `GET /dd-reports/{id}/stream` | SSE progress not connected — generation appears to hang |
| P2 | `POST /instruments/import/csv` | CSV bulk import missing from UI |
| P2 | `PATCH /instruments/{id}` | Edit instrument form missing |
| P2 | `POST /allocation/{profile}/simulate` | Allocation simulation button missing |
| P2 | `GET /macro/bis`, `/macro/imf`, `/macro/ofr`, `/macro/treasury` | Macro deep dive tabs missing |
| P3 | `GET /universe/funds/{id}/audit-trail` | Compliance audit trail |
| P3 | `GET /dd-reports/{id}/audit-trail` | Report audit trail |

---

## Cobertura Atualizada

| Métrica | Baseline (03-27) | Atual (03-31) | Delta |
|---|---|---|---|
| Total endpoints backend (Wealth) | 129 | ~135 | +6 novos endpoints |
| Conectados ao frontend | 73 (56.6%) | ~103 (76.3%) | **+30** |
| Desconectados | 56 (43.4%) | ~32 (23.7%) | -24 |
| Phantom calls reais | 3 | 0 | -3 |

Domínios com maiores ganhos: Screener/Catalog (25% → 80%), Content (20% → 80%), Model Portfolios (50% → 90%), DD Reports (43% → 70%).
