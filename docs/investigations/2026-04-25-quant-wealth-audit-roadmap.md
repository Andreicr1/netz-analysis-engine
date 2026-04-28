# Quant + Wealth Engine Audit Roadmap

Date: 2026-04-25

Scope:

- `backend/quant_engine`
- `backend/vertical_engines/wealth`

Goal: identify mathematically material and institutionally material bugs in the quant and wealth engines without exhausting agent context. This roadmap intentionally splits the audit into bounded sessions. Each session should be run independently, with a strict output format, and then consolidated in a separate synthesis pass.

---

## 1. Operating Principles

This is an institutional quant audit, not a style review.

Agents must prioritize:

1. Incorrect mathematics.
2. Unit, scale, sign, annualization, compounding, or convention mismatches.
3. Unsafe defaults and fallbacks that can bias risk, ranking, allocation, or reporting.
4. Data leakage, look-ahead bias, stale data, survivorship bias, and missing-data optimism.
5. Runtime config divergence from seeds, docs, migrations, and hardcoded fallbacks.
6. Duplicated/legacy implementations that can diverge silently.
7. Missing tests for high-risk invariants.

Agents must avoid:

1. Cosmetic refactors.
2. Naming/style findings unless they create incorrect interpretation.
3. Feature proposals.
4. Broad architectural rewrites.
5. Claiming a finding without concrete evidence.

Each finding must be testable. If a finding cannot be converted into a deterministic test or invariant check, mark it as an open question rather than a confirmed bug.

---

## 2. Global Mathematical Contracts

Before auditing individual modules, agents must evaluate code against these global contracts. If code intentionally differs, the module must document why.

### 2.1 Return Convention

Canonical questions:

- Is the input a price/NAV level, simple return, log return, excess return, or percent return?
- Is the output daily, monthly, annualized, or horizon-specific?
- Are simple and log returns mixed in the same matrix?
- Are returns represented as fractions (`0.05`) or percentages (`5.0`)?

Expected institutional contract:

- Price/NAV levels must be converted to returns exactly once.
- Simple and log returns must not be mixed in a single covariance, factor, optimization, or scoring panel.
- Annualization must be explicit: daily mean usually `*252`; daily volatility usually `*sqrt(252)`; covariance usually `*252`.
- Any use of monthly returns must annualize with `12` or `sqrt(12)`, not `252`.

### 2.2 Risk Sign Convention

Canonical questions:

- Is drawdown stored as a negative return (`-0.20`) or positive loss magnitude (`0.20`)?
- Is VaR/CVaR a negative return or positive loss?
- Does "higher is better" hold for normalized scores?

Expected institutional contract:

- Report-facing risk should usually be positive loss magnitude.
- Optimization can use either convention, but every boundary must convert explicitly.
- Scoring components must be monotonic in the intended direction.

### 2.3 Time and Data Alignment

Canonical questions:

- Is the lookback window inclusive or exclusive of `as_of_date`?
- Is any future data visible in rolling stats, factor fits, peer ranks, or reports?
- Are market holidays handled at level side or return side?
- Are stale macro/FRED/SEC fields treated defensively?

Expected institutional contract:

- No look-ahead in backtests, factor fits, scores, regime, DD reports, or model portfolios.
- Level-side forward fill is acceptable only with tight limits and only before computing returns.
- Return-side forward fill is usually dangerous.
- Missing critical risk data should not produce optimistic output.

### 2.4 Portfolio Construction Units

Canonical questions:

- Are expected returns `mu` and covariance `sigma` on the same horizon?
- Are CVaR limits annual or daily?
- Does `lambda_risk` match objective scale?
- Are weights fractions summing to 1.0?

Expected institutional contract:

- `mu`, `sigma`, and objective risk terms must share the same time scale.
- CVaR conversion between annual and daily must be explicit and tested.
- Risk aversion must be strictly positive and bounded defensively.
- Final weights must satisfy sum, min/max, block, and mandate constraints within numerical tolerance.

### 2.5 Config Precedence

Expected source hierarchy:

1. DB org override.
2. DB default.
3. YAML seed fallback.
4. Hardcoded fallback.

Audit rule:

- Runtime config is canonical. Docs and YAML are seed/reference unless explicitly loaded at runtime.
- Any divergence between runtime defaults, seeds, docs, and migrations must be classified as a config finding.

### 2.6 Institutional Fallbacks

Expected fallback posture:

- Use last-known-good when available.
- If no reliable last-known-good exists, fail closed or defensive for risk-sensitive flows.
- Never default to optimistic risk, favorable ranking, or permissive allocation because data is missing.

---

## 3. Severity Framework

Use two severity dimensions for every finding.

### 3.1 Math Severity

- Critical: Can invert a risk/allocation decision, create materially wrong portfolio weights, or produce invalid optimization/risk output.
- High: Wrong scale, sign, annualization, leakage, or formula in a core metric.
- Medium: Biases ranking or reporting but likely bounded.
- Low: Documentation/test gap or edge-case ambiguity with limited production effect.

### 3.2 Institutional Severity

- Critical: Could cause mandate breach, materially misleading IC/client report, unsuitable recommendation, or fiduciary risk.
- High: Could materially alter approved allocation, fund ranking, risk status, or alerting.
- Medium: Could mislead an analyst but is unlikely to auto-drive an action.
- Low: Internal inconsistency with limited user-facing or allocation impact.

### 3.3 Required Finding Format

Every agent must use this exact format:

```text
ID:
Title:
Files/lines:
Math severity:
Institutional severity:
Type: math | data | config | institutional | test-gap | legacy-divergence
Evidence:
Expected invariant:
Why it is wrong:
Recommended fix:
Minimum test:
Breaking-change risk:
Confidence: high | medium | low
Open questions:
```

---

## 4. Context Budget Rules

Each session should target one conceptual layer and no more than 3-8 implementation files unless the files are tiny.

Agent instructions:

- Read only the scoped files plus direct callers/tests needed to prove findings.
- Do not audit the whole repository from one session.
- If a session identifies a dependency outside scope, record it under "handoff", do not chase indefinitely.
- Prefer `rg` for callers and existing tests.
- Stop after producing findings and proposed tests. Do not implement unless explicitly assigned a remediation session.

Recommended session output limit:

- Maximum 15 findings.
- Maximum 5 high-priority recommendations.
- Include "No finding" for checked invariants that passed.

---

## 5. Audit Sessions

### Session 00 - Map Runtime Boundaries and Data Contracts

Purpose: build a map of data flow before individual formula audits.

Primary files:

- `backend/quant_engine/__init__.py`
- `backend/vertical_engines/wealth/shared_protocols.py`
- `backend/vertical_engines/wealth/quant_analyzer.py`
- `backend/vertical_engines/wealth/fund_analyzer.py`

Search targets:

- calls into `quant_engine`
- model dataclasses/schemas
- config injection
- return/risk/scoring payloads

Audit questions:

- Which modules are pure functions vs DB/service orchestrators?
- Which modules pass config in vs read defaults directly?
- Which numeric fields cross the boundary into reports, scores, or portfolios?
- Are field names precise about units and sign?

Deliverables:

- Data-flow map.
- List of canonical numeric fields and inferred units.
- Handoff list for sessions 01-13.

---

### Session 01 - Returns, Drawdown, Rolling, Backtest Basics

Primary files:

- `backend/quant_engine/return_statistics_service.py`
- `backend/quant_engine/drawdown_service.py`
- `backend/quant_engine/rolling_service.py`
- `backend/quant_engine/backtest_service.py`
- `backend/quant_engine/portfolio_metrics_service.py`

Audit questions:

- Are returns simple/log/percent consistently handled?
- Are rolling windows look-ahead safe?
- Is drawdown sign consistent across modules?
- Are annualized stats using the correct frequency?
- Do empty/short series produce neutral, defensive, or misleading outputs?

High-value invariants:

- Constant positive return series should have zero drawdown.
- A larger loss path must not produce better drawdown score.
- Reversing time order should change rolling/backtest outputs; if not, suspect leakage.
- Annualized volatility of daily returns should scale by `sqrt(252)`.

Expected tests:

- deterministic synthetic path with known max drawdown
- short-history behavior
- NaN/missing data behavior

---

### Session 02 - CVaR, Tail Risk, EVT, GARCH

Primary files:

- `backend/quant_engine/cvar_service.py`
- `backend/quant_engine/ru_cvar_lp.py`
- `backend/quant_engine/tail_var_service.py`
- `backend/quant_engine/garch_service.py`
- `backend/quant_engine/evt/pot_gpd.py`
- `backend/quant_engine/evt/diagnostics.py`

Audit questions:

- Is CVaR represented as positive loss or negative return?
- Are daily vs annual CVaR conversions explicit and correct?
- Are tails selected in the correct direction?
- Does the Rockafellar-Uryasev LP match the empirical CVaR convention?
- Are EVT thresholds fitted without look-ahead?
- Does GARCH output volatility on the intended horizon?
- Are fallback paths more permissive than primary paths?

High-value invariants:

- Worse left-tail returns must increase loss CVaR.
- More restrictive CVaR limit cannot allow a riskier accepted portfolio.
- EVT should not fit when threshold exceedance count is too low.
- GARCH variance must be non-negative and finite.

Expected tests:

- small hand-computable CVaR example
- sign-convention boundary test
- annual/daily conversion test
- degenerate all-zero returns test

---

### Session 03 - Covariance, Correlation, Factor Models, IPCA/PCA

Primary files:

- `backend/quant_engine/factor_model_service.py`
- `backend/quant_engine/factor_model_pca.py`
- `backend/quant_engine/factor_model_ipca_service.py`
- `backend/quant_engine/ipca/preprocessing.py`
- `backend/quant_engine/ipca/fit.py`
- `backend/quant_engine/ipca/drift_monitor.py`
- `backend/quant_engine/correlation_regime_service.py`
- `backend/quant_engine/portfolio_correlation_service.py`

Audit questions:

- Are factor returns built from levels or returns correctly?
- Are factor spreads calculated only when both legs are authoritative?
- Are covariance matrices symmetric and PSD after shrinkage/fallback?
- Are IPCA characteristics standardized/ranked cross-sectionally?
- Are train/test splits time-safe?
- Are PCA diagnostics accidentally passed where covariance is expected?
- Are correlation regimes based on contemporaneous or future data?

High-value invariants:

- Covariance matrix must be symmetric within tolerance.
- Eigenvalues should be non-negative after PSD correction.
- Factor panel must not repeat returns via return-side ffill.
- IPCA preprocessing should be cross-sectional by date, not global across time.

Expected tests:

- PSD/symmetry tests
- factor leg missing/stale tests
- IPCA no-leak split test
- synthetic factor covariance with known rank

---

### Session 04 - Optimizer, Constraints, Risk Budgeting, Rebalance

Primary files:

- `backend/quant_engine/optimizer_service.py`
- `backend/quant_engine/risk_budgeting_service.py`
- `backend/quant_engine/rebalance_service.py`
- `backend/quant_engine/mandate_risk_aversion.py`
- `backend/quant_engine/allocation_template_service.py`

Audit questions:

- Are objective terms DCP-compliant and economically scaled?
- Is `lambda_risk` strictly positive in every path?
- Do constraints apply to all assets/blocks, including unmapped assets?
- Are fallback solvers gated by realized constraint checks?
- Does rebalance distinguish drift, turnover, tax/friction, and mandate breach?
- Are failed optimizations surfaced as degraded/failure rather than plausible weights?

High-value invariants:

- Weights sum to 1 within tolerance.
- All min/max bounds are respected.
- Increasing risk aversion should not increase variance when returns equal.
- If all expected returns are equal, optimizer should prefer lower risk under MV objective.

Expected tests:

- infeasible constraint case
- zero/negative risk aversion override case
- solver fallback constraint validation
- equal-return minimum-risk behavior

---

### Session 05 - Black-Litterman, Views, Expected Returns

Primary files:

- `backend/quant_engine/black_litterman_service.py`
- `backend/quant_engine/benchmark_composite_service.py`
- `backend/quant_engine/monte_carlo_service.py`
- `backend/quant_engine/data_commons_service.py`

Relevant callers:

- `backend/app/domains/wealth/services/quant_queries.py`

Audit questions:

- Are `mu`, `sigma`, `tau`, and view covariance on compatible scales?
- Does confidence mapping behave monotonically?
- Are certainty/near-certainty views numerically regularized without changing economics?
- Is legacy `compute_bl_returns` still used in production?
- Are priors explicit or implicitly derived with hidden assumptions?
- Are no-view cases returning the intended prior/equilibrium?

High-value invariants:

- Higher confidence should move posterior closer to view.
- Empty views should return prior/equilibrium as documented.
- Relative views should be invariant to common return shifts.
- `tau` should not silently imply an absurd sample size unless documented.

Expected tests:

- one-asset absolute view closed-form sanity
- confidence monotonicity
- no-view behavior
- legacy vs multi-view single-view parity, if deprecation is planned

---

### Session 06 - Regime, Macro, TAA, Stress Severity

Primary files:

- `backend/quant_engine/regime_service.py`
- `backend/quant_engine/regional_macro_service.py`
- `backend/quant_engine/macro_snapshot_builder.py`
- `backend/quant_engine/stress_severity_service.py`
- `backend/quant_engine/taa_band_service.py`
- `backend/quant_engine/allocation_proposal_service.py`
- `backend/quant_engine/fred_service.py`
- `backend/quant_engine/fiscal_data_service.py`

Audit questions:

- Are regime defaults defensive when data is missing?
- Are stale macro series excluded or used optimistically?
- Are one-sided signals economically intentional?
- Does dynamic weighting create unintended single-signal dominance?
- Is hysteresis applied at the stateful caller rather than pure classifier?
- Are TAA bands clamped by IPS/mandate limits?

High-value invariants:

- Insufficient critical signals should not produce optimistic regime.
- Extreme stress in multiple signals should classify defensive/crisis.
- Stale macro data should not influence current regime.
- TAA output must remain inside hard mandate bounds.

Expected tests:

- no-data fallback
- stale-data fallback
- energy shock positive/negative tail policy
- TAA clamp against hard constraints

---

### Session 07 - Scoring, Normalization, Peer Comparison

Primary files:

- `backend/quant_engine/scoring_service.py`
- `backend/quant_engine/scoring_components/robust_sharpe.py`
- `backend/quant_engine/fixed_income_analytics_service.py`
- `backend/quant_engine/cash_analytics_service.py`
- `backend/quant_engine/alternatives_analytics_service.py`
- `backend/quant_engine/peer_group_service.py`
- `backend/quant_engine/peer_comparison_service.py`
- `backend/quant_engine/talib_momentum_service.py`
- `backend/quant_engine/expense_ratio_validator.py`

Audit questions:

- Are component scores monotonic in the intended direction?
- Are weights summing to 1 in every asset class/profile?
- Are docs/seeds/runtime defaults divergent?
- Are missing data defaults neutral, penalizing, or optimistic?
- Are components duplicated or collinear beyond intentional design?
- Are peer medians/ranks calculated in the correct peer universe?
- Are percent/fraction expense ratios handled consistently?

High-value invariants:

- Increasing expense ratio should not improve fee score.
- Increasing drawdown should not improve drawdown control.
- Higher credit beta should only improve score if monotonic policy is intentional.
- Missing critical metric should not score above peer median.

Expected tests:

- monotonicity/property tests per component
- asset-class dispatch tests
- weight-sum tests
- config override precedence tests

---

### Session 08 - Wealth Screener, Watchlist, Elite Ranking

Primary files:

- `backend/vertical_engines/wealth/screener/service.py`
- `backend/vertical_engines/wealth/screener/quant_metrics.py`
- `backend/vertical_engines/wealth/screener/layer_evaluator.py`
- `backend/vertical_engines/wealth/watchlist/service.py`
- `backend/vertical_engines/wealth/watchlist/transition_detector.py`
- `backend/vertical_engines/wealth/elite_ranking/allocation_source.py`

Audit questions:

- Are screening layers eliminatory vs ranking-only as intended?
- Is hysteresis correctly applied to watchlist/status transitions?
- Do status transitions avoid flapping?
- Are quant scores percentile-ranked within correct peer group?
- Are stale or missing quant metrics downgraded appropriately?
- Does elite ranking accidentally mix regimes, profiles, or universes?

High-value invariants:

- A fund failing hard eligibility must not pass because score is high.
- Previous watchlist status should require buffer to flip.
- Missing risk metrics should not create elite status.

Expected tests:

- previous-status hysteresis table
- layer hard-fail precedence
- missing metric downgrade
- peer-universe isolation

---

### Session 09 - Wealth Routes & Workers Integration

Inserted 2026-04-28 after smoke-test Caminho A (Q91/Q92 validation) revealed that the original roadmap §1 scope (`backend/quant_engine` + `backend/vertical_engines/wealth`) excludes the integration layer where 4 P1/P2 bugs were caught in a 4-call HTTP run (Q93 already shipped). Routes and workers must be audited before Session 10 because Session 10 onwards exercise this layer end-to-end.

Primary files:

- `backend/app/domains/wealth/routes/screener.py`
- `backend/app/domains/wealth/routes/universe.py`
- `backend/app/domains/wealth/routes/dd_reports.py`
- `backend/app/domains/wealth/routes/model_portfolios.py`
- `backend/app/domains/wealth/routes/fact_sheets.py`
- `backend/app/domains/wealth/routes/monitoring.py`
- `backend/app/domains/wealth/routes/rebalancing.py`
- `backend/app/domains/wealth/routes/instruments.py`
- `backend/app/domains/wealth/workers/universe_sync.py`
- `backend/app/domains/wealth/workers/risk_calc.py`
- `backend/app/domains/wealth/workers/strategy_reclassification.py`
- `backend/app/domains/wealth/workers/esma_aum_sync.py`
- `backend/app/domains/wealth/workers/portfolio_eval.py`
- `backend/app/domains/wealth/workers/construction_run_executor.py`
- `backend/app/domains/wealth/workers/benchmark_ingest.py`
- `backend/app/domains/wealth/workers/drift_check.py`
- `backend/app/domains/wealth/workers/regime_fit.py`
- `backend/app/core/db/audit.py`
- `backend/app/core/runtime/single_flight.py`
- `backend/app/core/runtime/provider_gate.py`

Audit questions:

- Are mutating routes idempotent? Re-running with the same input must not violate UNIQUE constraints (re-runs must mark prior `is_current=true` rows as `false` before INSERT).
- Do route handlers respect `org_id: uuid.UUID = Depends(get_org_id)` consistently? Are there annotation lies (`org_id: str`) hiding implicit casts that crash at runtime?
- Are `@idempotent` + triple-layer dedup (Redis + SingleFlightLock + `pg_advisory_xact_lock`) applied to every mutating route as required by Stability Charter §3?
- Do query-string params silently ignore unknown keys (e.g. `?text=` typo accepted as no-op)? Should Pydantic strict mode reject unknown query params?
- Are workers race-safe when they depend on data populated by another worker (e.g. `_deactivate_no_nav` running before NAV ingestion arrives)?
- Do worker upsert paths preserve `is_active=true` on re-upsert, or do they silently flip back to a stale state (Q91 surfaced this for UCITS; SEC ETFs verified affected — extent unknown)?
- Are advisory lock IDs deterministic (`zlib.crc32`, never `hash()`)? Does every worker `unlock` in `finally`?
- Does each worker emit `degraded=True` when downstream data is unavailable, instead of silently producing zero/null outputs?
- Are SSE-emitting routes wrapped in the Job-or-Stream pattern (202 + `/jobs/{id}/stream`) when expected p95 > 500ms?
- Do route handlers leak prompt content to the client (Netz IP) or expose internal `entity_type`/`action` strings that should be `CLIENT_VISIBLE_TYPES`-allowlisted?
- Are RLS policies actually enforced, or has TimescaleDB columnstore disabled them silently (audit drift confirmed in Q92 on `audit_events`)?
- Do mutating routes check `_require_investment_role(actor)` / `_require_ic_role(actor)` consistently across the 17 wealth route modules?

High-value invariants:

- Re-running any mutating route with the same payload must be deterministic (no UNIQUE violations, no duplicate audit rows, no double-billing of any external provider).
- Worker that flips `is_active=false` must be reversible by the upsert path that re-discovers the row with valid data — drift between worker invariants must be impossible.
- `get_org_id`'s return type (`uuid.UUID | None`) must match the route handler annotation everywhere; any `str` cast on the result is a bug.
- Audit events for global pipelines must persist with `organization_id=NULL` (Q92), and tenant pipelines must never produce orphan rows (`allow_global=False` raises).
- Route response payloads must never carry sensitive prompt strings, internal advisory lock IDs, raw SQL, or unsanitized error tracebacks.
- Workers must release advisory locks even on unhandled exceptions (test: kill mid-run, next run must succeed).

Known seed findings (smoke-test catches, 2026-04-28 — discovery agents must verify and find siblings):

- F-Q91-followup-A: `universe_sync._deactivate_no_nav` flips `is_active=false` for any instrument without NAV, and the ESMA/SEC re-upsert paths do not reset it when NAV later arrives. Q91 reactivated UCITS one-time only. SEC ETFs (e.g. SPY, 2516 NAV rows but `is_active=false`) confirmed affected. Recurrence is certain on next universe_sync run.
- F-Q93: `routes/universe.py:fast_approve` annotation lied (`org_id: str = Depends(get_org_id)`) and the body called `uuid.UUID(org_id)`. Already fixed but agents must sweep all 13+ route handlers with the same annotation pattern for the same footgun.
- F-screener-idempotency: `routes/screener.py:trigger_screening` (line 837 `db.commit()`) violates `uq_screening_results_current` on re-run. The route does not flip prior rows' `is_current=false` before INSERT. Pattern likely repeats in any route that writes to a table with a partial-unique-current index.
- F-catalog-strict-params: `routes/screener.py:get_catalog` accepts `?text=` (unknown param) silently as no filter, returning the full 52k-row table. Pydantic Query strictness not enforced; same pattern likely in other GET endpoints with many optional filters.

Expected tests:

- Idempotency: re-run each mutating route 3× with identical payload, assert no exception + identical state.
- Annotation contract: assert `Depends(get_org_id)` is annotated `uuid.UUID | None` everywhere via static check (AST scan).
- Worker reactivation: `universe_sync` round-trip — deactivate row, re-upsert with NAV available, assert `is_active=true`.
- Strict query params: GET routes reject unknown query parameters with 422.
- Audit surface: every mutating route writes audit row; every global pipeline writes with `organization_id=NULL`; orphan tenant audit raises ValueError.
- Lock release: every worker has `try/finally` around `pg_try_advisory_lock`/`unlock`.
- RLS posture: snapshot test for `pg_class.relrowsecurity` per table; flag drift from migration declarations.

Non-goals (out of scope for Session 09 — defer to other sessions):

- Quant math correctness (Sessions 01-08 cover this).
- Frontend formatter discipline (separate frontend audit).
- DD report content quality (Session 14).
- Migration chain integrity (Session 15).

---

### Session 10 - Wealth Model Portfolio, Mandate Fit, Validation

Primary files:

- `backend/vertical_engines/wealth/model_portfolio/portfolio_builder.py`
- `backend/vertical_engines/wealth/model_portfolio/construction_advisor.py`
- `backend/vertical_engines/wealth/model_portfolio/validation_gate.py`
- `backend/vertical_engines/wealth/model_portfolio/state_machine.py`
- `backend/vertical_engines/wealth/model_portfolio/stress_scenarios.py`
- `backend/vertical_engines/wealth/model_portfolio/track_record.py`
- `backend/vertical_engines/wealth/model_portfolio/block_mapping.py`
- `backend/vertical_engines/wealth/mandate_fit/service.py`
- `backend/vertical_engines/wealth/mandate_fit/constraint_evaluator.py`

Audit questions:

- Are hard constraints separated from soft preferences?
- Does validation gate block mandate breaches before approval?
- Are stress scenarios applied with correct sign and scale?
- Are state transitions auditable and non-bypassable?
- Does construction advisor double-count risk/return signals?
- Are block mappings complete and non-overlapping?

High-value invariants:

- Invalid portfolio cannot enter approved state.
- Hard mandate breach must override attractive score.
- Stress loss sign must be consistent in display and validation.
- Block weights must not disappear during mapping.

Expected tests:

- state transition denial cases
- hard vs soft constraint precedence
- stress scenario known-vector test
- block mapping coverage test

---

### Session 11 - Rebalancing, Monitoring, Drift, Alerts

Primary files:

- `backend/vertical_engines/wealth/rebalancing/service.py`
- `backend/vertical_engines/wealth/rebalancing/weight_proposer.py`
- `backend/vertical_engines/wealth/rebalancing/preview_service.py`
- `backend/vertical_engines/wealth/rebalancing/impact_analyzer.py`
- `backend/vertical_engines/wealth/monitoring/alert_engine.py`
- `backend/vertical_engines/wealth/monitoring/drift_monitor.py`
- `backend/vertical_engines/wealth/monitoring/overlap_scanner.py`
- `backend/vertical_engines/wealth/monitoring/strategy_drift_scanner.py`

Audit questions:

- Are proposed trades constrained by mandate and current holdings?
- Are preview impacts using the same risk conventions as construction?
- Are alerts deduplicated and severity-ranked correctly?
- Are drift calculations time-aligned and benchmark-consistent?
- Are overlap and concentration metrics based on current holdings, not stale snapshots?

High-value invariants:

- Rebalance proposal must not worsen a hard breach unless explicitly flagged.
- Drift cannot be negative when absolute deviation is intended.
- Duplicate alerts should not flood state transitions.

Expected tests:

- rebalance from known current/target weights
- preview sign convention test
- alert dedupe test
- stale holdings rejection/degraded test

---

### Session 12 - Attribution, Correlation, Active Share, Diversification

Primary files:

- `backend/quant_engine/active_share_service.py`
- `backend/quant_engine/attribution_service.py`
- `backend/quant_engine/diversification_service.py`
- `backend/quant_engine/drift_service.py`
- `backend/quant_engine/style_analysis.py`
- `backend/vertical_engines/wealth/attribution/service.py`
- `backend/vertical_engines/wealth/attribution/returns_based.py`
- `backend/vertical_engines/wealth/attribution/holdings_based.py`
- `backend/vertical_engines/wealth/attribution/brinson_fachler.py`
- `backend/vertical_engines/wealth/attribution/benchmark_proxy.py`
- `backend/vertical_engines/wealth/attribution/ipca_rail.py`
- `backend/vertical_engines/wealth/correlation/service.py`

Audit questions:

- Are attribution effects summing to excess return?
- Are allocation/selection/interaction terms signed correctly?
- Are holdings-based and returns-based attribution clearly separated?
- Is active share calculated against aligned holdings and benchmarks?
- Are correlation/diversification scores robust to missing/short data?

High-value invariants:

- Brinson components should reconcile to active return within tolerance.
- Active share must be between 0 and 1.
- Correlation matrix must be symmetric with diagonal 1.

Expected tests:

- hand-computed Brinson example
- active share toy portfolio
- correlation matrix validity
- missing benchmark behavior

---

### Session 13 - Asset Universe, Peer Group, Fee Drag, Fund Approval

Primary files:

- `backend/vertical_engines/wealth/asset_universe/universe_service.py`
- `backend/vertical_engines/wealth/asset_universe/fund_approval.py`
- `backend/vertical_engines/wealth/asset_universe/eviction_service.py`
- `backend/vertical_engines/wealth/peer_group/service.py`
- `backend/vertical_engines/wealth/peer_group/peer_matcher.py`
- `backend/vertical_engines/wealth/fee_drag/service.py`

Audit questions:

- Are instruments uniquely identified across ticker/ISIN/CUSIP/share class?
- Can a fund enter the approved universe without required due diligence?
- Are eviction rules defensive and auditable?
- Are peer groups homogeneous enough for percentile scoring?
- Is fee drag using percent/fraction convention correctly?

High-value invariants:

- Same share class should not appear as multiple competing instruments.
- Different share classes should not be collapsed when fees differ materially.
- Approval requires all hard gates.
- Higher fee should increase fee drag.

Expected tests:

- identity collision test
- approval hard-gate test
- fee percent/fraction test
- peer matcher boundary cases

---

### Session 14 - DD Reports, Fact Sheets, Client/IC Reporting

Primary files:

- `backend/vertical_engines/wealth/dd_report/quant_injection.py`
- `backend/vertical_engines/wealth/dd_report/peer_injection.py`
- `backend/vertical_engines/wealth/dd_report/sec_injection.py`
- `backend/vertical_engines/wealth/dd_report/confidence_scoring.py`
- `backend/vertical_engines/wealth/dd_report/evidence_pack.py`
- `backend/vertical_engines/wealth/dd_report/dd_report_engine.py`
- `backend/vertical_engines/wealth/fact_sheet/fact_sheet_engine.py`
- `backend/vertical_engines/wealth/fact_sheet/chart_builder.py`
- `backend/vertical_engines/wealth/monthly_report/monthly_report_engine.py`
- `backend/vertical_engines/wealth/long_form_report/long_form_report_engine.py`
- `backend/vertical_engines/wealth/critic/service.py`

Audit questions:

- Are quant metrics converted to user-facing units correctly?
- Are confidence scores penalizing missing/stale/low-quality evidence?
- Are generated narratives prevented from overstating uncertain metrics?
- Do reports distinguish estimated, stale, missing, and verified data?
- Do charts invert risk signs or mix percent/fraction labels?

High-value invariants:

- Missing evidence must lower confidence.
- Reported CVaR/drawdown must match engine sign convention.
- A metric marked stale/degraded must not be presented as current.

Expected tests:

- quant injection unit conversion test
- confidence score missing-evidence test
- report payload snapshot for known metrics
- critic catches macro/quant contradiction

---

### Session 15 - Cross-Cutting Config, Seeds, Docs, Migrations

Purpose: run only after sessions 01-13 produce module findings.

Primary files/areas:

- `backend/app/core/config`
- `calibration/config`
- `calibration/seeds`
- `backend/app/core/db/migrations/versions`
- `CLAUDE.md`
- `docs/audits`
- `docs/investigations`

Search targets:

- `scoring_weights`
- `risk_aversion`
- `cvar_limit`
- `regime_thresholds`
- `portfolio_profiles`
- `default`
- `fallback`
- `deprecated`
- `legacy`

Audit questions:

- Do migrations seed values that differ from YAML/docs/hardcoded fallbacks?
- Do docs claim a runtime behavior that ConfigService does not deliver?
- Are runtime configs visible to clients when they should be internal?
- Are hardcoded fallbacks still reachable in production?
- Are multiple defaults competing for the same institutionally material setting?

High-value invariants:

- Config precedence must be test-covered.
- Every institutionally material default must have one canonical owner.
- Seed docs must be marked seed/reference if not runtime.

Expected tests:

- ConfigService default vs YAML fallback tests
- migration seed smoke tests
- hardcoded fallback reachability tests
- doc/seed/runtime consistency checklist

---

## 6. Consolidation Pass

After all sessions complete, run a separate synthesis session. Do not ask an agent to both audit and synthesize the whole system in one pass.

Inputs:

- All session outputs.
- Existing `docs/audits/audit-findings-quant.txt`.
- Existing `docs/audits/audit-validation-quant.md`.

Consolidation tasks:

1. Deduplicate findings.
2. Merge related bugs into root-cause groups.
3. Assign remediation priority.
4. Identify dependency order.
5. Convert top findings into implementation tickets.
6. Identify missing tests that should be written before fixes.

Recommended priority labels:

- P0: can cause materially wrong allocation/risk/report decision today.
- P1: material quant bug but bounded or not directly actioned.
- P2: institutional consistency, test gap, or config drift.
- P3: cleanup/deprecation.

Recommended consolidated table:

```text
Priority:
Root cause:
Affected sessions:
Affected files:
Institutional impact:
Recommended fix:
Tests required before/with fix:
Migration/config implications:
Owner:
```

---

## 7. Standard Agent Prompt

Use this prompt for each session, replacing the bracketed fields.

```text
You are an institutional quant auditor for asset and wealth management software.

Audit scope:
[SESSION NAME]

Files:
[FILE LIST]

Audit only:
1. mathematical correctness;
2. unit, scale, sign, annualization, compounding, and horizon consistency;
3. data leakage, look-ahead bias, stale data, and unsafe missing-data behavior;
4. config/runtime/seed/doc divergence;
5. institutional risks that can affect allocation, ranking, alerts, DD reports, or client/IC interpretation;
6. missing tests for high-risk invariants.

Do not do style review.
Do not propose unrelated features.
Do not refactor.
Read direct callers/tests only when needed to prove a finding.

Use these global contracts:
- returns must not mix simple/log/percent/fraction conventions silently;
- risk sign conventions must be explicit at module boundaries;
- mu/sigma/CVaR/objectives must share the correct time scale;
- missing critical risk data must not produce optimistic output;
- runtime ConfigService is canonical over docs/YAML unless YAML is the runtime fallback;
- every confirmed bug must have a minimum deterministic test.

For each finding, use exactly:

ID:
Title:
Files/lines:
Math severity:
Institutional severity:
Type:
Evidence:
Expected invariant:
Why it is wrong:
Recommended fix:
Minimum test:
Breaking-change risk:
Confidence:
Open questions:

Also include:
- Checked invariants with no finding.
- Handoff items outside this session's scope.
- Top 3 remediation priorities for this session.
```

---

## 8. Remediation Session Template

Use only after a finding is accepted.

```text
You are implementing a narrow remediation for an accepted quant audit finding.

Finding:
[PASTE FINDING]

Constraints:
- Keep changes scoped to the affected module and tests.
- Preserve public behavior unless the finding requires a behavior change.
- Add deterministic tests for the stated invariant.
- Do not combine unrelated fixes.
- If config/defaults change, update the canonical config owner and note migration implications.
- If behavior changes are institutionally material, add audit/logging/degraded-state handling where appropriate.

Deliver:
- changed files;
- behavior before/after;
- tests added;
- remaining risks.
```

---

## 9. Suggested Execution Order

Recommended order if agents are limited:

1. Session 00 - Runtime boundaries.
2. Session 01 - Returns/drawdown/rolling.
3. Session 02 - CVaR/tail/GARCH/EVT.
4. Session 04 - Optimizer/risk aversion/constraints.
5. Session 05 - Black-Litterman/expected returns.
6. Session 06 - Regime/macro/TAA.
7. Session 07 - Scoring/normalization/peer comparison.
8. Session 09 - Routes & Workers Integration.
9. Session 10 - Model portfolio/mandate validation.
10. Session 14 - DD/reporting surfaces.
11. Session 15 - Config/docs/seeds cross-cutting.

Recommended parallelization:

- Sessions 01, 02, 07 can run in parallel after Session 00.
- Sessions 04 and 05 can run in parallel after Session 03 or with a limited boundary map from Session 00.
- Sessions 08, 11, 12, 13, 14 can run in parallel after their quant dependencies are known.
- Session 15 should run near the end.
- Consolidation should run last.

---

## 10. Known High-Risk Themes To Watch

These are not pre-judged findings; they are themes agents should actively test.

1. Simple vs log return mixing.
2. Daily vs annual CVaR and volatility conversion.
3. Drawdown/CVaR sign conventions crossing from engine to reports.
4. Optimistic defaults when data is missing.
5. ConfigService runtime values diverging from YAML/docs/hardcoded fallbacks.
6. Scoring components that are monotonic when economic logic is peaked, or vice versa.
7. Duplicate factors creating hidden overweighting.
8. Solver fallback accepting numerically invalid portfolios.
9. BL posterior scale mismatches between `mu`, `sigma`, `tau`, and views.
10. Regime flapping when pure classifier output is persisted without hysteresis.
11. Stale macro/SEC data entering current decisions.
12. Peer groups mixing incompatible instruments/share classes.
13. Report narratives presenting estimated/degraded metrics as verified facts.

