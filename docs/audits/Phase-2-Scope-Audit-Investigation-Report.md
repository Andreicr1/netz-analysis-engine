Phase 2 Scope Audit — Investigation Report

  Status: COMPLETE
  Date: 2026-04-11
  Auditor: Gemini CLI

  Section A: Schema / Migrations

  ┌────────────┬────────┬─────────────┬──────────────────┐    
  │ Item       │ Found  │ Location    │ Notes            │    
  ├────────────┼────────┼─────────────┼──────────────────┤    
  │ A.1        │ organi │ c3d4e5f6a7b │ Confirmed        │    
  │ fund_risk_ │ zation │ 8 L104      │ current          │    
  │ metrics    │ _id    │             │ segmentation     │    
  │ segmentby  │        │             │ matches master   │    
  │            │        │             │ plan claim.      │    
  │ A.2        │ DEFAUL │ 0002_wealth │ No explicit      │    
  │ nav_timese │ T (7   │ _domain L70 │ interval found   │    
  │ ries chunk │ days)  │             │ in migrations;   │    
  │            │        │             │ defaults to 7    │    
  │            │        │             │ days in          │    
  │            │        │             │ TimescaleDB.     │    
  │            │        │             │ Master plan      │    
  │            │        │             │ claim of 1mo is  │    
  │            │        │             │ likely an        │    
  │            │        │             │ environmental    │    
  │            │        │             │ observation, not │    
  │            │        │             │ a codebase       │    
  │            │        │             │ definition.      │    
  │ A.3        │ N/A    │ 0059_wealth │ Table is a       │    
  │ wealth_vec │        │ _vector_chu │ regular table,   │    
  │ tor_chunks │        │ nks         │ NOT a            │    
  │ segment    │        │             │ hypertable. No   │    
  │            │        │             │ compression or   │    
  │            │        │             │ segmentby        │    
  │            │        │             │ exists.          │    
  │ A.4        │ CONCUR │ view_refres │ Code already     │    
  │ mv_unified │ RENTLY │ h.py L29    │ attempts         │    
  │ _funds     │        │             │ CONCURRENTLY by  │    
  │ refresh    │        │             │ default with a   │    
  │            │        │             │ non-concurrent   │    
  │            │        │             │ fallback.        │    
  │ A.5        │ Regula │ 0099 L63    │ Confirmed NOT a  │    
  │ constructi │ r      │             │ hypertable.      │    
  │ on_runs    │ Table  │             │ MISSING          │    
  │ structure  │        │             │ event_log column │    
  │            │        │             │ (not in CREATE   │    
  │            │        │             │ TABLE or         │    
  │            │        │             │ subsequent       │    
  │            │        │             │ migrations).     │    
  │ A.6 RLS    │ NONE   │ All         │ Subselect        │    
  │ bare       │        │ migrations  │ pattern (SELECT  │    
  │ current_se │        │             │ current_setting( │    
  │ tting      │        │             │ ...)) is         │    
  │            │        │             │ consistently     │    
  │            │        │             │ followed across  │    
  │            │        │             │ all audited      │    
  │            │        │             │ files.           │    
  │ A.7        │ NON-UN │ 0049 L60,   │ Confirmed index  │    
  │ nav_monthl │ IQUE   │ 0069 L165   │ idx_nav_monthly_ │    
  │ y_returns_ │        │             │ returns_agg_inst │    
  │ agg index  │        │             │ _month is NOT    │    
  │            │        │             │ unique.          │    
  └────────────┴────────┴─────────────┴──────────────────┘    
  Section B: Endpoints
  ┌───────────────┬──────┬───────────────┬───────────────┐
  │ Endpoint      │ Stat │ Location      │ Notes         │
  │               │ us   │               │               │
  ├───────────────┼──────┼───────────────┼───────────────┤
  │ DELETE        │ MISS │ workers.py,   │ No job        │
  │ /jobs/{id}    │ ING  │ tracker.py    │ cancellation  │
  │               │      │               │ endpoint      │
  │               │      │               │ found in the  │
  │               │      │               │ core or       │
  │               │      │               │ wealth        │
  │               │      │               │ domain.       │
  │ GET           │ MISS │ model_portfol │ get_construct │
  │ .../runs/{run │ ING  │ ios.py        │ ion_run       │
  │ Id}/diff      │      │               │ exists, but   │
  │               │      │               │ no diff logic │
  │               │      │               │ or endpoint.  │
  │ GET           │ MISS │ dd_reports.py │ No aggregator │
  │ /dd-reports/q │ ING  │ ,             │ for the       │
  │ ueue          │      │ long_form_rep │ report queue  │
  │               │      │ orts.py       │ found.        │
  └───────────────┴──────┴───────────────┴───────────────┘
  Section C: Sanitization

   - C.1 sanitize_public_event module: NOT FOUND. However, a
     comprehensive
     backend/app/domains/wealth/schemas/sanitized.py exists,
     covering METRIC_LABELS (CVaR, GARCH, etc.) and
     REGIME_LABELS (RISK_ON -> Expansion). It uses Pydantic
     mixins and humanization helpers.
   - C.2 Schema jargon leakage: CONFIRMED. RiskTimeseriesOut
     (in schemas/risk_timeseries.py) emits volatility_garch
     and raw regime enums (e.g. RISK_ON) from the regime_prob
     series without routing through the sanitized layer.

  Section D: Worker State

   - D.1 global_risk_metrics fields: PARTIAL. Computed:       
     volatility, sharpe, cvar_95, rsi_14, nav_momentum_score, 
     blended_momentum_score, cvar_95_conditional. MISSING:    
     peer_quantile_cvar, peer_quantile_sharpe,
     peer_quantile_momentum. No quantile logic found in       
     risk_calc.py.
   - D.2 construction_run_executor sanitization: NONE.        
     publish_event calls pass raw internal event names (e.g., 
     optimizer_started, narrative_started) and raw optimizer  
     data without wrapping or sanitization.

  Section E: Frontend ELITE expectations

   - E.1 elite search: TerminalRiskKpis.svelte (L198) uses the
     elite class to badge funds with risk.managerScore >= 75.
     The eviction badge is used for scores < 40. Styles are
     defined at L392-393.

  Section F: Prior Plan Context

   - F.1 Plan Summary: The "Portfolio Enterprise Workbench
     Implementation Plan" (2026-04-08) mandates a 3-column FCL
     architecture for the Builder, a dedicated Analytics
     surface, and a high-density Live Workbench. It defines
     the construction run lifecycle, persistence of optimizer
     traces/narratives, and the state machine (draft →
     approved → live).
   - F.2 Task 3.4 Alignment: Confirmed
     construction_run_executor.py (900_101) follows the 120s
     wall-clock bound and Job-or-Stream pattern defined in the
     plan.

  Section G: Final Confirmation

   - 0099_portfolio_construction_runs.py does NOT include
     event_log.
   - 0049_wealth_continuous_aggregates.py does NOT include a
     UNIQUE index on monthly aggregates.
   - backend/app/domains/wealth/schemas/sanitized.py is the
     established source of truth for nomenclature, but remains
     under-utilized in recent construction/risk endpoints.