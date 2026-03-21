"""Document tables evaluated for hypertable conversion and skipped.

This migration performs no schema changes. It documents the evaluation
of candidate tables from the "Analytics Runs & Allocation State" group.

All tables in this group have updated_at columns that are actively used
(status transitions, approval workflows, or two-phase writes). They are
NOT append-only, and therefore not suitable for hypertable conversion.

## Tables evaluated — all SKIPPED

| Table | Reason skipped |
|---|---|
| eval_runs | status changes (running→completed), updated_at active |
| deep_review_validation_runs | aggregate_winner nullable (two-phase write), updated_at active |
| screening_runs | status changes (running→completed/failed), updated_at active |
| screening_results | is_current toggled (true→false on re-screen), updated_at active |
| backtest_runs | status changes (pending→completed), updated_at active |
| report_runs | status changes (running→completed/failed), updated_at active |
| rebalance_events | status changes (pending→approved), updated_at active |
| allocation_blocks | config table, rows updated in place, updated_at active |
| tactical_positions | valid_to set on supersede, partial unique on valid_to IS NULL |
| strategic_allocation | effective_to set on supersede, rows updated in place |

## Decision criteria

From the migration spec: "If table has updated_at that is actually
updated (not just set on insert), it is NOT append-only — skip
hypertable conversion."

All tables above have mutable status/lifecycle fields that are updated
after initial insert. Converting them would cause issues with
TimescaleDB's compressed chunk immutability (compressed chunks cannot
be updated, requiring decompress-update-recompress cycles).

## Hypertable summary after migrations 0026-0032

Existing (pre-0025):
  - nav_timeseries (0002): nav_date, 30-day compression
  - fund_risk_metrics (0002): calc_date, 30-day compression

From 0025 (SEC data):
  - sec_13f_holdings: report_date, 3-month chunks, 6-month compression
  - sec_13f_diffs: quarter_to, 3-month chunks, 6-month compression

From 0026 (Macro & Market):
  - macro_data: obs_date, 1-month chunks, 3-month compression
  - macro_snapshots: as_of_date, 1-month chunks, 3-month compression
  - macro_regional_snapshots: as_of_date, 1-month chunks, 3-month compression
  - benchmark_nav: nav_date, 1-month chunks, 3-month compression

From 0027 (NAV & Portfolio):
  - nav_snapshots: created_at, 1-month chunks, 3-month compression
  - asset_valuation_snapshots: created_at, 1-month chunks, 3-month compression
  - portfolio_snapshots: snapshot_date, 1-month chunks, 3-month compression

From 0028 (SEC Institutional):
  - sec_institutional_allocations: report_date, 3-month chunks, 6-month compression

From 0029 (Drift & Alerts):
  - performance_drift_flags: created_at, 1-month chunks, 3-month compression
  - strategy_drift_alerts: detected_at, 1-month chunks, 3-month compression
  - governance_alerts: created_at, 1-month chunks, 3-month compression
  - pipeline_alerts: created_at, 1-month chunks, 3-month compression

From 0030 (Audit & Events):
  - audit_events: created_at, 1-week chunks, 1-month compression
  - deal_events: created_at, 1-week chunks, 1-month compression
  - pipeline_deal_stage_history: changed_at, 1-week chunks, 1-month compression
  - deal_conversion_events: created_at, 1-week chunks, 1-month compression
  - cash_impact_flags: created_at, 1-week chunks, 1-month compression

From 0031 (Risk & Covenant):
  - covenant_status_register: created_at, 1-month chunks, 3-month compression
  - investment_risk_registry: created_at, 1-month chunks, 3-month compression
  - deal_risk_flags: created_at, 1-month chunks, 3-month compression

TOTAL: 24 hypertables (4 existing + 20 new)

depends_on: 0031 (risk_covenant_hypertables).
"""

from alembic import op  # noqa: F401 — required by Alembic even for no-op migrations

revision = "0032_hypertable_skip_docs"
down_revision = "0031_risk_covenant_hypertables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Documentation-only migration. No schema changes.
    # See module docstring for evaluation results.
    pass


def downgrade() -> None:
    pass
