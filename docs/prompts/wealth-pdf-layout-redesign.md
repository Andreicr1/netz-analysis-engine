# Wealth PDF Layout Redesign — Diagnostic + Layout Brainstorm

## The Problem: These PDFs Are the Product's Storefront

Every analytical engine in the system — quant optimizer, macro committee, DD reports, fund screening, attribution — ultimately produces a PDF that lands on an investment committee's table. These PDFs **are** the product. A portfolio manager judges the entire platform by the quality of the document they hold in their hands.

Right now, every PDF the system produces looks like a first-semester university assignment rendered by a markdown parser. The fact sheet — supposedly the most polished document — is barely better. This is unacceptable for institutional finance.

---

## Current State: Evidence-Based Diagnostic

### I reviewed all 6 PDF types. Here's what's broken.

---

### 1. Fact Sheet — Institutional Renderer (`institutional_renderer.py`)

**What it looks like:** 5 pages. Cover page is 80% empty white space. Tables are functional but visually flat. Charts work but have English labels in PT mode.

**Problems:**

| Issue | Severity | Detail |
|-------|----------|--------|
| **Cover is empty** | Critical | Title, subtitle, meta, confidential — then 70% blank page. No logo, no branding block, no visual weight. Looks like the first page of a Word doc. |
| **No logo anywhere** | Critical | The logo infrastructure exists in `pdf_base.py` (`LOGO_NETZ`, `LOGO_NECKER`, `_logo_image()`) but the fact sheet renderers never use it on the cover. Only the IC memo cover (`build_ic_cover_story()`) uses logos. |
| **Section headings are Windows 95 toolbars** | High | Full-width dark navy bars (`NAVY_DEEP` bg, white text) with no padding refinement. They look like application menu bars, not institutional section dividers. No left accent, no subtle gradient, no serif contrast. |
| **Returns table: unlabeled rows** | High | Portfolio row and benchmark row have no row labels. Reader must guess which is which. |
| **Pie chart title hardcoded in English** | Medium | `render_allocation_pie()` defaults `title="Strategic Allocation"` — not i18n. Same for `render_nav_chart()` title. |
| **Block IDs rendered raw** | Medium | `us_equity` → "Us Equity" via `.replace("_", " ").title()`. Should use i18n map: "Renda Variável EUA" / "US Equity". |
| **Risk metrics: flat single-row table** | Medium | Sharpe, CVaR, Vol, Max DD as one table row with header. No visual hierarchy — should be KPI cards with large numbers and small labels. |
| **Fee table decimal precision** | Medium | Fee values are stored as decimals (0.0003) and displayed with `format_pct()` which shows "0.00%". Management fee of 0.03% shows as "0.00%". Need more decimal places or basis points. |
| **ESG placeholder section** | Low | "Dados ESG serão incorporados quando disponíveis" occupies a full section heading + body. Remove until there's real data — placeholder sections damage credibility. |
| **No two-column layouts** | Medium | Everything is single-column, top-to-bottom. No side-by-side KPIs, no chart+table pairs. Wastes horizontal space. |
| **Commentary is plain text** | Low | Manager commentary section has no visual treatment — just body text under a heading. Should have a quote-style container or callout box. |
| **No visual distinction executive vs institutional** | Medium | The executive renderer is just a shorter version of institutional. No layout difference, no density change. Executive should be a dashboard-style 1-pager; institutional should be a detailed report. |

---

### 2. Investment Outlook (`preview_investment_outlook_pt.pdf`)

**What it looks like:** 2 pages. Cover page with title, then raw markdown body text.

**Problems:**

| Issue | Severity | Detail |
|-------|----------|--------|
| **Raw `**bold**` markers in output** | Critical | `**América do Norte:**` renders literally as `**América do Norte:**` with asterisks visible. The markdown parser only handles `##` headings and line breaks — it does not process inline bold, italic, lists, or any other markdown. |
| **No structured data at all** | Critical | The engine gathers `macro_data` (regional scores, regime, global indicators) in `_gather_macro_data()` but throws it all away in `render_pdf()`. Only `content_md` (LLM prose) reaches the renderer. The macro dashboard, regional score table, and indicator KPIs that the prompt describes — all of this structured data exists in the system but is not passed to the renderer. |
| **Cover page 70% empty** | High | Same as fact sheet — title, orange rule, date, confidential. Rest blank. |
| **No logo** | High | Same. |
| **No quarter identification visual** | Medium | "Q2 2026" appears as subtitle text. Should be a prominent badge or sidebar element. |
| **Numbered lists render as raw text** | Medium | `1. Manter overweight...` renders as body paragraph starting with "1.". No list formatting. |

---

### 3. Long-Form Report (`preview_long_form_report_pt.pdf`)

**What it looks like:** 3 pages. Cover page, then 8 sections of raw body text.

**Problems:**

| Issue | Severity | Detail |
|-------|----------|--------|
| **Raw markdown everywhere** | Critical | Same as outlook — `**bold**`, `| table |`, lists, all rendered as plain text. |
| **No structured chapter data** | Critical | `LongFormReportResult` has `chapters[].content: dict` with structured data (allocation targets, Brinson decomposition, CVaR breakdown, fee drag). ALL of this is ignored — only `content_md` (LLM narrative) is rendered. This is the most data-rich document in the system, rendered as a wall of text. |
| **No table of contents** | High | 8 chapters, no navigation. |
| **No chapter-specific rendering** | High | `macro_context` chapter should have a regional score table. `performance_attribution` should have a Brinson table. `risk_decomposition` should have CVaR bars. Instead, everything is body paragraphs. |
| **Chapter confidence scores invisible** | Medium | `ChapterResult.confidence` exists but is never shown. |
| **Failed chapters silently omitted** | Medium | If a chapter fails, it just... doesn't appear. No indication to reader. |

---

### 4. Macro Committee Review (`preview_macro_committee_pt.pdf`)

**What it looks like:** 2 pages. Cover, then body text.

**Problems:**

| Issue | Severity | Detail |
|-------|----------|--------|
| **Structured data rendered as text** | Critical | This is the WORST offender. The macro engine produces `WeeklyReportData` with typed fields: `score_deltas: list[ScoreDelta]`, `regime_transitions`, `staleness_alerts`, `global_indicators_delta`, `has_material_changes`. The renderer receives `build_report_json()` output — a clean dict with numerical fields. Instead of rendering tables and KPI cards, it's fed through the markdown text renderer as prose. Score deltas should be a color-coded table. Regime should be badge rows. Staleness should be a warning box. |
| **Raw markdown artifacts** | High | `**mudança material**` shows literally with asterisks. Unicode ⚠️ rendered as black squares. |
| **Material change flag invisible** | High | `has_material_changes` is the most operationally critical field — it triggers committee action. Currently buried in prose. Should be a prominent orange/red banner. |
| **No score delta visualization** | Medium | Numbers like "72.5 → 73.1 (+0.6)" as text. Should be a table with delta arrows and color coding. |

---

### 5. Manager Spotlight (`preview_manager_spotlight_pt.pdf`)

**What it looks like:** 3 pages. Cover, then body text.

**Problems:**

| Issue | Severity | Detail |
|-------|----------|--------|
| **Rich structured data available, not used** | Critical | The `ManagerSpotlight.generate()` method gathers `fund_data` (identity, SEC enrichment, classification flags), `quant_profile` (returns, momentum, scores), and `risk_metrics` (CVaR, drawdown, Sortino). All of this is used for the LLM prompt but NOT passed to the renderer. Only `content_md` arrives. |
| **Markdown tables render as pipe characters** | Critical | The LLM generates markdown tables (`| Metric | ARCC | Median |`) which render as literal pipe characters in body text. This is the most embarrassing rendering failure. |
| **No fund identity card** | High | Ticker, ISIN, AUM, strategy, inception date — all available in `fund_data` but not rendered as a structured card. |
| **No KPI cards for quant metrics** | High | Sharpe, CVaR, momentum — should be big numbers with labels, not embedded in LLM prose. |
| **Classification flags as text** | Medium | "Index Fund: Não, Fund of Funds: Não" as bullet points. Should be visual badges (green check / grey X). |

---

### 6. Flash Report (`preview_flash_report` — not shown but uses same renderer)

Uses `render_content_pdf()` like everything else. Same markdown rendering problems. No urgency visual treatment, no event summary box, no timestamp (just date).

---

### Cross-Cutting Problems (all documents)

| Problem | Impact |
|---------|--------|
| **`render_content_pdf()` doesn't parse markdown** | `**bold**` renders literally, `| tables |` render as text, lists render as paragraphs starting with `-` or `1.`. The renderer only handles `## heading` and `# heading` — nothing else. |
| **No logo on any content PDF** | Brand identity absent from all documents except IC memos (credit vertical). |
| **No two-column layouts** | Every document is single-column. Wastes space, looks unsophisticated. |
| **`build_netz_styles()` is credit-focused** | Styles were designed for IC memos. Cover styles (`cover_title`, `cover_subtitle`) work, but there are no styles for KPI cards, callout boxes, quote blocks, badge rows, or dashboard grids. |
| **Charts not localized** | `render_nav_chart(title="NAV vs Benchmark")`, `render_allocation_pie(title="Strategic Allocation")` — chart titles are English-only. Block labels in charts use raw `block_id`. |
| **`netz_header_footer()` says "Netz Report"** | Doesn't show document type in the running header unless caller passes `report_title`. Content PDFs pass it, but it's generic. |

---

## What Good Looks Like: Reference Benchmarks

These are the visual standards the industry sets for institutional documents:

1. **BlackRock Fund Fact Sheets** — KPI cards at top (large number, small label), two-column layout, NAV chart + allocation donut side by side, returns table with portfolio/benchmark rows clearly labeled, risk metrics as gauge visuals.
2. **J.P. Morgan Market Insights** — Editorial feel. Large quote pullouts, regional heatmap, bold recommendation boxes, clean section dividers (thin rule + label, not full-width colored bars).
3. **Bridgewater Daily Observations** — Dense data, but clean hierarchy. Score tables with color-coded deltas, regime badges, no wasted space.
4. **Goldman Sachs FICC Flash** — Urgent briefing feel. Bold colored header bar, timestamp prominent, event callout box, concise two-column narrative.

---

## Layout Brainstorm Per Document

### A. Fact Sheet — Executive (1 page)

**Feel:** Dashboard one-pager. Information-dense, scannable in 30 seconds.

```
┌─────────────────────────────────────────────────────┐
│ [NETZ LOGO]                        [NECKER LOGO]    │
│─────────────────────────────────────────────────────│
│                                                     │
│  RESUMO EXECUTIVO                                   │
│  Netz Growth Allocation · Growth · 28/03/2026       │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │  +9.25%  │  │  1.28    │  │  -4.72%  │          │
│  │  1Y Ret  │  │  Sharpe  │  │  CVaR95  │          │
│  └──────────┘  └──────────┘  └──────────┘          │
│                                                     │
│  ┌─ NAV Chart ──────────┐  ┌─ Allocation ──────┐   │
│  │                      │  │     ● Pie chart    │   │
│  │   📈 line chart      │  │     with legend    │   │
│  │                      │  │                    │   │
│  └──────────────────────┘  └────────────────────┘   │
│                                                     │
│  ┌─ Returns ────────────────────────────────────┐   │
│  │        MTD    QTD    YTD    1Y     SI        │   │
│  │ Port   1.23%  3.45%  5.67%  9.25%  18.42%   │   │
│  │ Bench  0.98%  2.87%  4.52%  7.80%  14.15%   │   │
│  └──────────────────────────────────────────────┘   │
│                                                     │
│  ┌─ Top Holdings ────────┐  ┌─ Risk ────────────┐  │
│  │ VOO    US Eq    25.0% │  │ Vol     12.35%    │  │
│  │ PTTRX  FI       20.0% │  │ DD Max  -8.45%   │  │
│  │ IEFA   Intl     15.0% │  │ Sharpe  1.28     │  │
│  │ ...                   │  │ CVaR95  -4.72%   │  │
│  └───────────────────────┘  └───────────────────┘  │
│                                                     │
│  CONFIDENCIAL · Disclaimer text...                  │
│ ════════════ orange stripe ═══════════════════════  │
└─────────────────────────────────────────────────────┘
```

**Key changes vs current:**
- KPI hero cards at top (3 large numbers)
- Two-column layout: chart + pie side by side, holdings + risk side by side
- Labeled portfolio/benchmark rows
- Everything fits in 1 page — density is the point
- Logo row on cover

### B. Fact Sheet — Institutional (4-6 pages)

**Feel:** Comprehensive institutional report. All data the committee needs.

**Page 1: Cover**
- Logo row (Netz left, Necker right)
- Title, portfolio name, profile, as_of
- 4 KPI hero cards (1Y Return, Sharpe, CVaR, Volatility)
- Confidential stamp

**Page 2: Performance**
- NAV vs Benchmark chart (full width)
- Returns table (labeled rows: Portfolio / Benchmark)
- Allocation pie + allocation table side by side

**Page 3: Holdings + Risk**
- Top holdings table
- Risk metrics KPI row
- Manager commentary in a callout box (light background, left navy border)

**Page 4: Attribution + Stress**
- Brinson attribution table
- Regime overlay chart
- Stress scenario table

**Page 5: Fees**
- Fee drag summary KPI row (drag ratio, efficient count, inefficient count)
- Per-fund fee comparison table with color-coded status column
- Remove ESG placeholder entirely

**Page 6: Disclaimer**
- Full disclaimer + regulatory text

### C. Manager Spotlight (4-5 pages)

**Feel:** Equity research note. Dense structured data + analytical narrative.

**Page 1: Cover**
- Logo row
- "DESTAQUE DO GESTOR / MANAGER SPOTLIGHT"
- Fund name as hero subtitle
- Date, confidential

**Page 2: Fund Identity + Quant Dashboard**
```
┌─────────────────────────────────────────────────────┐
│ FICHA DO FUNDO                                      │
│ ┌─────────────────────┬─────────────────────────┐   │
│ │ Ticker: ARCC        │ Strategy: Private Credit│   │
│ │ ISIN: —             │ Inception: 2004-10-08   │   │
│ │ AUM: $23.4B         │ Expense Ratio: 1.50%    │   │
│ │ Manager: Ares Mgmt  │ CRD: 152891             │   │
│ └─────────────────────┴─────────────────────────┘   │
│                                                     │
│ Flags: [BDC] [Ext. Managed] [Not Index]             │
│                                                     │
│ DASHBOARD QUANTITATIVO                              │
│ ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│ │  1.45    │  │  -3.8%   │  │  -6.2%   │           │
│ │  Sharpe  │  │  CVaR95  │  │  Max DD  │           │
│ └──────────┘  └──────────┘  └──────────┘           │
│                                                     │
│ SINAIS DE MOMENTUM                                  │
│ ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│ │  58.3    │  │  0.65    │  │  62.5    │           │
│ │  RSI 14  │  │  Bolling │  │  Blended │           │
│ │ [YELLOW] │  │ [GREEN]  │  │ [GREEN]  │           │
│ └──────────┘  └──────────┘  └──────────┘           │
│                                                     │
│ ANÁLISE DE TAXAS                                    │
│ ┌───────────────────────────────────────────────┐   │
│ │ Mgmt Fee    Perf Fee    Other    Total    Drag│   │
│ │ 1.50%       2.00%       0.15%    3.65%   31% │   │
│ └───────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

**Page 3-4: Narrative Analysis**
- LLM `content_md` rendered with proper markdown parsing (bold, lists, tables)
- Each `##` section gets a clean heading (thin navy rule + text, not full-width bar)

**Page 5: Disclaimer**

**Key insight:** The `ManagerSpotlight.generate()` method already gathers `fund_data`, `quant_profile`, `risk_metrics`. These dicts need to be carried on `SpotlightResult` and passed to the renderer. The LLM narrative is complementary — the structured data is primary.

### D. Investment Outlook (3-4 pages)

**Feel:** Editorial quarterly publication. Magazine-style.

**Page 1: Cover**
- Logo row
- "PERSPECTIVA DE INVESTIMENTO / INVESTMENT OUTLOOK"
- Prominent quarter badge: "Q2 2026"
- Date, confidential

**Page 2: Macro Dashboard + Global Summary**
```
┌─────────────────────────────────────────────────────┐
│ PAINEL MACROECONÔMICO                               │
│ ┌───────────────────────────────────────────────┐   │
│ │ Region     │ Score │ Delta │ Regime            │   │
│ │ N. America │ 73.1  │ +0.6  │ 🟢 Expansion     │   │
│ │ Europe     │ 66.2  │ +0.4  │ 🟢 Expansion     │   │
│ │ Asia-Pac   │ 59.8  │ -8.5  │ 🟡 Near thresh  │   │
│ │ EM         │ 57.9  │ -0.3  │ 🔴 Contraction   │   │
│ └───────────────────────────────────────────────┘   │
│                                                     │
│ ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────┐  │
│ │  48.7    │  │  $82.30  │  │  287.1   │  │104.2│  │
│ │  GeoPol  │  │  WTI     │  │  CRB     │  │ DXY │  │
│ │  +3.5    │  │  +4.8%   │  │  +0.6%   │  │+0.4%│  │
│ └──────────┘  └──────────┘  └──────────┘  └─────┘  │
│                                                     │
│ RESUMO MACRO GLOBAL                                 │
│ [LLM narrative section...]                          │
└─────────────────────────────────────────────────────┘
```

**Page 3-4: Narrative Sections**
- Regional Outlook, Asset Class Views, Portfolio Positioning, Key Risks
- Proper markdown rendering with bold, lists
- Recommendation box at end (colored background, border)

**Key insight:** `InvestmentOutlook._gather_macro_data()` returns the full `MacroReview.report_json` which has `score_deltas`, `global_indicators_delta`, `regime_transitions`. This data must be added to `OutlookResult` and passed to the renderer alongside `content_md`.

### E. Flash Report (1-2 pages)

**Feel:** Urgent market briefing. Time-sensitive.

**Page 1: Everything**
```
┌─────────────────────────────────────────────────────┐
│ [NETZ LOGO]                        28/03/2026 15:42 │
│═══════════ ORANGE STRIPE (urgency) ═════════════════│
│                                                     │
│  ⚡ RELATÓRIO FLASH / FLASH REPORT                  │
│                                                     │
│  ┌─ EVENT CONTEXT ──────────────────────────────┐   │
│  │ 🟠 Event: BoJ Policy Reversal               │   │
│  │    Trigger: 28 Mar 2026                      │   │
│  │    Regions: Asia-Pacific, Global             │   │
│  └──────────────────────────────────────────────┘   │
│                                                     │
│  EVENTO DE MERCADO                                  │
│  [LLM narrative...]                                 │
│                                                     │
│  IMPACTO NO MERCADO                                 │
│  [LLM narrative...]                                 │
│                                                     │
│  AÇÕES RECOMENDADAS                                 │
│  [LLM narrative...]                                 │
│                                                     │
│  Disclaimer...                                      │
│ ════════════ orange stripe ═══════════════════════  │
└─────────────────────────────────────────────────────┘
```

**Key differences from other documents:**
- ORANGE accent dominant (not navy) — signals urgency
- Timestamp with HOUR, not just date
- Event context box with colored background
- Maximum 2 pages — brevity is the design constraint
- No cover page separation — content starts immediately after header

### F. Macro Committee Review (2 pages)

**Feel:** Operational dashboard printout. Data-first, no narrative.

**Page 1:**
```
┌─────────────────────────────────────────────────────┐
│ [NETZ LOGO]        REVISÃO MACRO SEMANAL            │
│                    Comitê de Investimentos           │
│                    Data-base: 28/03/2026             │
│─────────────────────────────────────────────────────│
│                                                     │
│ ┌═══════════════════════════════════════════════┐   │
│ ║ ⚠ MUDANÇA MATERIAL IDENTIFICADA              ║   │
│ └═══════════════════════════════════════════════┘   │
│  (only shown if has_material_changes == true)       │
│                                                     │
│ SCORES REGIONAIS                                    │
│ ┌───────────────────────────────────────────────┐   │
│ │ Região          │ Anterior │ Atual  │ Delta   │   │
│ │ América Norte   │  72.5    │ 73.1   │ ▲ +0.6  │   │
│ │ Europa          │  65.8    │ 66.2   │ ▲ +0.4  │   │
│ │ Ásia-Pacífico   │  68.3    │ 59.8   │ ▼ -8.5 ⚠│   │
│ │ Merc. Emergentes│  58.2    │ 57.9   │ ▼ -0.3  │   │
│ └───────────────────────────────────────────────┘   │
│                                                     │
│ REGIMES                                             │
│ [🟢 Expansion] [🟢 Expansion] [🟡 Near] [🔴 Contr] │
│  N. America      Europe        APAC      EM         │
│                                                     │
│ INDICADORES GLOBAIS                                 │
│ ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────┐  │
│ │  48.7    │  │  $82.30  │  │  287.1   │  │104.2│  │
│ │  GeoPol  │  │  WTI     │  │  CRB     │  │ DXY │  │
│ │  ▲ +3.5  │  │  ▲ +4.8% │  │  ▲ +0.6% │  │▲+0.4│  │
│ └──────────┘  └──────────┘  └──────────┘  └─────┘  │
└─────────────────────────────────────────────────────┘
```

**Page 2:**
```
┌─────────────────────────────────────────────────────┐
│ ALERTAS DE STALENESS                                │
│ ┌─ Warning Box (orange bg) ─────────────────────┐   │
│ │ imf_weo_gdp_forecast — last: 15 Mar 2026     │   │
│ │ bis_credit_gap_cn    — last: 12 Mar 2026      │   │
│ └───────────────────────────────────────────────┘   │
│                                                     │
│ Disclaimer...                                       │
└─────────────────────────────────────────────────────┘
```

**Key insight:** This document receives NO markdown. `MacroReview.report_json` is pure structured data from `build_report_json()`. The renderer formats data directly — no LLM text at all. Currently, the preview script generates fake markdown for this doc, which is wrong.

### G. Long-Form Report (5-8 pages)

**Feel:** Comprehensive institutional due diligence. The most complete document.

**Page 1: Cover**
- Logo row
- "RELATÓRIO INSTITUCIONAL / INSTITUTIONAL REPORT"
- Portfolio name, profile, date
- Confidential stamp

**Page 2: Table of Contents**
- Auto-generated from completed chapters
- Failed chapters marked with "[Indisponível]"
- Confidence badges next to each chapter title

**Pages 3-7: Chapters (each rendered by tag)**
Each chapter type gets specialized rendering:

| Chapter Tag | Structured Rendering |
|-------------|---------------------|
| `macro_context` | Regional score table (same as macro committee) |
| `strategic_allocation` | Block allocation table: Block / Target / Current / Delta (colored) |
| `portfolio_composition` | Holdings change table: Fund / Previous Weight / Current / Change |
| `performance_attribution` | Brinson table (reuse from fact sheet institutional) |
| `risk_decomposition` | CVaR decomposition: Block / CVaR / Contribution % (stacked bar?) |
| `fee_analysis` | Fee drag summary + per-fund fee table (reuse from fact sheet) |
| `per_fund_highlights` | Per-fund cards with name, key metrics, narrative |
| `forward_outlook` | Narrative body + recommendation box |

Between structured data sections, `chapter.content` narrative is rendered with proper markdown parsing.

**Page 8: Disclaimer**

**Key insight:** This is the hardest renderer because each chapter tag needs different rendering logic. But the data is already structured in `ChapterResult.content: dict`. The current system throws away all this structure and renders only the LLM text.

---

## Technical Root Causes

### 1. `render_content_pdf()` is a markdown non-parser

```python
# content_pdf.py — the entire "parser"
for line in content_md.split("\n"):
    line = line.strip()
    if not line:
        story.append(Spacer(1, 2 * mm))
    elif line.startswith("## "):
        story.append(Paragraph(safe_text(line[3:]), styles["section_heading"]))
    elif line.startswith("# "):
        story.append(Paragraph(safe_text(line[2:]), styles["cover_subtitle"]))
    else:
        story.append(Paragraph(safe_text(line), styles["body"]))
```

This handles `##` and `#` headings. Everything else — bold, italic, lists, tables, code blocks — is rendered as plain body text with `safe_text()` which also escapes `<` and `>`, breaking any embedded HTML.

### 2. Structured data never reaches the renderer

Each engine gathers rich structured data:
- `ManagerSpotlight.generate()` → `fund_data`, `quant_profile`, `risk_metrics`
- `InvestmentOutlook.generate()` → `macro_data` from `_gather_macro_data()`
- `FlashReport.generate()` → `event_context`, `macro_data`
- `MacroCommittee` → `WeeklyReportData` → `build_report_json()`
- `LongFormReport` → `ChapterResult.content` per chapter

But the result dataclasses only carry `content_md: str`. The structured data is used for the LLM prompt, then discarded. The renderer receives only the LLM's text interpretation.

### 3. `pdf_base.py` has no layout components

The base has: `build_institutional_table()`, `build_netz_styles()`, `netz_header_footer()`, `build_ic_cover_story()`.

What's missing for institutional layouts:
- **KPI card flowable** — large number + small label + optional delta, in a bordered box
- **Callout box** — colored background container for commentary/warnings
- **Badge row** — inline colored labels (regime badges, classification flags)
- **Two-column layout helper** — side-by-side flowable arrangement
- **Markdown-to-story parser** — proper conversion of `**bold**`, `- list`, `| table |` to ReportLab flowables
- **Cover page builder** for wealth (the existing `build_ic_cover_story()` is credit-specific with IC signal badge)

### 4. Chart localization gap

`chart_builder.py` functions accept optional `title` parameter but default to English. Block labels use raw `block_id`. Charts need i18n support for titles and legend labels.

---

## Implementation Approach (for next prompt)

The next prompt should implement in this order:

1. **`pdf_base.py` extensions** — Add reusable flowables: `build_kpi_card()`, `build_callout_box()`, `build_badge_row()`, `build_two_column()`, `markdown_to_story()`, `build_wealth_cover()`. These become shared primitives for all renderers.

2. **Chart i18n** — Add `language` parameter to chart functions. Create block label i18n map.

3. **Fact sheet overhaul** — Redesign executive (1-page dashboard) and institutional (multi-page with two-column layouts, KPI cards, labeled rows). Remove ESG placeholder.

4. **Content renderers** — Build dedicated renderers for all 5 types. Each receives structured data + narrative.

5. **Result model extensions** — Add structured data fields to `SpotlightResult`, `OutlookResult`, `FlashReportResult`.

6. **Preview script overhaul** — Each preview exercises the full renderer with realistic structured mock data.

7. **Route dispatch** — Wire dedicated renderers in `_render_content_pdf()`.

---

## What Already Exists (DO NOT re-implement)

### Infrastructure (keep, extend)
- `backend/ai_engine/pdf/pdf_base.py` — shared Netz brand primitives. **WILL BE EXTENDED** with new flowables.
- `backend/vertical_engines/wealth/fact_sheet/i18n.py` — bilingual labels. **WILL BE EXTENDED** with new keys.
- `backend/vertical_engines/wealth/fact_sheet/chart_builder.py` — chart renderers. **WILL BE EXTENDED** with i18n.
- `backend/vertical_engines/wealth/fact_sheet/models.py` — fact sheet data models.
- `backend/vertical_engines/wealth/content_pdf.py` — current generic renderer. **PRESERVED as fallback**.

### Engine Logic (DO NOT modify)
- `backend/vertical_engines/wealth/manager_spotlight.py` — `generate()`, `_gather_fund_data()`, `_gather_vector_context()`, `_generate_narrative()`. Only modify `render_pdf()` and result model.
- `backend/vertical_engines/wealth/investment_outlook.py` — same pattern. Only modify `render_pdf()` and result model.
- `backend/vertical_engines/wealth/flash_report.py` — same pattern.
- `backend/vertical_engines/wealth/macro_committee_engine.py` — `generate_weekly_report()`, `build_report_json()`. Do not modify.
- `backend/vertical_engines/wealth/long_form_report/` — chapter generation logic. Do not modify.

### Content Engine Results (frozen dataclasses — extend, don't replace)
1. **`SpotlightResult`** — add: `fund_data`, `quant_profile`, `risk_metrics` fields
2. **`OutlookResult`** — add: `macro_data` field
3. **`FlashReportResult`** — add: `event_context` field
4. **`LongFormReportResult`** — already has `chapters[].content: dict` (no change needed)
5. **`WeeklyReportData`** / `build_report_json()` — already structured (no change needed)

### Preview Scripts
- `backend/scripts/preview_fact_sheet.py` — **WILL BE OVERHAULED** with new renderer calls
- `backend/scripts/preview_content_pdfs.py` — **WILL BE OVERHAULED** with structured mock data

### Route Integration
- `backend/app/domains/wealth/routes/content.py:502` — `_render_content_pdf()` dispatches by content_type

---

## Constraints

- DO NOT change content engine business logic (LLM calls, DB queries, vector search).
- All renderers must support both PT and EN via `i18n.LABELS[language]`.
- Renderers must handle missing/partial data gracefully (conditional sections, not crashes).
- Follow existing import patterns: renderers import from `pdf_base` and `i18n`, never from routes or engines.
- New `pdf_base.py` primitives must be genuinely reusable across all renderers.
- Charts must work in headless mode (Agg backend, no DISPLAY).
