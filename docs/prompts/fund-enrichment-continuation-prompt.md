# Fund Enrichment Integration — Continuation Prompt

## Context

The fund enrichment integration plan (`docs/plans/2026-03-28-fund-enrichment-integration-plan.md`) has been **partially executed**. All 5 phases of the original plan are implemented in code. This session handles post-implementation tasks: tests, CLAUDE.md update, and two small pending items (2C partial, 4B optional).

## What Was Implemented (DO NOT re-implement)

All code changes below are already committed to the working tree. Read first, verify, then proceed to the pending tasks.

### Phase 1 — DD Report Fund Enrichment (DONE)
- `backend/vertical_engines/wealth/dd_report/sec_injection.py` — `gather_fund_enrichment()` added (~130 lines). Queries SecRegisteredFund (N-CEN), SecFundClass (XBRL), SecEtf/SecBdc/SecMoneyMarketFund (vehicle-specific). Also includes insider sentiment integration via `insider_queries.py`.
- `backend/vertical_engines/wealth/dd_report/evidence_pack.py` — `fund_enrichment: dict[str, Any]` field added to `EvidencePack`. `_CHAPTER_FIELD_EXPECTATIONS` updated for 7 chapters. `build_evidence_pack()` accepts `fund_enrichment` kwarg. `to_context()` includes it.
- `backend/vertical_engines/wealth/dd_report/dd_report_engine.py` — `_run_enrichment()` added as 6th parallel worker. `ThreadPoolExecutor(max_workers=6)`. `gather_fund_enrichment` imported and wired.
- `backend/vertical_engines/wealth/dd_report/chapters.py` — `_build_user_content()` extended: fee_analysis (share class tables, N-CEN fees, ETF tracking diff), investment_strategy/executive_summary/recommendation (strategy_label, classification flags), operational_dd (securities lending, swing pricing, broker research), manager_assessment (strategy_label).
- `backend/vertical_engines/wealth/prompts/dd_chapters/fee_analysis.j2` — XBRL fee table + N-CEN fee blocks added.
- `backend/vertical_engines/wealth/prompts/dd_chapters/investment_strategy.j2` — SEC classification section added.
- `backend/vertical_engines/wealth/prompts/dd_chapters/operational_dd.j2` — Operational flags section added.

### Phase 2 — Import Enrichment + Fee Drag (DONE)
- `backend/app/domains/wealth/routes/screener.py` (`import_sec_security`) — Multi-table lookup: SecRegisteredFund → SecFundClass (by ticker) → SecEtf (by ticker). Enriches attributes with: `strategy_label`, `is_index`, `is_target_date`, `is_fund_of_fund`, `expense_ratio_pct`, `holdings_count`, `portfolio_turnover_pct`, `sec_crd`, `fund_inception_date`. Best-class selection: ticker match first, then highest `net_assets`.
- `backend/app/domains/wealth/services/esma_import_service.py` — `strategy_label` from `EsmaFund` added to attributes.
- `backend/vertical_engines/wealth/fee_drag/service.py` — `_extract_fees()` now prefers `expense_ratio_pct` (XBRL) over `management_fee_pct` (manual).
- **2C PARTIAL**: SecBdc and SecMoneyMarketFund ticker fallback NOT yet added to `import_sec_security`. Only SecRegisteredFund → SecFundClass → SecEtf chain exists.

### Phase 3 — Quant Fee Adjustment + Peer Group (DONE)
- `backend/app/domains/wealth/services/quant_queries.py` — Fee-adjusted expected returns when `config.fee_adjustment.enabled`. Queries Instrument by IDs, subtracts `expense_ratio_pct / 100.0` from annual returns.
- `backend/vertical_engines/wealth/peer_group/peer_matcher.py` — `_fund_key_levels()` now uses `attrs.get("strategy_label") or attrs.get("strategy", "unknown")`.

### Phase 4 — Manager Spotlight (DONE, 4B pending)
- `backend/vertical_engines/wealth/manager_spotlight.py` — `_gather_fund_data()` calls `gather_fund_enrichment()`. `_build_user_content()` renders strategy_label, expense_ratio, classification flags.
- **4B NOT DONE**: Fact sheet fee comparison table (optional enhancement) — not implemented. `fact_sheet_engine.py` already picks up enriched attributes automatically via Phase 2A.

### Phase 5 — Watchlist + Scoring (DONE)
- `backend/vertical_engines/wealth/watchlist/service.py` — `check_enrichment_changes()` static method added. Detects expense ratio increases >5bps and strategy_label changes.
- `backend/quant_engine/scoring_service.py` — **Lipper fully removed** (provider never contracted). `lipper_score` param removed, `lipper_rating` weight removed. Replaced by `fee_efficiency` as **default** component (weight 0.10). `insider_sentiment` is opt-in.

### Lipper Cleanup (DONE)
- `backend/app/domains/wealth/models/lipper.py` — DELETED (empty stub)
- `backend/app/domains/wealth/schemas/lipper.py` — DELETED (empty stub)
- `backend/app/domains/wealth/models/__init__.py` — `LipperRating` export removed
- `backend/app/domains/wealth/services/quant_queries.py` — `get_fund_lipper_score()` removed, `LIPPER_SCORE_FIELDS` removed, `settings` import removed
- `backend/app/core/config/settings.py` — `feature_lipper_enabled` removed
- `calibration/config/scoring.yaml` — Updated to 6-weight model (fee_efficiency replaces lipper_rating)
- `backend/tests/e2e_smoke_test.py` — Positional arg fixed (removed lipper_score)

### Current Scoring Model (6 default components, sum = 1.0)
```
return_consistency:    0.20  (NAV return 1Y, normalized)
risk_adjusted_return:  0.25  (Sharpe 1Y, normalized)
drawdown_control:      0.20  (Max drawdown 1Y, normalized)
information_ratio:     0.15  (IR 1Y, normalized)
flows_momentum:        0.10  (pre-computed RSI/OBV, passed by caller)
fee_efficiency:        0.10  (SEC XBRL expense_ratio_pct → 0%=100, 2%=0, None=50 neutral)
insider_sentiment:     opt-in (SEC Form 345, weight > 0 in config to activate)
```

---

## Pending Tasks

### Task 1: Add SecBdc + SecMoneyMarketFund to import chain (Phase 2C completion)

In `backend/app/domains/wealth/routes/screener.py` → `import_sec_security()`, after the SecEtf fallback block, add:

```python
# Fallback: search sec_bdcs by ticker
if not reg_fund and not enrichment_attrs.get("sec_universe"):
    from app.shared.models import SecBdc
    bdc_row = (await db.execute(
        select(SecBdc).where(SecBdc.ticker == sec_row.ticker).limit(1),
    )).scalar_one_or_none()
    if bdc_row:
        enrichment_attrs["sec_universe"] = "bdc"
        enrichment_attrs["strategy_label"] = bdc_row.strategy_label
        if bdc_row.net_operating_expenses is not None:
            enrichment_attrs["expense_ratio_pct"] = float(bdc_row.net_operating_expenses)
        enrichment_attrs["investment_focus"] = bdc_row.investment_focus
        enrichment_attrs["is_externally_managed"] = bdc_row.is_externally_managed

# Fallback: search sec_money_market_funds by ticker
if not reg_fund and not enrichment_attrs.get("sec_universe"):
    from app.shared.models import SecMoneyMarketFund
    mmf_row = (await db.execute(
        select(SecMoneyMarketFund).where(SecMoneyMarketFund.ticker == sec_row.ticker).limit(1),
    )).scalar_one_or_none()
    if mmf_row:
        enrichment_attrs["sec_universe"] = "money_market"
        enrichment_attrs["strategy_label"] = mmf_row.strategy_label
        enrichment_attrs["mmf_category"] = mmf_row.mmf_category
```

Read the current `import_sec_security()` to find the exact insertion point (after the `SecEtf` fallback, before `if reg_fund:`).

### Task 2: Write unit tests for `gather_fund_enrichment()`

**File:** `backend/tests/test_fund_enrichment.py` (new)

Test `gather_fund_enrichment()` from `vertical_engines.wealth.dd_report.sec_injection`. Use `unittest.mock.MagicMock` for sync Session. Tests to write:

1. `test_returns_empty_when_no_cik` — `fund_cik=None` → `{}`
2. `test_returns_empty_when_wrong_universe` — `sec_universe="ucits_eu"` → `{}`
3. `test_registered_fund_basic` — mock SecRegisteredFund with strategy_label, is_index, etc. Verify dict structure.
4. `test_share_classes_populated` — mock SecFundClass rows, verify `share_classes` list populated with expense_ratio_pct etc.
5. `test_etf_vehicle_specific` — mock SecRegisteredFund with series_id + SecEtf → verify `vehicle_specific.type == "etf"`.
6. `test_bdc_vehicle_specific` — same pattern for BDC.
7. `test_mmf_vehicle_specific` — same pattern for MMF.
8. `test_exception_returns_empty` — mock DB to raise → verify `{}` returned.

Follow existing test patterns in `backend/tests/test_dd_report*.py`. Use `@pytest.mark.parametrize` where appropriate.

### Task 3: Write unit tests for scoring changes

**File:** `backend/tests/test_scoring_fee_efficiency.py` (new)

Test the updated `compute_fund_score()`:

1. `test_default_weights_sum_to_one` — verify `sum(_DEFAULT_SCORING_WEIGHTS.values()) == 1.0`
2. `test_fee_efficiency_with_low_er` — `expense_ratio_pct=0.035` → `fee_efficiency` component near 98.25
3. `test_fee_efficiency_with_high_er` — `expense_ratio_pct=1.52` → `fee_efficiency` component near 24.0
4. `test_fee_efficiency_none_defaults_neutral` — `expense_ratio_pct=None` → `fee_efficiency == 50.0`
5. `test_fee_efficiency_2pct_is_zero` — `expense_ratio_pct=2.0` → `fee_efficiency == 0.0`
6. `test_insider_sentiment_opt_in_only` — without `insider_sentiment` weight in config, param is ignored
7. `test_insider_sentiment_with_weight` — config with `insider_sentiment: 0.05`, verify component included
8. `test_no_lipper_parameter` — verify `lipper_score` is NOT a parameter (inspect signature)
9. `test_backward_compat_positional` — `compute_fund_score(metrics, 50.0, None)` still works (flows_momentum as 1st positional)

### Task 4: Write unit test for watchlist enrichment detection

**File:** add to existing `backend/tests/test_watchlist.py`

Test `WatchlistService.check_enrichment_changes()`:

1. `test_fee_increase_above_threshold` — ER from 0.50 to 0.60 (+10bps) → alert with direction="enrichment_change"
2. `test_fee_increase_below_threshold` — ER from 0.50 to 0.54 (+4bps) → no alert
3. `test_strategy_label_change` — "US Large Cap Growth" → "US Large Cap Value" → alert
4. `test_no_previous_snapshot` — empty previous → no alerts
5. `test_mixed_changes` — one fund with fee increase, one with strategy change → 2 alerts

### Task 5: Update CLAUDE.md

Add the following updates to CLAUDE.md:

1. **Scoring model section** — document the 6-component model replacing the old 6-component (with Lipper). Note fee_efficiency is default, insider_sentiment is opt-in. Note Lipper was removed (provider never contracted).

2. **Fund enrichment at import** — document that `import_sec_security()` now enriches attributes with N-CEN flags + XBRL fees. Mention the multi-table lookup chain: SecRegisteredFund → SecFundClass → SecEtf → SecBdc → SecMoneyMarketFund.

3. **Screener layer 1 config** — document that enriched attributes enable new screening rules without code changes:
   ```yaml
   max_expense_ratio_pct: 1.5
   excluded_is_index: true
   excluded_is_target_date: true
   ```

4. **Migration head** — verify current migration head is correct in CLAUDE.md (should be `0067_insider_transactions` based on the worker/manifest changes seen).

5. **Workers table** — add `form345_ingestion` worker entry if not already present.

6. **Global tables list** — add `sec_insider_transactions`, `sec_insider_sentiment` (materialized view) if not already listed.

7. **Remove** any remaining references to Lipper as a planned integration. Keep only historical references in docs/plans/ and docs/brainstorms/.

### Task 6: Verify `make check` passes

Run `make lint && make typecheck && make test` after all changes. The 8 pre-existing failures are expected:
- `test_data_providers_e2e.py` — 4 IMF/BIS external API tests (network-dependent)
- `test_manifest_freshness.py` — 4 manifest byte-equal tests (need regeneration)

Zero new failures allowed from enrichment changes.

---

## Execution Order

1. Task 1 (2C completion) — quick, ~15 lines
2. Task 2 (enrichment tests) — new file
3. Task 3 (scoring tests) — new file
4. Task 4 (watchlist tests) — append to existing
5. Task 5 (CLAUDE.md) — documentation
6. Task 6 (verify) — `make check`

Prepare a new prompt to execute the next phase in a new fresh session.
