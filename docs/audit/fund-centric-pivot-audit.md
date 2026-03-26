# Fund-Centric Pivot Audit

**Date:** 2026-03-26
**Scope:** DD Report Engine, SEC Data Injection, Manager Assessment, Drift Monitoring, Peer Comparison
**Verdict:** The system has a **critical semantic gap** in the DD Report evidence pipeline. Drift and Peer Compare are already fund-centric. The DD Report treats 13F (firm-level) holdings as if they were fund-level holdings, ignoring the N-PORT data that is already ingested and available.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Finding 1 — Evidence Pack Is 13F-Only (Firm-Centric)](#2-finding-1--evidence-pack-is-13f-only-firm-centric)
3. [Finding 2 — Manager Assessment Evaluates the Firm, Not the PM](#3-finding-2--manager-assessment-evaluates-the-firm-not-the-pm)
4. [Finding 3 — Drift & Peer Compare Are Already Fund-Centric](#4-finding-3--drift--peer-compare-are-already-fund-centric)
5. [Finding 4 — Instrument Model Has No SEC Linkage](#5-finding-4--instrument-model-has-no-sec-linkage)
6. [Finding 5 — DisclosureMatrix Exists But Is Not Consumed by DD Report](#6-finding-5--disclosurematrix-exists-but-is-not-consumed-by-dd-report)
7. [Execution Plan — Fund-Centric DD Report Pivot](#7-execution-plan--fund-centric-dd-report-pivot)
8. [File Reference Index](#8-file-reference-index)

---

## 1. Executive Summary

The Unified Fund Catalog (completed 2026-03-26) introduced a `DisclosureMatrix` that correctly distinguishes between `holdings_source="nport"` (registered US funds) and `holdings_source=None` (private/UCITS). The catalog knows **which data source is authoritative for each fund**.

However, the DD Report engine — the system's flagship analytical output — **ignores this matrix entirely**. It unconditionally resolves `fund.manager_name → sec_managers.firm_name → CIK → sec_13f_holdings`, treating the firm's 13F filing as the fund's portfolio. This is semantically wrong for every registered mutual fund and ETF, where the authoritative source is N-PORT (fund-level monthly holdings).

### Impact Matrix

| System | Current State | Semantic Correctness | Action Required |
|--------|--------------|---------------------|-----------------|
| **DD Report — Investment Strategy** | 13F sector weights from firm | **WRONG** for registered funds | Pivot to N-PORT via DisclosureMatrix |
| **DD Report — Manager Assessment** | Evaluates entire RIA firm | **PARTIALLY WRONG** — should split firm vs PM | Add fund-level PM context |
| **DD Report — Operational DD** | ADV compliance on firm | **CORRECT** — firm governance is the right scope | None |
| **Drift Monitoring** | `fund_risk_metrics` (NAV-derived) | **CORRECT** — fund-level | None |
| **Peer Comparison** | `instrument_screening_metrics` | **CORRECT** — fund-level | None |
| **Fund Catalog** | DisclosureMatrix with `holdings_source` | **CORRECT** — properly segmented | None |
| **SEC Analysis Routes** | `/sec/managers/` for 13F, `/sec/funds/` for N-PORT | **CORRECT** — properly separated | None |

### The Core Problem in One Sentence

> The DD Report asks "what does the **manager firm** hold?" (13F) when it should ask "what does **this fund** hold?" (N-PORT), and the DisclosureMatrix already knows which question is answerable.

---

## 2. Finding 1 — Evidence Pack Is 13F-Only (Firm-Centric)

### Current Architecture

```
DDReportEngine.generate()
    │
    ├── fund = load_fund(fund_id)
    ├── manager_name = fund.manager_name          ← string, e.g. "BlackRock"
    │
    ├── gather_sec_13f_data(db, manager_name)      ← resolves to BlackRock's FIRM 13F
    │   └── _resolve_cik(manager_name)             ← case-insensitive match on sec_managers.firm_name
    │       └── query sec_13f_holdings WHERE cik = firm_cik
    │           └── sector_weights = aggregate by sector
    │           └── drift_detected = |Δsector| > 5pp between quarters
    │
    ├── gather_sec_adv_data(db, manager_name)      ← firm ADV (correct for ops/compliance)
    └── gather_sec_adv_brochure(db, crd_number)    ← firm brochure (correct for ops/compliance)
```

**Reference:** `dd_report/dd_report_engine.py:315-320`, `dd_report/sec_injection.py:27-98`

### What's Wrong

1. **13F is the firm's aggregate equity portfolio**, not the fund's. BlackRock's 13F shows ~$4T in equity positions across 500+ funds. Injecting this into a DD Report for "BlackRock Technology Opportunities Fund" is meaningless — the 13F sector weights reflect the entire firm, not the fund's strategy.

2. **N-PORT is available and already ingested.** The `nport_ingestion` worker (lock 900_018) runs weekly, populating `sec_nport_holdings` with fund-level monthly holdings including `pct_of_nav`. The `sec_registered_funds` catalog links each fund CIK to its manager CRD.

3. **The EvidencePack dataclass has zero N-PORT fields:**

```python
# Current fields (evidence_pack.py:110-160)
thirteenf_available: bool = False          # ← 13F only
sector_weights: dict[str, float] = {}      # ← from 13F firm aggregate
drift_detected: bool = False               # ← from 13F quarter-over-quarter
drift_quarters: int = 0                    # ← 13F quarter count

# Missing entirely:
# nport_available: bool
# nport_holdings: list[dict]
# nport_sector_weights: dict[str, float]
# nport_asset_allocation: dict[str, float]  (equity/fixed/cash %)
# fund_style: dict[str, Any]               (from sec_fund_style_snapshots)
```

4. **Chapter field expectations hardcode 13F as provider:**

```python
# evidence_pack.py:22-35
"investment_strategy": {
    "fields": ["fund_name", "fund_type", "geography", "asset_class",
               "thirteenf_available", "sector_weights"],
    "providers": ["YFinance", "SEC EDGAR 13F"],     # ← should be N-PORT for registered funds
    "primary_provider": "YFinance",
},
```

5. **The Jinja2 prompt only references 13F:**

```jinja2
{# investment_strategy.j2:32-56 #}
{% if thirteenf_available %}
## SEC 13F Holdings Verification ({{ drift_quarters }} quarters of data)
The manager's most recent 13F-HR filing reports the following sector allocation:
{% for sector, weight in sector_weights.items() %}
- {{ sector }}: {{ "%.1f"|format(weight * 100) }}%
{% endfor %}
{% endif %}
```

6. **Chapter user content assembly is 13F-hardcoded:**

```python
# chapters.py:165-175
if chapter_tag == "investment_strategy" and evidence_context.get("thirteenf_available"):
    parts.append("\n## SEC 13F Holdings Data")
```

### Data Availability Gap

| Data Source | Ingested? | Available in DB? | Used by DD Report? |
|-------------|----------|-----------------|-------------------|
| `sec_13f_holdings` (firm quarterly) | ✅ Weekly | ✅ 8 quarters depth | ✅ **Only source used** |
| `sec_nport_holdings` (fund monthly) | ✅ Weekly | ✅ 12 months depth | ❌ **Never consumed** |
| `sec_fund_style_snapshots` (derived) | ✅ Weekly | ✅ Per fund CIK | ❌ **Never consumed** |
| `sec_registered_funds` (catalog) | ✅ Weekly | ✅ 15K+ funds | ❌ **Never consumed** |

### Why This Matters Analytically

For a registered US fund (e.g., "Vanguard Total Stock Market Index Fund"):

| Question | 13F Answer (WRONG) | N-PORT Answer (CORRECT) |
|----------|-------------------|------------------------|
| Sector allocation | Vanguard Group's $7.7T aggregate | This specific fund's $1.3T allocation |
| Asset classes | Equity only (13F mandate) | Equity + fixed income + cash + derivatives |
| Holdings count | ~13,000 (all Vanguard equity) | ~3,600 (this fund only) |
| Update frequency | Quarterly (45-day delay) | Monthly (60-day delay) |
| Drift detection | Firm rebalancing noise | Actual fund strategy shift |

---

## 3. Finding 2 — Manager Assessment Evaluates the Firm, Not the PM

### Current Architecture

The `manager_assessment` chapter (Chapter 3) evaluates five dimensions:

| Dimension | Data Source | Actual Scope |
|-----------|-----------|-------------|
| Track Record | `fund_risk_metrics` | ✅ Fund-level (correct) |
| Team Stability | `sec_manager_team` (ADV Part 2A bios) | ❌ **Firm-level** — all key personnel of the RIA |
| AUM Growth | `sec_managers.aum_total` | ❌ **Firm-level** — total AUM across all funds |
| Organizational Strength | ADV Part 2A Items 8-10 | ❌ **Firm-level** — firm infrastructure |
| Alignment of Interests | `sec_managers.fee_types` | ❌ **Firm-level** — firm fee schedule |

**Reference:** `prompts/dd_chapters/manager_assessment.j2:88-105`

### What the Prompt Says

```jinja2
{# manager_assessment.j2:7 #}
You are a senior investment analyst writing the Fund Manager Assessment chapter

{# manager_assessment.j2:24-28 #}
## SEC ADV — Regulatory AUM (Form ADV Part 1A)
{# Shows firm total AUM, discretionary/non-discretionary split #}

{# manager_assessment.j2:43-66 #}
## ADV Part 2A — Regulatory Disclosures
{# Item 8: Investment Strategy & Methods of Analysis — FIRM level #}
{# Item 5: Fee Schedule — FIRM level, not fund-specific #}
{# Item 9: Disciplinary Information — on the FIRM #}
{# Item 10: Other Financial Activities — FIRM level #}

{# manager_assessment.j2:97-100 #}
AUM Growth: Use the SEC-reported regulatory AUM figures above as authoritative.
{# This is the FIRM's total AUM, not the fund's AUM #}
```

### What Should Change

The chapter conflates two distinct concepts:

| Concept | Correct Scope | Data Source | DD Report Use |
|---------|--------------|-------------|---------------|
| **Portfolio Management Team** | Fund-specific PMs | N-PORT filing header + ADV Part 2B (supplement) | Chapter 3 primary focus |
| **RIA Organizational Quality** | Firm governance | ADV Part 1A + Part 2A Items 9-11 | Chapter 7 (Operational DD) |

**The fix is semantic, not structural.** ADV data is legitimately useful — but in the right chapter:

- **Chapter 3 (Manager Assessment):** Should focus on the fund's portfolio management team, their tenure on this specific fund, the fund's AUM trajectory (not firm AUM), and strategy consistency (via N-PORT style drift, not 13F firm drift).
- **Chapter 7 (Operational DD):** Already correctly scoped to firm governance. ADV compliance, fee structure, and organizational strength belong here.

### Missing Data: Fund-Level PM Identity

Currently there is no way to identify **which team members manage this specific fund**. The `sec_manager_team` table lists all firm-level personnel from ADV Part 2A. N-PORT filing headers include a `manager_name` field per fund, but this is the firm name, not the PM name.

**Partial solution:** `sec_registered_funds` could be extended with PM names from N-PORT XML `<investorType>` and `<managementInfo>` sections (currently not parsed).

---

## 4. Finding 3 — Drift & Peer Compare Are Already Fund-Centric

### Drift Monitoring — CORRECT

| Component | Data Source | Granularity | 13F Used? |
|-----------|-----------|-------------|----------|
| Strategy Drift Scanner | `fund_risk_metrics` (7 metrics: vol, drawdown, Sharpe, Sortino, alpha, beta, tracking error) | Per-instrument, daily | **NO** |
| DTW Drift Monitor | `fund_risk_metrics.dtw_drift_score` | Per-instrument vs block benchmark | **NO** |
| Drift Alerts | `strategy_drift_alerts` | Per-instrument | **NO** |

**Algorithm:** Z-score based behavior change detection. Compares 90-day recent window vs 360-day baseline. Alert if |z| > 2.0 on any metric. Severity: ≥3 anomalous = severe, 1-2 = moderate.

**Reference:** `vertical_engines/wealth/monitoring/strategy_drift_scanner.py:70-223`

**Verdict:** Drift monitoring is fully fund-centric. It reads from `fund_risk_metrics` which is computed by the `risk_calc` worker from `nav_timeseries` (fund NAV). No 13F contamination.

### Peer Comparison — CORRECT

| Component | Data Source | Granularity | 13F Used? |
|-----------|-----------|-------------|----------|
| Peer Matcher | `instruments_universe` (type + block + attributes) | Per-instrument | **NO** |
| Peer Rankings | `instrument_screening_metrics` | Per-instrument | **NO** |
| Composite Score | Weighted percentiles (Sharpe 30%, drawdown 20%, return 25%, vol 15%, positive months 10%) | Per-instrument | **NO** |

**Peer matching hierarchy:**
1. `block_id::strategy::aum_bucket` (most specific)
2. `block_id::strategy`
3. `block_id` (broadest)

Falls through levels until ≥20 peers found (Morningstar/Lipper standard).

**Reference:** `vertical_engines/wealth/peer_group/peer_matcher.py:80-91`, `peer_group/service.py:41-61`

**Verdict:** Peer comparison is fully fund-centric. It matches instruments by type/strategy/AUM and ranks by quant metrics from `instrument_screening_metrics`. No firm-level data involved.

### The Exception: SEC Analysis Routes (Correctly Separated)

The `/sec/managers/{cik}/holdings` route and `/sec/managers/compare` endpoint **do** use 13F data — but these are explicitly manager-scoped routes, not fund analysis. They live in `routes/sec_analysis.py` and are separate from the fund analysis pipeline.

Similarly, `/sec/funds/{cik}/holdings` correctly uses N-PORT data for fund-level views.

**Reference:** `routes/sec_analysis.py:735-896` (manager compare), `routes/sec_funds.py` (fund N-PORT)

---

## 5. Finding 4 — Instrument Model Has No SEC Linkage

### Current State

Neither the legacy `Fund` model nor the current `Instrument` model has a `sec_cik` field:

```python
# models/fund.py (deprecated)
class Fund(Base):
    manager_name: Mapped[str | None]    # ← only linkage to SEC, via string match
    # No sec_cik, no crd_number, no FK to sec_registered_funds

# models/instrument.py (current)
class Instrument(Base):
    attributes: Mapped[dict] = mapped_column(JSONB)  # ← opaque bag, no explicit SEC fields
    # No sec_cik, no FK to sec_registered_funds
```

### Why This Is the Root Cause

The DD Report cannot use N-PORT data because it has no way to resolve `Instrument → fund CIK`. The current path is:

```
Instrument.manager_name → sec_managers.firm_name → firm CIK → sec_13f_holdings
```

The correct path for registered funds would be:

```
Instrument.sec_cik → sec_nport_holdings WHERE cik = fund_cik
```

Or via the catalog:

```
Instrument.external_id → sec_registered_funds.cik → sec_nport_holdings
```

### The Catalog Already Has the Answer

The `UnifiedFundItem` schema includes `external_id` which is the fund CIK for `universe="registered_us"`. The catalog SQL (`catalog_sql.py:167`) correctly joins `sec_registered_funds` and produces `holdings_source="nport"`.

**But this information never flows back to the DD Report engine.** The DD Report receives only `fund_id` (tenant instrument UUID) and resolves SEC data via `manager_name` string match.

---

## 6. Finding 5 — DisclosureMatrix Exists But Is Not Consumed by DD Report

### Current DisclosureMatrix

```python
# schemas/catalog.py:17-29
class DisclosureMatrix(BaseModel):
    has_holdings: bool = False
    has_nav_history: bool = False
    has_quant_metrics: bool = False
    has_private_fund_data: bool = False
    has_style_analysis: bool = False
    has_13f_overlay: bool = False           # ← never populated
    has_peer_analysis: bool = False
    holdings_source: Literal["nport", "13f"] | None = None
    nav_source: Literal["yfinance"] | None = None
    aum_source: Literal["nport", "schedule_d", "yfinance"] | None = None
```

### How the Catalog Populates It

| Universe | `has_holdings` | `holdings_source` | `has_style_analysis` |
|----------|---------------|-------------------|---------------------|
| `registered_us` | `True` | `"nport"` | `True` |
| `private_us` | `False` | `None` | `False` |
| `ucits_eu` | `False` | `None` | `False` |

**Reference:** `queries/catalog_sql.py:167` (registered), `catalog_sql.py:236` (private), `catalog_sql.py:296` (UCITS)

### The Gap

The DD Report engine does not:
1. Look up the instrument's `DisclosureMatrix`
2. Branch on `holdings_source` to choose 13F vs N-PORT
3. Use `has_style_analysis` to include/exclude style drift data

Instead, it unconditionally runs `gather_sec_13f_data()` for all funds regardless of type.

### Note: `has_13f_overlay` Is Never Set

The `has_13f_overlay` field exists in the schema but is never populated by the catalog SQL. This field was designed for the future state where 13F data would be an **overlay** (supplementary context about the manager's firm) rather than the primary holdings source. The pivot should populate this field for funds where the manager also files 13F.

---

## 7. Execution Plan — Fund-Centric DD Report Pivot

### Phase 1: Data Linkage (Foundation)

**Goal:** Enable `Instrument → fund CIK` resolution without breaking existing flows.

#### 1.1 Add `sec_cik` to Instrument attributes convention

Instead of a schema migration, use the existing `attributes: JSONB` field with a convention:

```python
# When importing from catalog, store:
instrument.attributes["sec_cik"] = "0001234567"     # fund CIK (N-PORT filer)
instrument.attributes["sec_universe"] = "registered_us"  # universe tag
```

**Why JSONB, not a column:** Avoids migration for a field that only applies to US registered funds. The catalog import flow (`asset_universe/` package) already writes attributes.

**Alternative (stronger):** Add `sec_cik: Mapped[str | None]` column to `Instrument` via Alembic migration. This is cleaner for queries but requires migration 0043+.

#### 1.2 Backfill existing instruments

Write a one-time script that matches existing `Instrument` records against `sec_registered_funds` by name/ticker/ISIN and populates `sec_cik` in attributes.

#### 1.3 Update asset_universe import to persist `sec_cik`

When a fund is imported from the catalog into the tenant universe, copy the `external_id` (which is the fund CIK for registered_us) into `attributes.sec_cik`.

---

### Phase 2: Evidence Pack Pivot (Core Fix)

**Goal:** The DD Report uses N-PORT for registered funds, 13F only as manager overlay.

#### 2.1 Add N-PORT fields to EvidencePack

```python
# New fields in evidence_pack.py
nport_available: bool = False
nport_holdings_count: int = 0
nport_sector_weights: dict[str, float] = field(default_factory=dict)
nport_asset_allocation: dict[str, float] = field(default_factory=dict)  # equity/fixed/cash %
nport_top_holdings: list[dict[str, Any]] = field(default_factory=list)  # top 10 by pct_of_nav
nport_report_date: str | None = None
fund_style: dict[str, Any] = field(default_factory=dict)  # from sec_fund_style_snapshots
holdings_source: str | None = None  # "nport" | "13f" | None — mirrors DisclosureMatrix
```

#### 2.2 Create `gather_sec_nport_data()` in sec_injection.py

```python
def gather_sec_nport_data(
    db: Session,
    *,
    fund_cik: str | None,
) -> dict[str, Any]:
    """Gather N-PORT fund-level holdings for DD report.

    DB-only reads from sec_nport_holdings and sec_fund_style_snapshots.
    """
    if not fund_cik:
        return {}

    # Query latest 2 report dates from sec_nport_holdings
    # Compute sector weights from holdings (group by sector, sum pct_of_nav)
    # Compute asset allocation (equity/fixed/cash split)
    # Get top 10 holdings by pct_of_nav
    # Get latest style snapshot from sec_fund_style_snapshots
    # Detect sector drift between latest 2 months (same 5pp threshold)
```

#### 2.3 Update `_build_evidence()` to branch on DisclosureMatrix

```python
def _build_evidence(self, db: Session, *, fund_id: str, organization_id: str) -> EvidencePack:
    fund = ...  # load instrument

    # Resolve SEC linkage
    fund_cik = fund.attributes.get("sec_cik")
    universe = fund.attributes.get("sec_universe")
    manager_name = fund.manager_name  # or attributes.get("manager_name")

    # Holdings: branch on universe
    if universe == "registered_us" and fund_cik:
        nport_data = gather_sec_nport_data(db, fund_cik=fund_cik)
        holdings_source = "nport"
    else:
        nport_data = {}
        holdings_source = None

    # 13F: always gather as OVERLAY (manager firm context), never as primary holdings
    sec_13f = gather_sec_13f_data(db, manager_name=manager_name)

    # ADV: always gather (firm governance for ops/compliance chapters)
    sec_adv = gather_sec_adv_data(db, manager_name=manager_name)
    adv_brochure = gather_sec_adv_brochure(db, sec_adv.get("crd_number"))

    return EvidencePack(
        # ... existing fields ...
        nport_available=bool(nport_data),
        nport_sector_weights=nport_data.get("sector_weights", {}),
        nport_asset_allocation=nport_data.get("asset_allocation", {}),
        nport_top_holdings=nport_data.get("top_holdings", []),
        nport_report_date=nport_data.get("report_date"),
        fund_style=nport_data.get("fund_style", {}),
        holdings_source=holdings_source,
        # 13F fields remain for overlay
        thirteenf_available=sec_13f.get("thirteenf_available", False),
        sector_weights=sec_13f.get("sector_weights", {}),
        # ...
    )
```

#### 2.4 Update chapter field expectations

```python
"investment_strategy": {
    "fields": [
        "fund_name", "fund_type", "geography", "asset_class",
        "holdings_source",                    # NEW — "nport" | "13f" | None
        "nport_available", "nport_sector_weights", "nport_asset_allocation",  # NEW
        "thirteenf_available", "sector_weights",  # kept for overlay
    ],
    "providers": ["YFinance", "SEC EDGAR N-PORT", "SEC EDGAR 13F"],  # N-PORT first
    "primary_provider": "SEC EDGAR N-PORT",
},
```

---

### Phase 3: Prompt Pivot (Investment Strategy)

**Goal:** The LLM sees the correct holdings data for each fund type.

#### 3.1 Rewrite `investment_strategy.j2`

Replace the 13F-only block with a DisclosureMatrix-aware template:

```jinja2
{# PRIMARY: N-PORT fund-level holdings (registered US funds) #}
{% if nport_available %}
## Fund Portfolio Holdings (SEC N-PORT, {{ nport_report_date }})

### Asset Allocation
{% for asset_class, pct in nport_asset_allocation.items() %}
- {{ asset_class }}: {{ "%.1f"|format(pct * 100) }}%
{% endfor %}

### Sector Exposure
{% for sector, weight in nport_sector_weights.items() %}
- {{ sector }}: {{ "%.1f"|format(weight * 100) }}%
{% endfor %}

### Top 10 Holdings (by % of NAV)
{% for h in nport_top_holdings[:10] %}
- {{ h.name }} ({{ h.cusip }}): {{ "%.2f"|format(h.pct_of_nav) }}%
{% endfor %}

{% if fund_style %}
### Style Classification (derived from holdings)
- Equity %: {{ fund_style.equity_pct }}% | Fixed Income %: {{ fund_style.fi_pct }}%
- Cap: {{ fund_style.cap_label }} | Style: {{ fund_style.style_label }}
{% endif %}

Cross-reference the stated investment strategy against these fund-level portfolio holdings.
{% endif %}

{# OVERLAY: 13F manager firm context (supplementary, not primary) #}
{% if thirteenf_available and not nport_available %}
## Manager Firm 13F Holdings (proxy — no fund-level N-PORT available)
⚠ This fund does not file N-PORT. The following sector allocation is from the
manager firm's aggregated 13F-HR filing and represents ALL assets under the firm's
discretion, not this specific fund's portfolio.
{% for sector, weight in sector_weights.items() %}
- {{ sector }}: {{ "%.1f"|format(weight * 100) }}%
{% endfor %}
{% elif thirteenf_available and nport_available %}
## Manager Firm 13F Context (supplementary)
The manager firm's aggregate 13F sector allocation is provided for context.
This represents the firm's overall equity positioning across all managed funds.
{% for sector, weight in sector_weights.items() %}
- {{ sector }}: {{ "%.1f"|format(weight * 100) }}%
{% endfor %}
{% endif %}
```

#### 3.2 Update `chapters.py` user content builder

Replace the 13F-hardcoded block with DisclosureMatrix branching:

```python
if chapter_tag == "investment_strategy":
    if evidence_context.get("nport_available"):
        parts.append("\n## Fund Holdings (N-PORT)")
        # ... append nport_sector_weights, asset_allocation, top_holdings
    elif evidence_context.get("thirteenf_available"):
        parts.append("\n## Manager Firm 13F Holdings (proxy)")
        # ... append sector_weights with caveat
```

---

### Phase 4: Manager Assessment Semantic Fix

**Goal:** Chapter 3 focuses on the fund's PM team; firm governance moves to Chapter 7.

#### 4.1 Split `manager_assessment.j2` scope

**Keep in Chapter 3 (Manager Assessment):**
- Fund-level track record (already from `fund_risk_metrics` ✅)
- Fund AUM trajectory (from N-PORT `total_net_assets` time series, or `nav_timeseries`)
- Strategy consistency (from N-PORT style drift, not 13F firm drift)
- Fund-specific team (future: parse N-PORT `<managementInfo>`)

**Move to Chapter 7 (Operational DD):**
- Firm AUM growth (`sec_managers.aum_total`) → already partially there
- Organizational strength (ADV Items 8, 10) → already partially there
- Fee structure (ADV Item 5) → move to Chapter 6 (Fee Analysis) or Chapter 7
- Disciplinary history (ADV Item 9) → already in Chapter 7

#### 4.2 Add fund-level style drift to EvidencePack

```python
# From sec_fund_style_snapshots — computed from N-PORT
fund_style_history: list[dict] = field(default_factory=list)  # time series of style classifications
fund_style_drift_detected: bool = False  # True if style changed in last 6 months
```

This replaces 13F sector drift as the primary "strategy consistency" signal for Chapter 3.

#### 4.3 Update `manager_assessment.j2` preamble

```jinja2
{# Current (wrong): "SEC-reported regulatory AUM figures above as authoritative" #}
{# Fixed: distinguish fund AUM from firm AUM #}

{% if nport_available %}
## Fund-Level Context
- Fund AUM: {{ fund_aum_usd | format_currency }}
- Fund Style: {{ fund_style.cap_label }} {{ fund_style.style_label }}
{% if fund_style_drift_detected %}
⚠ Style drift detected: fund classification changed in the last 6 months.
{% endif %}
{% endif %}

## Manager Firm Context (supplementary)
- Firm Total AUM: {{ adv_aum_history.aum_total | format_currency }}
- Funds Under Management: {{ adv_funds | length }}
```

---

### Phase 5: Populate `has_13f_overlay` in DisclosureMatrix

**Goal:** The catalog correctly signals when 13F data is available as supplementary context.

#### 5.1 Update catalog SQL

In `catalog_sql.py`, for `registered_us` universe:

```sql
-- Check if the fund's manager also files 13F
CASE WHEN EXISTS (
    SELECT 1 FROM sec_13f_holdings h
    JOIN sec_managers m ON m.cik = h.cik
    WHERE m.crd_number = srf.crd_number
    AND h.report_date >= CURRENT_DATE - INTERVAL '6 months'
) THEN true ELSE false END AS has_13f_overlay
```

This populates the currently-dead `has_13f_overlay` field, enabling the frontend to show a "Manager 13F Overlay" panel in the fund detail view.

---

### Phase 6: Tests & Validation

#### 6.1 Unit tests for `gather_sec_nport_data()`

- Test with known registered fund CIK → returns sector weights, asset allocation, top holdings
- Test with unknown CIK → returns empty dict
- Test drift detection between consecutive months

#### 6.2 Integration test for evidence branching

- Test registered fund → `holdings_source="nport"`, N-PORT fields populated
- Test private fund → `holdings_source=None`, 13F overlay only
- Test fund with no SEC data → graceful degradation

#### 6.3 Prompt regression test

- Verify `investment_strategy.j2` renders N-PORT block for registered fund
- Verify 13F proxy block renders for private fund
- Verify overlay block renders when both are available

---

### Execution Order & Dependencies

```
Phase 1 (Foundation)     ──── No dependencies, can start immediately
    │
Phase 2 (Evidence Pack)  ──── Depends on Phase 1 (needs sec_cik resolution)
    │
Phase 3 (Prompts)        ──── Depends on Phase 2 (needs new EvidencePack fields)
Phase 4 (Manager Assess) ──── Depends on Phase 2 (needs fund_style fields)
Phase 5 (Catalog)        ──── Independent, can parallel with Phase 3-4
    │
Phase 6 (Tests)          ──── Depends on Phases 2-5
```

**Estimated scope:** 6 files modified, ~300 lines added, ~50 lines removed. No new tables. No migrations if using JSONB convention. One migration (0043) if adding `sec_cik` column.

---

## 8. File Reference Index

### Files That Need Changes

| File | Change Type | Phase |
|------|-----------|-------|
| `vertical_engines/wealth/dd_report/evidence_pack.py` | Add N-PORT fields, update chapter expectations | 2 |
| `vertical_engines/wealth/dd_report/sec_injection.py` | Add `gather_sec_nport_data()`, refactor `_build_evidence()` | 2 |
| `vertical_engines/wealth/dd_report/dd_report_engine.py` | Branch on DisclosureMatrix in `_build_evidence()` | 2 |
| `vertical_engines/wealth/dd_report/chapters.py` | Branch user content on `holdings_source` | 3 |
| `vertical_engines/wealth/prompts/dd_chapters/investment_strategy.j2` | N-PORT primary, 13F overlay | 3 |
| `vertical_engines/wealth/prompts/dd_chapters/manager_assessment.j2` | Scope to fund PM, not firm | 4 |
| `app/domains/wealth/queries/catalog_sql.py` | Populate `has_13f_overlay` | 5 |

### Files That Are Already Correct (No Changes)

| File | Why Correct |
|------|------------|
| `vertical_engines/wealth/monitoring/strategy_drift_scanner.py` | Fund-level via `fund_risk_metrics` |
| `vertical_engines/wealth/monitoring/drift_monitor.py` | Fund-level DTW vs benchmark |
| `vertical_engines/wealth/peer_group/service.py` | Fund-level via `instrument_screening_metrics` |
| `vertical_engines/wealth/peer_group/peer_matcher.py` | Matches instruments by type/strategy |
| `app/domains/wealth/routes/sec_analysis.py` | Correctly scoped: `/sec/managers/` for 13F |
| `app/domains/wealth/routes/sec_funds.py` | Correctly scoped: `/sec/funds/` for N-PORT |
| `app/domains/wealth/schemas/catalog.py` | DisclosureMatrix already has the right fields |
| `vertical_engines/wealth/prompts/dd_chapters/operational_dd.j2` | Firm governance is correct scope |

### Data Models (Reference)

| Model | Table | Scope | Primary Key |
|-------|-------|-------|-------------|
| `Sec13fHolding` | `sec_13f_holdings` | Firm (adviser CIK) | `(report_date, cik, cusip)` |
| `SecNportHolding` | `sec_nport_holdings` | Fund (fund CIK) | `(report_date, cik, cusip)` |
| `SecRegisteredFund` | `sec_registered_funds` | Fund catalog | `cik` |
| `SecFundStyleSnapshot` | `sec_fund_style_snapshots` | Fund style | `(cik, report_date)` |
| `SecManager` | `sec_managers` | Firm/RIA | `crd_number` |
| `SecManagerFund` | `sec_manager_funds` | Firm's Schedule D | FK to `crd_number` |
| `SecManagerTeam` | `sec_manager_team` | Firm's personnel | FK to `crd_number` |
| `Instrument` | `instruments_universe` | Tenant fund | `instrument_id` |
| `FundRiskMetrics` | `fund_risk_metrics` | Per-fund quant | `(instrument_id, calc_date)` |
| `InstrumentScreeningMetrics` | `instrument_screening_metrics` | Per-fund screening | `(instrument_id, calc_date)` |

---

*Generated by architecture audit — 2026-03-26*
