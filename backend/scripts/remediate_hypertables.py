"""Remediate dev DB: convert regular tables to TimescaleDB hypertables.

Fixes the case where Alembic migrations ran but the create_hypertable
calls failed silently (e.g. DATABASE_URL_SYNC not set, psycopg3
autocommit connection could not be established).

Idempotent — safe to run multiple times. Skips tables already converted.

Usage:
    # Dry run (default) — shows what would be done
    python -m scripts.remediate_hypertables

    # Execute for real
    python -m scripts.remediate_hypertables --execute

    # Against specific DB
    DATABASE_URL_SYNC=postgresql://... python -m scripts.remediate_hypertables --execute

Requires: psycopg[binary] (psycopg3)
"""

from __future__ import annotations

import argparse
import os
import sys
import psycopg


# ── Hypertable specifications ────────────────────────────────────────────
# Each spec describes the FINAL desired state of the hypertable.
# Grouped by migration origin for traceability.

HYPERTABLE_SPECS: list[dict] = [
    # ── c3d4e5f6a7b8: nav_timeseries, fund_risk_metrics ──
    {
        "table": "nav_timeseries",
        "time_col": "nav_date",
        "chunk_interval": None,  # default (7 days)
        "compress_segmentby": "instrument_id",  # changed from organization_id in 0069
        "compress_orderby": "nav_date DESC",
        "compress_after": "3 months",  # updated in 0069
        "pk_restructure": None,  # PK already has nav_date
        "rls_drop": True,
        "fk_drops": [],
        "time_col_nullable": False,
        "drop_id_column": False,
    },
    {
        "table": "fund_risk_metrics",
        "time_col": "calc_date",
        "chunk_interval": None,  # default
        "compress_segmentby": None,
        "compress_orderby": "calc_date DESC",
        "compress_after": "30 days",
        "pk_restructure": None,  # PK already has calc_date
        "rls_drop": True,
        "fk_drops": [],
        "time_col_nullable": False,
        "drop_id_column": False,
    },

    # ── 0025: sec_13f_holdings, sec_13f_diffs ──
    {
        "table": "sec_13f_holdings",
        "time_col": "report_date",
        "chunk_interval": "3 months",
        "compress_segmentby": "cik",
        "compress_orderby": "report_date DESC",
        "compress_after": "6 months",
        "pk_restructure": {
            "drop_constraints": [
                "sec_13f_holdings_pkey",
                "uq_sec_13f_holdings_cik_date_cusip",
            ],
            "drop_indexes": [
                "idx_sec_13f_holdings_cik_report_date",
                "idx_sec_13f_holdings_cusip_report_date",
                "idx_sec_13f_holdings_sector",
            ],
            "drop_id_column": True,
            "new_pk": "(report_date, cik, cusip)",
        },
        "post_indexes": [
            "CREATE INDEX IF NOT EXISTS idx_sec_13f_holdings_cik_report_date ON sec_13f_holdings (cik, report_date DESC)",
            "CREATE INDEX IF NOT EXISTS idx_sec_13f_holdings_cusip_report_date ON sec_13f_holdings (cusip, report_date DESC) INCLUDE (cik, shares, market_value)",
            "CREATE INDEX IF NOT EXISTS idx_sec_13f_holdings_sector ON sec_13f_holdings (cik, report_date DESC, sector)",
        ],
        "rls_drop": False,
        "fk_drops": [],
        "time_col_nullable": False,
        "drop_id_column": True,
    },
    {
        "table": "sec_13f_diffs",
        "time_col": "quarter_to",
        "chunk_interval": "3 months",
        "compress_segmentby": "cik",
        "compress_orderby": "quarter_to DESC",
        "compress_after": "6 months",
        "pk_restructure": {
            "drop_constraints": [
                "sec_13f_diffs_pkey",
                "uq_sec_13f_diffs_cik_cusip_quarters",
            ],
            "drop_indexes": [
                "idx_sec_13f_diffs_cik_quarter_to",
                "idx_sec_13f_diffs_cusip_quarter_to",
            ],
            "drop_id_column": True,
            "new_pk": "(quarter_to, cik, cusip, quarter_from)",
        },
        "post_indexes": [
            "CREATE INDEX IF NOT EXISTS idx_sec_13f_diffs_cik_quarter_to ON sec_13f_diffs (cik, quarter_to DESC)",
            "CREATE INDEX IF NOT EXISTS idx_sec_13f_diffs_cusip_quarter_to ON sec_13f_diffs (cusip, quarter_to DESC)",
        ],
        "rls_drop": False,
        "fk_drops": [],
        "time_col_nullable": False,
        "drop_id_column": True,
    },

    # ── 0026: macro_data, macro_snapshots, macro_regional_snapshots, benchmark_nav ──
    {
        "table": "macro_data",
        "time_col": "obs_date",
        "chunk_interval": "1 month",
        "compress_segmentby": "series_id",
        "compress_orderby": "obs_date DESC",
        "compress_after": "3 months",
        "pk_restructure": None,
        "rls_drop": False,
        "fk_drops": [],
        "time_col_nullable": False,
        "drop_id_column": False,
        "post_indexes": [
            "CREATE INDEX IF NOT EXISTS idx_macro_data_series_obs_date ON macro_data (series_id, obs_date DESC)",
        ],
    },
    {
        "table": "macro_snapshots",
        "time_col": "as_of_date",
        "chunk_interval": "1 month",
        "compress_segmentby": None,
        "compress_orderby": "as_of_date DESC",
        "compress_after": "3 months",
        "pk_restructure": {
            "drop_constraints": [
                "macro_snapshots_pkey",
                "macro_snapshots_as_of_date_key",
            ],
            "drop_indexes": ["ix_macro_snapshots_as_of_date"],
            "drop_id_column": False,
            "new_pk": "(as_of_date, id)",
        },
        "post_constraints": [
            "ALTER TABLE macro_snapshots DROP CONSTRAINT IF EXISTS uq_macro_snapshots_as_of_date",
            "ALTER TABLE macro_snapshots ADD CONSTRAINT uq_macro_snapshots_as_of_date UNIQUE (as_of_date)",
        ],
        "rls_drop": False,
        "fk_drops": [],
        "time_col_nullable": True,  # needs backfill
        "drop_id_column": False,
    },
    {
        "table": "macro_regional_snapshots",
        "time_col": "as_of_date",
        "chunk_interval": "1 month",
        "compress_segmentby": None,
        "compress_orderby": "as_of_date DESC",
        "compress_after": "3 months",
        "pk_restructure": {
            "drop_constraints": [
                "macro_regional_snapshots_pkey",
                "macro_regional_snapshots_as_of_date_key",
            ],
            "drop_indexes": ["ix_macro_regional_snapshots_as_of_date"],
            "drop_id_column": False,
            "new_pk": "(as_of_date, id)",
        },
        "post_constraints": [
            "ALTER TABLE macro_regional_snapshots DROP CONSTRAINT IF EXISTS uq_macro_regional_snapshots_as_of_date",
            "ALTER TABLE macro_regional_snapshots ADD CONSTRAINT uq_macro_regional_snapshots_as_of_date UNIQUE (as_of_date)",
        ],
        "rls_drop": False,
        "fk_drops": [
            "ALTER TABLE macro_reviews DROP CONSTRAINT IF EXISTS macro_reviews_snapshot_id_fkey",
        ],
        "time_col_nullable": True,
        "drop_id_column": False,
    },
    {
        "table": "benchmark_nav",
        "time_col": "nav_date",
        "chunk_interval": "1 month",
        "compress_segmentby": "block_id",
        "compress_orderby": "nav_date DESC",
        "compress_after": "3 months",
        "pk_restructure": None,
        "rls_drop": False,
        "fk_drops": [],
        "time_col_nullable": False,
        "drop_id_column": False,
        "post_indexes": [
            "CREATE INDEX IF NOT EXISTS idx_benchmark_nav_block_date ON benchmark_nav (block_id, nav_date DESC)",
        ],
    },

    # ── 0027: nav_snapshots, asset_valuation_snapshots, portfolio_snapshots ──
    {
        "table": "nav_snapshots",
        "time_col": "created_at",
        "chunk_interval": "1 month",
        "compress_segmentby": "fund_id",
        "compress_orderby": "created_at DESC",
        "compress_after": "3 months",
        "pk_restructure": {
            "drop_constraints": ["nav_snapshots_pkey"],
            "drop_indexes": [
                "ix_nav_snapshots_fund_period",
                "ix_nav_snapshots_fund_status",
            ],
            "drop_id_column": False,
            "new_pk": "(created_at, id)",
        },
        "post_indexes": [
            "CREATE INDEX IF NOT EXISTS idx_nav_snapshots_fund_period ON nav_snapshots (fund_id, period_month, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_nav_snapshots_fund_status ON nav_snapshots (fund_id, status, created_at DESC)",
        ],
        "rls_drop": True,
        "fk_drops": [
            "ALTER TABLE monthly_report_packs DROP CONSTRAINT IF EXISTS monthly_report_packs_nav_snapshot_id_fkey",
            "ALTER TABLE asset_valuation_snapshots DROP CONSTRAINT IF EXISTS asset_valuation_snapshots_nav_snapshot_id_fkey",
        ],
        "time_col_nullable": True,
        "drop_id_column": False,
    },
    {
        "table": "asset_valuation_snapshots",
        "time_col": "created_at",
        "chunk_interval": "1 month",
        "compress_segmentby": "fund_id",
        "compress_orderby": "created_at DESC",
        "compress_after": "3 months",
        "pk_restructure": {
            "drop_constraints": ["asset_valuation_snapshots_pkey"],
            "drop_indexes": [
                "ix_asset_valuation_snapshots_fund_nav",
                "ix_asset_valuation_snapshots_nav_asset",
            ],
            "drop_id_column": False,
            "new_pk": "(created_at, id)",
        },
        "post_indexes": [
            "CREATE INDEX IF NOT EXISTS idx_asset_val_snapshots_fund_nav ON asset_valuation_snapshots (fund_id, nav_snapshot_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_asset_val_snapshots_nav_asset ON asset_valuation_snapshots (nav_snapshot_id, asset_id, created_at DESC)",
        ],
        "rls_drop": True,
        "fk_drops": [],
        "time_col_nullable": True,
        "drop_id_column": False,
    },
    {
        "table": "portfolio_snapshots",
        "time_col": "snapshot_date",
        "chunk_interval": "1 month",
        "compress_segmentby": "organization_id",
        "compress_orderby": "snapshot_date DESC",
        "compress_after": "3 months",
        "pk_restructure": {
            "drop_constraints": ["portfolio_snapshots_pkey"],
            "drop_indexes": ["ix_portfolio_snapshots_org_profile_date"],
            "drop_id_column": False,
            "new_pk": "(snapshot_date, snapshot_id)",
        },
        "post_indexes": [
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_portfolio_snapshots_org_profile_date ON portfolio_snapshots (organization_id, profile, snapshot_date)",
        ],
        "rls_drop": True,
        "fk_drops": [],
        "time_col_nullable": False,
        "drop_id_column": False,
    },

    # ── 0028: sec_institutional_allocations ──
    {
        "table": "sec_institutional_allocations",
        "time_col": "report_date",
        "chunk_interval": "3 months",
        "compress_segmentby": "filer_cik",
        "compress_orderby": "report_date DESC",
        "compress_after": "6 months",
        "pk_restructure": {
            "drop_constraints": [
                "sec_institutional_allocations_pkey",
                "uq_sec_inst_alloc_filer_target_date",
            ],
            "drop_indexes": [
                "idx_sec_inst_alloc_filer_report_date",
                "idx_sec_inst_alloc_target_report_date",
            ],
            "drop_id_column": True,
            "new_pk": "(report_date, filer_cik, target_cusip)",
        },
        "post_indexes": [
            "CREATE INDEX IF NOT EXISTS idx_sec_inst_alloc_filer_report_date ON sec_institutional_allocations (filer_cik, report_date DESC)",
            "CREATE INDEX IF NOT EXISTS idx_sec_inst_alloc_target_report_date ON sec_institutional_allocations (target_cusip, report_date DESC)",
        ],
        "rls_drop": False,
        "fk_drops": [],
        "time_col_nullable": False,
        "drop_id_column": True,
    },

    # ── 0029: drift & alert tables ──
    {
        "table": "performance_drift_flags",
        "time_col": "created_at",
        "chunk_interval": "1 month",
        "compress_segmentby": "fund_id",
        "compress_orderby": "created_at DESC",
        "compress_after": "3 months",
        "pk_restructure": {
            "drop_constraints": ["performance_drift_flags_pkey"],
            "drop_indexes": ["ix_performance_drift_flags_fund_investment"],
            "drop_id_column": False,
            "new_pk": "(created_at, id)",
        },
        "post_indexes": [
            "CREATE INDEX IF NOT EXISTS idx_perf_drift_flags_fund_investment ON performance_drift_flags (fund_id, investment_id, created_at DESC)",
        ],
        "rls_drop": True,
        "fk_drops": [],
        "time_col_nullable": True,
        "drop_id_column": False,
    },
    {
        "table": "strategy_drift_alerts",
        "time_col": "detected_at",
        "chunk_interval": "1 month",
        "compress_segmentby": "instrument_id",
        "compress_orderby": "detected_at DESC",
        "compress_after": "3 months",
        "pk_restructure": {
            "drop_constraints": ["strategy_drift_alerts_pkey"],
            "drop_indexes": [
                "uq_drift_alerts_current",
                "ix_drift_alerts_severity",
            ],
            "drop_id_column": False,
            "new_pk": "(detected_at, id)",
        },
        "post_indexes": [
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_strategy_drift_alerts_org_instrument_current ON strategy_drift_alerts (detected_at, organization_id, instrument_id) WHERE is_current = true",
            "CREATE INDEX IF NOT EXISTS idx_strategy_drift_alerts_org_severity_current ON strategy_drift_alerts (organization_id, severity, detected_at DESC) WHERE is_current = true",
        ],
        "rls_drop": True,
        "fk_drops": [],
        "time_col_nullable": False,
        "drop_id_column": False,
    },
    {
        "table": "governance_alerts",
        "time_col": "created_at",
        "chunk_interval": "1 month",
        "compress_segmentby": "organization_id",
        "compress_orderby": "created_at DESC",
        "compress_after": "3 months",
        "pk_restructure": {
            "drop_constraints": ["governance_alerts_pkey"],
            "drop_indexes": ["ix_governance_alerts_fund_alert_id"],
            "drop_id_column": False,
            "new_pk": "(created_at, id)",
        },
        "post_indexes": [
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_governance_alerts_fund_alert ON governance_alerts (created_at, fund_id, alert_id)",
        ],
        "rls_drop": True,
        "fk_drops": [],
        "time_col_nullable": True,
        "drop_id_column": False,
    },
    {
        "table": "pipeline_alerts",
        "time_col": "created_at",
        "chunk_interval": "1 month",
        "compress_segmentby": "organization_id",
        "compress_orderby": "created_at DESC",
        "compress_after": "3 months",
        "pk_restructure": {
            "drop_constraints": ["pipeline_alerts_pkey"],
            "drop_indexes": ["ix_pipeline_alerts_fund_deal"],
            "drop_id_column": False,
            "new_pk": "(created_at, id)",
        },
        "post_indexes": [
            "CREATE INDEX IF NOT EXISTS idx_pipeline_alerts_fund_deal ON pipeline_alerts (fund_id, deal_id, created_at DESC)",
        ],
        "rls_drop": True,
        "fk_drops": [],
        "time_col_nullable": True,
        "drop_id_column": False,
    },

    # ── 0030: audit & event logs ──
    {
        "table": "audit_events",
        "time_col": "created_at",
        "chunk_interval": "1 week",
        "compress_segmentby": "organization_id",
        "compress_orderby": "created_at DESC",
        "compress_after": "1 month",
        "pk_restructure": {
            "drop_constraints": ["audit_events_pkey"],
            "drop_indexes": ["ix_audit_events_org_entity_created"],
            "drop_id_column": False,
            "new_pk": "(created_at, id)",
        },
        "post_indexes": [
            "CREATE INDEX IF NOT EXISTS idx_audit_events_org_entity_created ON audit_events (organization_id, entity_type, created_at DESC)",
        ],
        "rls_drop": True,
        "fk_drops": [],
        "time_col_nullable": True,
        "drop_id_column": False,
    },
    {
        "table": "deal_events",
        "time_col": "created_at",
        "chunk_interval": "1 week",
        "compress_segmentby": "fund_id",
        "compress_orderby": "created_at DESC",
        "compress_after": "1 month",
        "pk_restructure": {
            "drop_constraints": ["deal_events_pkey"],
            "drop_indexes": ["ix_deal_events_fund_type", "ix_deal_events_created"],
            "drop_id_column": False,
            "new_pk": "(created_at, id)",
        },
        "post_indexes": [
            "CREATE INDEX IF NOT EXISTS idx_deal_events_fund_type ON deal_events (fund_id, event_type, created_at DESC)",
        ],
        "rls_drop": True,
        "fk_drops": [],
        "time_col_nullable": True,
        "drop_id_column": False,
    },
    {
        "table": "pipeline_deal_stage_history",
        "time_col": "changed_at",
        "chunk_interval": "1 week",
        "compress_segmentby": "deal_id",
        "compress_orderby": "changed_at DESC",
        "compress_after": "1 month",
        "pk_restructure": {
            "drop_constraints": ["pipeline_deal_stage_history_pkey"],
            "drop_indexes": [],
            "drop_id_column": False,
            "new_pk": "(changed_at, id)",
        },
        "post_indexes": [
            "CREATE INDEX IF NOT EXISTS idx_pipeline_stage_history_deal ON pipeline_deal_stage_history (deal_id, changed_at DESC)",
        ],
        "rls_drop": True,
        "fk_drops": [],
        "time_col_nullable": False,
        "drop_id_column": False,
    },
    {
        "table": "deal_conversion_events",
        "time_col": "created_at",
        "chunk_interval": "1 week",
        "compress_segmentby": "fund_id",
        "compress_orderby": "created_at DESC",
        "compress_after": "1 month",
        "pk_restructure": {
            "drop_constraints": ["deal_conversion_events_pkey"],
            "drop_indexes": ["ix_deal_conversion_events_fund_created"],
            "drop_id_column": False,
            "new_pk": "(created_at, id)",
        },
        "post_indexes": [
            "CREATE INDEX IF NOT EXISTS idx_deal_conversion_events_fund ON deal_conversion_events (fund_id, created_at DESC)",
        ],
        "rls_drop": True,
        "fk_drops": [],
        "time_col_nullable": True,
        "drop_id_column": False,
    },
    {
        "table": "cash_impact_flags",
        "time_col": "created_at",
        "chunk_interval": "1 week",
        "compress_segmentby": "investment_id",
        "compress_orderby": "created_at DESC",
        "compress_after": "1 month",
        "pk_restructure": {
            "drop_constraints": ["cash_impact_flags_pkey"],
            "drop_indexes": ["ix_cash_impact_flags_fund_investment"],
            "drop_id_column": False,
            "new_pk": "(created_at, id)",
        },
        "post_indexes": [
            "CREATE INDEX IF NOT EXISTS idx_cash_impact_flags_fund_investment ON cash_impact_flags (fund_id, investment_id, created_at DESC)",
        ],
        "rls_drop": True,
        "fk_drops": [],
        "time_col_nullable": True,
        "drop_id_column": False,
    },

    # ── 0031: risk & covenant ──
    {
        "table": "covenant_status_register",
        "time_col": "created_at",
        "chunk_interval": "1 month",
        "compress_segmentby": "investment_id",
        "compress_orderby": "created_at DESC",
        "compress_after": "3 months",
        "pk_restructure": {
            "drop_constraints": ["covenant_status_register_pkey"],
            "drop_indexes": ["ix_covenant_status_register_fund_investment"],
            "drop_id_column": False,
            "new_pk": "(created_at, id)",
        },
        "post_indexes": [
            "CREATE INDEX IF NOT EXISTS idx_covenant_status_fund_investment ON covenant_status_register (fund_id, investment_id, created_at DESC)",
        ],
        "rls_drop": True,
        "fk_drops": [],
        "time_col_nullable": True,
        "drop_id_column": False,
    },
    {
        "table": "investment_risk_registry",
        "time_col": "created_at",
        "chunk_interval": "1 month",
        "compress_segmentby": "investment_id",
        "compress_orderby": "created_at DESC",
        "compress_after": "3 months",
        "pk_restructure": {
            "drop_constraints": ["investment_risk_registry_pkey"],
            "drop_indexes": ["ix_investment_risk_registry_fund_investment"],
            "drop_id_column": False,
            "new_pk": "(created_at, id)",
        },
        "post_indexes": [
            "CREATE INDEX IF NOT EXISTS idx_investment_risk_fund_investment ON investment_risk_registry (fund_id, investment_id, created_at DESC)",
        ],
        "rls_drop": True,
        "fk_drops": [],
        "time_col_nullable": True,
        "drop_id_column": False,
    },
    {
        "table": "deal_risk_flags",
        "time_col": "created_at",
        "chunk_interval": "1 month",
        "compress_segmentby": "deal_id",
        "compress_orderby": "created_at DESC",
        "compress_after": "3 months",
        "pk_restructure": {
            "drop_constraints": ["deal_risk_flags_pkey"],
            "drop_indexes": ["ix_deal_risk_flags_fund_deal"],
            "drop_id_column": False,
            "new_pk": "(created_at, id)",
        },
        "post_indexes": [
            "CREATE INDEX IF NOT EXISTS idx_deal_risk_flags_fund_deal ON deal_risk_flags (fund_id, deal_id, created_at DESC)",
        ],
        "rls_drop": True,
        "fk_drops": [],
        "time_col_nullable": True,
        "drop_id_column": False,
    },

    # ── 0034: append-only validation/eval/review tables ──
    {
        "table": "deep_review_validation_runs",
        "time_col": "created_at",
        "chunk_interval": "1 month",
        "compress_segmentby": None,
        "compress_orderby": "created_at DESC",
        "compress_after": "3 months",
        "pk_restructure": {
            "drop_constraints": ["deep_review_validation_runs_pkey"],
            "drop_indexes": [],
            "drop_id_column": False,
            "new_pk": "(created_at, id)",
        },
        "rls_drop": False,
        "fk_drops": [],
        "time_col_nullable": True,
        "drop_id_column": False,
    },
    {
        "table": "eval_runs",
        "time_col": "started_at",
        "chunk_interval": "1 month",
        "compress_segmentby": None,
        "compress_orderby": "started_at DESC",
        "compress_after": "3 months",
        "pk_restructure": {
            "drop_constraints": ["eval_runs_pkey"],
            "drop_indexes": [],
            "drop_id_column": False,
            "new_pk": "(started_at, id)",
        },
        "post_indexes": [
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_eval_runs_started_run_id ON eval_runs (started_at, run_id)",
        ],
        "rls_drop": False,
        "fk_drops": [],
        "time_col_nullable": True,
        "drop_id_column": False,
    },
    {
        "table": "periodic_review_reports",
        "time_col": "created_at",
        "chunk_interval": "1 month",
        "compress_segmentby": "fund_id",
        "compress_orderby": "created_at DESC",
        "compress_after": "3 months",
        "pk_restructure": {
            "drop_constraints": ["periodic_review_reports_pkey"],
            "drop_indexes": [],
            "drop_id_column": False,
            "new_pk": "(created_at, id)",
        },
        "rls_drop": True,
        "fk_drops": [],
        "time_col_nullable": True,
        "drop_id_column": False,
    },

    # ── 0036: treasury_data ──
    {
        "table": "treasury_data",
        "time_col": "obs_date",
        "chunk_interval": "1 month",
        "compress_segmentby": "series_id",
        "compress_orderby": "obs_date DESC",
        "compress_after": "3 months",
        "pk_restructure": None,  # PK already (obs_date, series_id)
        "rls_drop": False,
        "fk_drops": [],
        "time_col_nullable": False,
        "drop_id_column": False,
    },

    # ── 0037: ofr_hedge_fund_data ──
    {
        "table": "ofr_hedge_fund_data",
        "time_col": "obs_date",
        "chunk_interval": "3 months",
        "compress_segmentby": "series_id",
        "compress_orderby": "obs_date DESC",
        "compress_after": "6 months",
        "pk_restructure": None,
        "rls_drop": False,
        "fk_drops": [],
        "time_col_nullable": False,
        "drop_id_column": False,
    },

    # ── 0040: sec_nport_holdings ──
    {
        "table": "sec_nport_holdings",
        "time_col": "report_date",
        "chunk_interval": "3 months",
        "compress_segmentby": "cik",
        "compress_orderby": "report_date DESC",
        "compress_after": "3 months",
        "pk_restructure": None,
        "rls_drop": False,
        "fk_drops": [],
        "time_col_nullable": False,
        "drop_id_column": False,
    },

    # ── 0042: bis_statistics, imf_weo_forecasts ──
    {
        "table": "bis_statistics",
        "time_col": "period",
        "chunk_interval": "1 year",
        "compress_segmentby": "country_code",
        "compress_orderby": "period DESC",
        "compress_after": "1 year",
        "pk_restructure": None,
        "rls_drop": False,
        "fk_drops": [],
        "time_col_nullable": False,
        "drop_id_column": False,
    },
    {
        "table": "imf_weo_forecasts",
        "time_col": "period",
        "chunk_interval": "1 year",
        "compress_segmentby": "country_code",
        "compress_orderby": "period DESC",
        "compress_after": "1 year",
        "pk_restructure": None,
        "rls_drop": False,
        "fk_drops": [],
        "time_col_nullable": False,
        "drop_id_column": False,
    },

    # ── 0055: model_portfolio_nav (NO compression — RLS enabled) ──
    {
        "table": "model_portfolio_nav",
        "time_col": "nav_date",
        "chunk_interval": "1 month",
        "compress_segmentby": None,
        "compress_orderby": None,
        "compress_after": None,  # NO compression — RLS enabled
        "pk_restructure": None,  # PK already (portfolio_id, nav_date)
        "rls_drop": False,
        "fk_drops": [],
        "time_col_nullable": False,
        "drop_id_column": False,
    },

    # ── 0061: macro_regime_history ──
    {
        "table": "macro_regime_history",
        "time_col": "regime_date",
        "chunk_interval": "1 month",
        "compress_segmentby": None,
        "compress_orderby": "regime_date DESC",
        "compress_after": "3 months",
        "pk_restructure": None,  # PK already (regime_date)
        "rls_drop": False,
        "fk_drops": [],
        "time_col_nullable": False,
        "drop_id_column": False,
    },

    # ── 0064: sec_mmf_metrics ──
    {
        "table": "sec_mmf_metrics",
        "time_col": "metric_date",
        "chunk_interval": "1 month",
        "compress_segmentby": "series_id,class_id",
        "compress_orderby": None,
        "compress_after": "3 months",
        "pk_restructure": None,  # PK already (metric_date, series_id, class_id)
        "rls_drop": False,
        "fk_drops": [],
        "time_col_nullable": False,
        "drop_id_column": False,
    },
]


# ── Continuous aggregates ────────────────────────────────────────────────

CONTINUOUS_AGGREGATES = [
    {
        "name": "sec_13f_latest_quarter",
        "depends_on": "sec_13f_holdings",
        "create_sql": """
            CREATE MATERIALIZED VIEW IF NOT EXISTS sec_13f_latest_quarter
            WITH (timescaledb.continuous) AS
            SELECT
                cik,
                time_bucket('3 months'::interval, report_date) AS quarter,
                SUM(market_value) FILTER (WHERE asset_class = 'Shares')
                    AS total_equity_value,
                COUNT(DISTINCT cusip) FILTER (WHERE asset_class = 'Shares')
                    AS position_count
            FROM sec_13f_holdings
            GROUP BY cik, time_bucket('3 months'::interval, report_date)
            WITH NO DATA
        """,
        "policy_sql": """
            SELECT add_continuous_aggregate_policy(
                'sec_13f_latest_quarter',
                start_offset => INTERVAL '9 months',
                end_offset => INTERVAL '1 day',
                schedule_interval => INTERVAL '1 day',
                if_not_exists => true
            )
        """,
    },
    {
        "name": "nav_monthly_returns_agg",
        "depends_on": "nav_timeseries",
        "create_sql": """
            CREATE MATERIALIZED VIEW IF NOT EXISTS nav_monthly_returns_agg
            WITH (timescaledb.continuous) AS
            SELECT
                instrument_id,
                time_bucket('1 month', nav_date) AS month,
                SUM(return_1d) AS compound_log_return,
                (EXP(SUM(return_1d)) - 1) AS compound_return,
                COUNT(*) AS trading_days,
                MIN(nav) AS min_nav,
                MAX(nav) AS max_nav
            FROM nav_timeseries
            WHERE return_1d IS NOT NULL
            GROUP BY instrument_id,
                time_bucket('1 month', nav_date)
            WITH NO DATA
        """,
        "post_indexes": [
            "CREATE INDEX IF NOT EXISTS idx_nav_monthly_returns_agg_inst_month ON nav_monthly_returns_agg (instrument_id, month DESC)",
        ],
        "policy_sql": """
            SELECT add_continuous_aggregate_policy(
                'nav_monthly_returns_agg',
                start_offset => INTERVAL '3 months',
                end_offset => INTERVAL '1 day',
                schedule_interval => INTERVAL '1 day',
                if_not_exists => true
            )
        """,
    },
]

# ── Plain materialized views ─────────────────────────────────────────────

PLAIN_MATVIEWS = [
    {
        "name": "sec_13f_manager_sector_latest",
        "depends_on": "sec_13f_holdings",
        "create_sql": """
            CREATE MATERIALIZED VIEW IF NOT EXISTS sec_13f_manager_sector_latest AS
            SELECT DISTINCT ON (h.cik)
                h.cik,
                h.report_date,
                h.sector,
                agg.sector_value,
                agg.sector_weight
            FROM (
                SELECT
                    cik,
                    report_date,
                    sector,
                    SUM(market_value) AS sector_value,
                    SUM(market_value)::float /
                        NULLIF(SUM(SUM(market_value)) OVER (PARTITION BY cik, report_date), 0)
                        AS sector_weight
                FROM sec_13f_holdings
                WHERE asset_class = 'Shares' AND sector IS NOT NULL
                GROUP BY cik, report_date, sector
            ) agg
            JOIN sec_13f_holdings h ON h.cik = agg.cik AND h.report_date = agg.report_date
            WHERE h.asset_class = 'Shares' AND h.sector = agg.sector
            ORDER BY h.cik, agg.report_date DESC, agg.sector_value DESC
        """,
        "post_indexes": [
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sec_13f_manager_sector_latest_cik ON sec_13f_manager_sector_latest (cik)",
        ],
    },
]


def get_conninfo() -> str:
    """Resolve a psycopg-compatible connection string."""
    url = os.getenv("DATABASE_URL_SYNC", "") or os.getenv("DATABASE_URL", "")
    if not url:
        print("ERROR: Set DATABASE_URL_SYNC or DATABASE_URL environment variable")
        sys.exit(1)
    # Strip SQLAlchemy dialect prefixes
    for prefix in (
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgresql+asyncpg://",
    ):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]
            break
    return url


def is_hypertable(cursor, table: str) -> bool:
    """Check if table is already a TimescaleDB hypertable."""
    cursor.execute(
        "SELECT 1 FROM timescaledb_information.hypertables "
        "WHERE hypertable_name = %s",
        (table,),
    )
    return cursor.fetchone() is not None


def table_exists(cursor, table: str) -> bool:
    """Check if table exists in the database."""
    cursor.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = %s",
        (table,),
    )
    return cursor.fetchone() is not None


def matview_exists(cursor, name: str) -> bool:
    """Check if materialized view exists."""
    cursor.execute(
        "SELECT 1 FROM pg_matviews WHERE matviewname = %s",
        (name,),
    )
    return cursor.fetchone() is not None


def has_column(cursor, table: str, column: str) -> bool:
    """Check if column exists in table."""
    cursor.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
        (table, column),
    )
    return cursor.fetchone() is not None


def convert_table(cursor, spec: dict, *, dry_run: bool = True) -> bool:
    """Convert a single table to hypertable. Returns True if converted."""
    table = spec["table"]

    if not table_exists(cursor, table):
        print(f"  SKIP {table}: table does not exist")
        return False

    if is_hypertable(cursor, table):
        print(f"  SKIP {table}: already a hypertable")
        return False

    time_col = spec["time_col"]
    if not has_column(cursor, table, time_col):
        print(f"  SKIP {table}: time column '{time_col}' not found")
        return False

    if dry_run:
        print(f"  WOULD CONVERT {table} -> hypertable({time_col})")
        return True

    print(f"  CONVERTING {table} -> hypertable({time_col})...")

    # 1. Drop RLS if needed
    if spec.get("rls_drop"):
        cursor.execute(f"DROP POLICY IF EXISTS org_isolation ON {table}")
        cursor.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        cursor.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # 2. Drop FK constraints
    for fk_sql in spec.get("fk_drops", []):
        cursor.execute(fk_sql)

    # 3. Backfill NULL time columns
    if spec.get("time_col_nullable"):
        cursor.execute(
            f"UPDATE {table} SET {time_col} = NOW() WHERE {time_col} IS NULL"
        )
        cursor.execute(
            f"ALTER TABLE {table} ALTER COLUMN {time_col} SET NOT NULL"
        )

    # 4. PK restructuring
    pk = spec.get("pk_restructure")
    if pk:
        for constraint in pk.get("drop_constraints", []):
            cursor.execute(
                f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}"
            )
        for index in pk.get("drop_indexes", []):
            cursor.execute(f"DROP INDEX IF EXISTS {index}")
        if pk.get("drop_id_column"):
            cursor.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS id")

    # 5. Create hypertable
    chunk_clause = ""
    if spec.get("chunk_interval"):
        chunk_clause = f", chunk_time_interval => INTERVAL '{spec['chunk_interval']}'"
    cursor.execute(
        f"SELECT create_hypertable('{table}', '{time_col}'"
        f"{chunk_clause}, migrate_data => true, if_not_exists => true)"
    )

    # 6. New PK
    if pk and pk.get("new_pk"):
        cursor.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_pkey"
        )
        cursor.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {table}_pkey "
            f"PRIMARY KEY {pk['new_pk']}"
        )

    # 7. Compression settings
    if spec.get("compress_after"):
        compress_parts = ["timescaledb.compress"]
        if spec.get("compress_orderby"):
            compress_parts.append(
                f"timescaledb.compress_orderby = '{spec['compress_orderby']}'"
            )
        if spec.get("compress_segmentby"):
            compress_parts.append(
                f"timescaledb.compress_segmentby = '{spec['compress_segmentby']}'"
            )
        cursor.execute(
            f"ALTER TABLE {table} SET ({', '.join(compress_parts)})"
        )
        cursor.execute(
            f"SELECT add_compression_policy('{table}', "
            f"INTERVAL '{spec['compress_after']}', if_not_exists => true)"
        )

    # 8. Post-conversion constraints
    for sql in spec.get("post_constraints", []):
        cursor.execute(sql)

    # 9. Post-conversion indexes
    for sql in spec.get("post_indexes", []):
        cursor.execute(sql)

    print(f"  OK {table}")
    return True


def create_continuous_aggregates(cursor, *, dry_run: bool = True) -> int:
    """Create continuous aggregates. Returns count created."""
    count = 0
    for cagg in CONTINUOUS_AGGREGATES:
        name = cagg["name"]
        depends_on = cagg["depends_on"]

        if not is_hypertable(cursor, depends_on):
            print(f"  SKIP cagg {name}: {depends_on} is not a hypertable")
            continue

        if matview_exists(cursor, name):
            print(f"  SKIP cagg {name}: already exists")
            continue

        if dry_run:
            print(f"  WOULD CREATE continuous aggregate: {name}")
            count += 1
            continue

        print(f"  CREATING continuous aggregate: {name}...")
        cursor.execute(cagg["create_sql"])
        for sql in cagg.get("post_indexes", []):
            cursor.execute(sql)
        cursor.execute(cagg["policy_sql"])
        print(f"  OK {name}")
        count += 1

    return count


def create_plain_matviews(cursor, *, dry_run: bool = True) -> int:
    """Create plain materialized views. Returns count created."""
    count = 0
    for mv in PLAIN_MATVIEWS:
        name = mv["name"]

        if matview_exists(cursor, name):
            print(f"  SKIP matview {name}: already exists")
            continue

        if dry_run:
            print(f"  WOULD CREATE materialized view: {name}")
            count += 1
            continue

        print(f"  CREATING materialized view: {name}...")
        cursor.execute(mv["create_sql"])
        for sql in mv.get("post_indexes", []):
            cursor.execute(sql)
        print(f"  OK {name}")
        count += 1

    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Remediate dev DB hypertables")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually execute (default is dry run)",
    )
    args = parser.parse_args()
    dry_run = not args.execute

    conninfo = get_conninfo()
    mode = "DRY RUN" if dry_run else "EXECUTING"
    print(f"\n{'=' * 60}")
    print(f"  Hypertable Remediation — {mode}")
    print(f"{'=' * 60}\n")

    # Mask password in output
    safe_conninfo = conninfo
    if "@" in safe_conninfo:
        parts = safe_conninfo.split("@")
        user_part = parts[0].rsplit(":", 1)[0]
        safe_conninfo = f"{user_part}:****@{parts[1]}"
    print(f"  DB: {safe_conninfo}\n")

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        # Verify TimescaleDB
        cursor.execute(
            "SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'"
        )
        if not cursor.fetchone():
            print("ERROR: TimescaleDB extension not installed!")
            sys.exit(1)

        cursor.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'"
        )
        row = cursor.fetchone()
        print(f"  TimescaleDB version: {row[0]}\n")

        # Current state
        cursor.execute(
            "SELECT count(*) FROM timescaledb_information.hypertables"
        )
        current_count = cursor.fetchone()[0]
        print(f"  Current hypertables: {current_count}")
        print(f"  Target hypertables:  {len(HYPERTABLE_SPECS)}\n")

        # Convert tables
        print("--- Hypertable Conversion ---\n")
        converted = 0
        failed = 0
        for spec in HYPERTABLE_SPECS:
            try:
                if convert_table(cursor, spec, dry_run=dry_run):
                    converted += 1
            except Exception as e:
                print(f"  FAILED {spec['table']}: {e}")
                failed += 1

        # Create continuous aggregates
        print("\n--- Continuous Aggregates ---\n")
        cagg_count = create_continuous_aggregates(cursor, dry_run=dry_run)

        # Create plain materialized views
        print("\n--- Materialized Views ---\n")
        mv_count = create_plain_matviews(cursor, dry_run=dry_run)

        # Final state
        if not dry_run:
            cursor.execute(
                "SELECT count(*) FROM timescaledb_information.hypertables"
            )
            final_count = cursor.fetchone()[0]
            print(f"\n  Final hypertables: {final_count}")

        cursor.close()

    # Summary
    print(f"\n{'=' * 60}")
    action = "would convert" if dry_run else "converted"
    print(f"  {action}: {converted} tables")
    print(f"  {'would create' if dry_run else 'created'}: {cagg_count} continuous aggregates")
    print(f"  {'would create' if dry_run else 'created'}: {mv_count} materialized views")
    if failed:
        print(f"  FAILED: {failed}")
    if dry_run and converted > 0:
        print(f"\n  Run with --execute to apply changes")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
