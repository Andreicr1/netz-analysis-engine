# Fund Enrichment Integration Plan

**Status:** COMPLETED 2026-03-28

## Implementation Summary

| Phase | Arquivo | Mudança |
|---|---|---|
| 1A | `dd_report/sec_injection.py` | `gather_fund_enrichment()` — SecRegisteredFund, SecFundClass, SecEtf/SecBdc/SecMoneyMarketFund |
| 1B | `dd_report/evidence_pack.py` | `fund_enrichment` field, `to_context()`, `build_evidence_pack()`, `_CHAPTER_FIELD_EXPECTATIONS` (7 chapters) |
| 1C | `dd_report/dd_report_engine.py` | `_run_enrichment()` como 6º worker paralelo (ThreadPoolExecutor bumped para 6) |
| 1D | `dd_report/chapters.py` | Share class fee tables → `fee_analysis`; strategy/flags → `investment_strategy`/`executive_summary`/`recommendation`; operational → `operational_dd`; strategy → `manager_assessment` |
| 1E | `prompts/dd_chapters/fee_analysis.j2`, `investment_strategy.j2`, `operational_dd.j2` | Blocos condicionais para enrichment data |
| 2A | `routes/screener.py` (`import_sec_security`) | Multi-table lookup (SecRegisteredFund → SecFundClass → SecEtf); attributes: `strategy_label`, `is_index`, `is_target_date`, `expense_ratio_pct`, `holdings_count`, `portfolio_turnover_pct`, `sec_crd` |
| 2B | `esma_import_service.py` | `strategy_label` de EsmaFund adicionado ao attributes |
| 2D | `fee_drag/service.py` | Prefere `expense_ratio_pct` (XBRL) sobre `management_fee_pct` (manual) |
| 3A | `services/quant_queries.py` | Retornos esperados ajustados por fee quando `config.fee_adjustment.enabled` |
| 3B | `peer_group/peer_matcher.py` | Prefere `strategy_label` sobre `strategy` nas chaves de peer group |
| 4A | `manager_spotlight.py` | `_gather_fund_data()` chama `gather_fund_enrichment()`; Fund Identity block renderiza strategy, expense ratio, classification flags |
| 5A | `watchlist/service.py` | `check_enrichment_changes()` — detecta expense ratio increases >5bps e mudanças de strategy_label |
| 5B | `scoring_service.py` | `expense_ratio_pct: float \| None = None` adicionado a `compute_fund_score()` — componente `fee_drag` opt-in |

---

## Context

Migrations 0063–0066 enriched SEC/ESMA fund tables with strategy_label (37 categories), N-CEN classification flags (27 columns), XBRL per-share-class fee data (11 columns), and dedicated ETF/BDC/MMF tables. The embedding worker already consumes all this data for `wealth_vector_chunks`, but **no analytical engine** (DD report, screener, optimizer, fee drag, fact sheet) uses it yet. The gap: fee_analysis chapters say "Not available", scoring treats index funds and active equally, and the optimizer uses gross returns without fee adjustment.

---

## Phase 1 — DD Report Fund Enrichment (Tier 1, ~200 LOC)

**Goal:** Inject structured SEC fund data into DD report chapters so LLM has real fee, classification, and strategy context.

### 1A. New gather functions in `sec_injection.py`

**File:** `backend/vertical_engines/wealth/dd_report/sec_injection.py`

Add two new functions following existing `gather_sec_*` pattern:

```python
def gather_fund_enrichment(
    db: Session,
    *,
    fund_cik: str | None,
    sec_universe: str | None,
) -> dict[str, Any]:
```

**Logic:**
- If `sec_universe == "registered_us"` and `fund_cik`:
  1. Query `SecRegisteredFund` by CIK → extract: `strategy_label`, `is_index`, `is_non_diversified`, `is_target_date`, `is_fund_of_fund`, `is_master_feeder`, `management_fee`, `net_operating_expenses`, `is_sec_lending_authorized`, `did_lend_securities`, `has_swing_pricing`, `did_pay_broker_research`, `monthly_avg_net_assets`, `fund_inception_date`
  2. Query `SecFundClass` by CIK → extract per class: `class_id`, `ticker`, `expense_ratio_pct`, `advisory_fees_paid`, `net_assets`, `holdings_count`, `portfolio_turnover_pct`, `avg_annual_return_pct`
- If fund matches `SecEtf` (by series_id from registered fund): extract `tracking_difference_gross`, `tracking_difference_net`, `index_tracked`, `creation_unit_size`
- If fund matches `SecBdc`: extract `investment_focus`, `is_externally_managed`
- If fund matches `SecMoneyMarketFund`: extract `mmf_category`, `weighted_avg_maturity`, `weighted_avg_life`, `seven_day_gross_yield`, `pct_daily_liquid_latest`
- Return empty dict `{}` if nothing found (safe fallback)

**Return dict structure:**
```python
{
    "enrichment_available": True,
    "strategy_label": "US Large Cap Growth",
    "classification": {
        "is_index": False,
        "is_non_diversified": False,
        "is_target_date": False,
        "is_fund_of_fund": False,
        "is_master_feeder": False,
    },
    "operational": {
        "is_sec_lending_authorized": True,
        "did_lend_securities": True,
        "has_swing_pricing": False,
        "did_pay_broker_research": True,
    },
    "ncen_fees": {
        "management_fee": 0.75,
        "net_operating_expenses": 0.95,
    },
    "share_classes": [
        {
            "class_id": "C000012345",
            "ticker": "ACMGX",
            "expense_ratio_pct": 0.65,
            "advisory_fees_paid": 5.2,
            "net_assets": 334.7,
            "holdings_count": 247,
            "portfolio_turnover_pct": 45.0,
            "avg_annual_return_pct": 8.25,
        }
    ],
    "vehicle_specific": {  # only if ETF/BDC/MMF
        "type": "etf",
        "tracking_difference_net": 0.12,
    },
    "monthly_avg_net_assets": 11970000000.0,
    "fund_inception_date": "2005-06-15",
}
```

### 1B. Extend EvidencePack

**File:** `backend/vertical_engines/wealth/dd_report/evidence_pack.py`

Add new fields to frozen dataclass:
```python
fund_enrichment: dict[str, Any] = field(default_factory=dict)
```

Update `_CHAPTER_FIELD_EXPECTATIONS`:
- `fee_analysis`: add `fund_enrichment.share_classes`, `fund_enrichment.ncen_fees` — provider "SEC N-CSR XBRL / N-CEN"
- `investment_strategy`: add `fund_enrichment.strategy_label`, `fund_enrichment.classification` — provider "SEC N-CEN"
- `operational_dd`: add `fund_enrichment.operational`, `fund_enrichment.classification` — provider "SEC N-CEN"
- `manager_assessment`: add `fund_enrichment.strategy_label` — provider "SEC N-CEN"
- `executive_summary`: add `fund_enrichment.strategy_label` — provider "SEC N-CEN"

Update `build_evidence_pack()` to accept `fund_enrichment` kwarg.

Update `compute_source_metadata()` so chapters with enrichment data report `structured_data_complete` or `structured_data_partial` accordingly.

### 1C. Wire into `_build_evidence()`

**File:** `backend/vertical_engines/wealth/dd_report/dd_report_engine.py`

Add `gather_fund_enrichment` as 6th parallel worker in `ThreadPoolExecutor(max_workers=5)` → bump to 6:
```python
def _run_enrichment() -> dict:
    return gather_fund_enrichment(db, fund_cik=fund_cik, sec_universe=sec_universe)
```

Pass result to `build_evidence_pack(..., fund_enrichment=results["enrichment"])`.

### 1D. Update chapter user content

**File:** `backend/vertical_engines/wealth/dd_report/chapters.py` → `_build_user_content()`

For `fee_analysis`:
```python
enrichment = evidence_context.get("fund_enrichment", {})
if enrichment.get("share_classes"):
    parts.append("## Share Class Fee Data (SEC N-CSR XBRL)")
    for sc in enrichment["share_classes"]:
        parts.append(f"- {sc['ticker'] or sc['class_id']}: ER {sc['expense_ratio_pct']}%, ...")
if enrichment.get("ncen_fees"):
    parts.append(f"Management Fee: {enrichment['ncen_fees']['management_fee']}%")
```

For `investment_strategy`:
```python
if enrichment.get("strategy_label"):
    parts.append(f"SEC Strategy Classification: {enrichment['strategy_label']}")
if enrichment.get("classification"):
    flags = [k for k, v in enrichment["classification"].items() if v]
    if flags:
        parts.append(f"Fund Flags: {', '.join(flags)}")
```

For `operational_dd`:
```python
if enrichment.get("operational"):
    ops = enrichment["operational"]
    if ops.get("is_sec_lending_authorized"):
        parts.append(f"Securities Lending: {'Active' if ops['did_lend_securities'] else 'Authorized, not active'}")
    if ops.get("has_swing_pricing"):
        parts.append("Swing Pricing: Yes")
```

For `executive_summary` and `recommendation`:
```python
if enrichment.get("strategy_label"):
    parts.append(f"Strategy: {enrichment['strategy_label']}")
```

### 1E. Update prompt templates

**Files:** `backend/vertical_engines/wealth/prompts/dd_chapters/fee_analysis.j2`, `investment_strategy.j2`, `operational_dd.j2`

Add conditional blocks for new data:
- `{% if fund_enrichment.share_classes %}` → render fee table
- `{% if fund_enrichment.strategy_label %}` → provide strategy context
- `{% if fund_enrichment.operational %}` → render operational flags

Prompts already have `structured_data_complete/partial/absent` logic — the enrichment will flip these to `partial` or `complete`.

---

## Phase 2 — Import Enrichment + Screener + Fee Drag (Tier 1-2, ~150 LOC)

**Goal:** Populate `Instrument.attributes` with enriched data at import time so screener and fee drag use XBRL/N-CEN data.

### 2A. Enrich SEC import route

**File:** `backend/app/domains/wealth/routes/screener.py` → `import_sec_security()`

After looking up `sec_registered_funds` by ticker:
1. Query `SecFundClass` for the matched CIK → get `expense_ratio_pct`, `holdings_count`, `portfolio_turnover_pct`
2. Read N-CEN flags from `SecRegisteredFund`: `is_index`, `is_target_date`, `is_fund_of_fund`, `strategy_label`, `fund_inception_date`
3. Store in `attributes`:
```python
attributes["expense_ratio_pct"] = best_class.expense_ratio_pct  # cheapest class for ticker
attributes["strategy_label"] = fund.strategy_label
attributes["is_index"] = fund.is_index
attributes["is_target_date"] = fund.is_target_date
attributes["fund_inception_date"] = str(fund.fund_inception_date) if fund.fund_inception_date else None
attributes["holdings_count"] = best_class.holdings_count
attributes["portfolio_turnover_pct"] = best_class.portfolio_turnover_pct
```

**Best class selection:** Match by ticker first; if multiple, use class with highest `net_assets`.

### 2B. Enrich ESMA import route

**File:** `backend/app/domains/wealth/routes/screener.py` or `esma_import_service.py`

After looking up `esma_funds` by ISIN:
1. Read `strategy_label` from `esma_funds`
2. Store in `attributes["strategy_label"]`

### 2C. Multi-table SEC import (ETF/BDC/MMF)

**File:** `backend/app/domains/wealth/routes/screener.py` → `import_sec_security()`

Currently only queries `sec_registered_funds`. Extend lookup chain:
1. `sec_registered_funds` (existing)
2. If not found → `sec_fund_classes` ticker search (covers all registered)
3. If not found → `sec_etfs` by ticker
4. If not found → `sec_bdcs` by ticker
5. If not found → `sec_money_market_funds` by ticker

Each table branch populates table-specific attributes (e.g., ETF: `tracking_difference_net`, MMF: `mmf_category`).

### 2D. Fee Drag reads expense_ratio_pct

**File:** `backend/vertical_engines/wealth/fee_drag/service.py` → `_extract_fees()`

Current: reads `attributes["management_fee_pct"]`
Change: prioritize `attributes["expense_ratio_pct"]` (XBRL, authoritative) over `management_fee_pct` (manual):

```python
mgmt = max(0.0, _safe_float(
    attributes.get("expense_ratio_pct")       # XBRL (preferred)
    or attributes.get("management_fee_pct")   # manual fallback
    or 0.0
))
```

This is a 3-line change. All callers remain untouched.

### 2E. Screener layer 1 — no code change needed

The evaluator already supports `min_*`, `max_*`, `excluded_*` patterns dynamically from attributes. Once attributes are enriched at import (2A), config can use:
```yaml
layer1:
  fund:
    max_expense_ratio_pct: 1.5
    excluded_is_index: true
    excluded_is_target_date: true
```

No code change — just config. Document in CLAUDE.md.

---

## Phase 3 — Quant Fee Adjustment (Tier 2, ~80 LOC)

**Goal:** Optimizer uses net-of-fee expected returns.

### 3A. Adjust expected returns pre-optimizer

**File:** `backend/app/domains/wealth/services/quant_queries.py` → `compute_fund_level_inputs()`

After computing `expected_returns` dict:
```python
# Fee adjustment (optional, controlled by config)
if config.get("fee_adjustment", {}).get("enabled"):
    for fid in fund_ids:
        instrument = instruments_by_id.get(fid)
        if instrument and instrument.attributes:
            er = instrument.attributes.get("expense_ratio_pct")
            if er is not None:
                expected_returns[fid] -= float(er) / 100.0  # pct → decimal
```

### 3B. Peer group uses strategy_label

**File:** `backend/vertical_engines/wealth/peer_group/peer_matcher.py` → `_fund_key_levels()`

Current: `attrs.get("strategy", "unknown")`
Change: prefer `strategy_label` over `strategy`:
```python
strategy = str(attrs.get("strategy_label") or attrs.get("strategy", "unknown"))
```

Single-line change. Peer keys become more granular automatically when `strategy_label` is populated at import.

---

## Phase 4 — Manager Spotlight + Fact Sheet (Tier 2-3, ~60 LOC)

### 4A. Manager Spotlight enrichment

**File:** `backend/vertical_engines/wealth/manager_spotlight.py` → `_gather_fund_data()`

After reading `Instrument`, add SEC enrichment lookup:
```python
fund_cik = attrs.get("sec_cik")
if fund_cik:
    enrichment = gather_fund_enrichment(db, fund_cik=fund_cik, sec_universe=attrs.get("sec_universe"))
    fund_data["strategy_label"] = enrichment.get("strategy_label")
    fund_data["expense_ratio_pct"] = (enrichment.get("share_classes") or [{}])[0].get("expense_ratio_pct")
    fund_data["classification"] = enrichment.get("classification", {})
```

Reuse `gather_fund_enrichment` from Phase 1A (same function, no duplication).

Update `_build_user_content()` to include strategy_label, classification flags, and expense ratio in the Fund Identity block.

### 4B. Fact Sheet institutional — fee comparison table

**File:** `backend/vertical_engines/wealth/fact_sheet/fact_sheet_engine.py` → `_compute_fee_drag()`

Currently reads `fund.attributes` per fund in portfolio. With enriched attributes (Phase 2A), this automatically picks up XBRL expense ratios without any code change.

Optional enhancement: add a fee comparison table in the institutional PDF showing per-fund expense ratios.

---

## Phase 5 — Watchlist + Scoring (Tier 2-3, ~100 LOC)

### 5A. Watchlist enrichment change detection

**File:** `backend/vertical_engines/wealth/watchlist/service.py`

Extend `check_transitions()` to detect enrichment attribute changes:
- Compare current `attributes["expense_ratio_pct"]` vs `previous_snapshot`
- Compare `strategy_label` changes
- Emit `TransitionAlert` with `direction="enrichment_change"` for fee increases >5bps or strategy drift

### 5B. Scoring fee awareness

**File:** `backend/quant_engine/scoring_service.py`

**IMPLEMENTADO:** Parâmetro opcional `expense_ratio_pct` adicionado a `compute_fund_score()`.

**Nota:** `lipper_score` não existe no modelo e não foi implementado. A assinatura
real foi lida antes de editar — apenas `expense_ratio_pct` foi adicionado:

```python
def compute_fund_score(
    metrics: RiskMetrics,
    flows_momentum_score: float = 50.0,  # parâmetros existentes preservados
    config: dict | None = None,
    expense_ratio_pct: float | None = None,  # ADICIONADO
) -> tuple[float, dict[str, float]]:
```

Se fornecido e config tem weight `"fee_drag"` > 0:
```python
if expense_ratio_pct is not None and weights.get("fee_drag", 0) > 0:
    fee_score = max(0, 100 - expense_ratio_pct * 50)  # 2% ER → score 0
    components["fee_drag"] = fee_score * weights["fee_drag"]
```

Backward-compatible (default None = comportamento inalterado).

---

## Files Modified (Summary)

| Phase | File | Change |
|-------|------|--------|
| 1A | `dd_report/sec_injection.py` | +`gather_fund_enrichment()` (~80 lines) |
| 1B | `dd_report/evidence_pack.py` | +`fund_enrichment` field, update expectations |
| 1C | `dd_report/dd_report_engine.py` | Wire enrichment into parallel gather |
| 1D | `dd_report/chapters.py` | Extend `_build_user_content()` for 5 chapters |
| 1E | `prompts/dd_chapters/*.j2` | Conditional blocks for enrichment data |
| 2A | `routes/screener.py` | Enrich SEC import with XBRL/N-CEN |
| 2B | `routes/screener.py` or `esma_import_service.py` | Add strategy_label to ESMA import |
| 2C | `routes/screener.py` | Multi-table lookup (ETF/BDC/MMF) |
| 2D | `fee_drag/service.py` | Prefer expense_ratio_pct over management_fee_pct |
| 3A | `services/quant_queries.py` | Fee-adjusted expected returns |
| 3B | `peer_group/peer_matcher.py` | Prefer strategy_label in peer keys |
| 4A | `manager_spotlight.py` | Add enrichment to fund data |
| 4B | `fact_sheet/fact_sheet_engine.py` | Optional fee comparison table |
| 5A | `watchlist/service.py` | Enrichment change detection |
| 5B | `scoring_service.py` | Optional fee_drag scoring component |

## Verification

1. **Unit tests**: Each `gather_*` function gets a test with mocked DB session
2. **Integration test**: `test_dd_report_with_enrichment` — generate report for a registered_us fund with known CIK, verify `fund_enrichment` populated in evidence
3. **Manual**: Import a SEC fund (e.g., VINIX), verify attributes contain `expense_ratio_pct=0.035`, `strategy_label`, `is_index`
4. **Regression**: `make check` (lint + typecheck + 2900+ tests) must pass after each phase
5. **Fee drag**: Import fund with known XBRL ER, run fee_drag, verify it uses XBRL value
6. **Screener**: Configure `max_expense_ratio_pct: 0.5` in layer1, verify VINIX (0.035%) passes, high-fee fund fails
