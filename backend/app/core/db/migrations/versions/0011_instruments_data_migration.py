"""Instruments data migration: copy funds → instruments, rename FK columns.

DML-only migration (no DDL schema creation). Copies existing fund data from
funds_universe into instruments_universe with JSONB attributes mapping.
Renames fund_id → instrument_id across all referencing tables. Adds
report_type to dd_reports. Makes analysis_report_id (formerly dd_report_id)
nullable on universe_approvals.

depends_on: 0012 (instruments_universe_additive).
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0012"
branch_labels = None
depends_on = None

# Tables with fund_id FK to funds_universe that need column rename.
# Format: (table_name, has_fk_constraint_name_or_None)
_FK_TABLES = [
    ("nav_timeseries", "nav_timeseries_fund_id_fkey"),
    ("fund_risk_metrics", "fund_risk_metrics_fund_id_fkey"),
    ("lipper_ratings", "lipper_ratings_fund_id_fkey"),
    ("dd_reports", None),  # FK added in 0008, name varies
    ("universe_approvals", None),  # FK added in 0008, name varies
]


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    bind = op.get_bind()

    # ═══════════════════════════════════════════════════════════════
    #  PHASE A: Migrate fund data into instruments_universe
    # ═══════════════════════════════════════════════════════════════
    op.execute("""
        INSERT INTO instruments_universe (
            instrument_id, organization_id, instrument_type, name, isin,
            ticker, asset_class, geography, currency, block_id, is_active,
            approval_status, attributes, created_at, updated_at
        )
        SELECT
            fund_id,
            organization_id,
            'fund',
            name,
            isin,
            ticker,
            COALESCE(asset_class, 'unknown'),
            COALESCE(geography, 'unknown'),
            COALESCE(currency, 'USD'),
            block_id,
            is_active,
            COALESCE(approval_status, 'pending'),
            jsonb_strip_nulls(jsonb_build_object(
                'aum_usd', aum_usd::text,
                'manager_name', manager_name,
                'fund_type', fund_type,
                'sub_category', sub_category,
                'domicile', domicile,
                'liquidity_days', liquidity_days,
                'inception_date', to_char(inception_date, 'YYYY-MM-DD'),
                'data_source', data_source
            )),
            created_at,
            updated_at
        FROM funds_universe
    """)

    # Assert rowcount matches
    fund_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM funds_universe"),
    ).scalar()
    instrument_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM instruments_universe "
            "WHERE instrument_type = 'fund'",
        ),
    ).scalar()
    assert fund_count == instrument_count, (
        f"Data migration mismatch: {fund_count} funds vs {instrument_count} instruments"
    )

    # ═══════════════════════════════════════════════════════════════
    #  PHASE B: Rename FK columns across all referencing tables
    # ═══════════════════════════════════════════════════════════════

    # --- nav_timeseries (TimescaleDB hypertable) ---
    # Must drop FK before rename, recreate after pointing to new table
    op.execute("ALTER TABLE nav_timeseries DROP CONSTRAINT IF EXISTS nav_timeseries_fund_id_fkey")
    op.alter_column("nav_timeseries", "fund_id", new_column_name="instrument_id")
    op.execute("""
        ALTER TABLE nav_timeseries
        ADD CONSTRAINT nav_timeseries_instrument_id_fkey
        FOREIGN KEY (instrument_id) REFERENCES instruments_universe(instrument_id)
    """)

    # --- fund_risk_metrics (TimescaleDB hypertable) ---
    op.execute("ALTER TABLE fund_risk_metrics DROP CONSTRAINT IF EXISTS fund_risk_metrics_fund_id_fkey")
    op.alter_column("fund_risk_metrics", "fund_id", new_column_name="instrument_id")
    op.execute("""
        ALTER TABLE fund_risk_metrics
        ADD CONSTRAINT fund_risk_metrics_instrument_id_fkey
        FOREIGN KEY (instrument_id) REFERENCES instruments_universe(instrument_id)
    """)

    # --- lipper_ratings ---
    op.execute("ALTER TABLE lipper_ratings DROP CONSTRAINT IF EXISTS lipper_ratings_fund_id_fkey")
    op.alter_column("lipper_ratings", "fund_id", new_column_name="instrument_id")
    op.execute("""
        ALTER TABLE lipper_ratings
        ADD CONSTRAINT lipper_ratings_instrument_id_fkey
        FOREIGN KEY (instrument_id) REFERENCES instruments_universe(instrument_id)
    """)

    # --- dd_reports ---
    # FK was added in migration 0008 — drop by discovering constraint name
    _drop_fk_by_column(bind, "dd_reports", "fund_id")
    op.alter_column("dd_reports", "fund_id", new_column_name="instrument_id")
    op.execute("""
        ALTER TABLE dd_reports
        ADD CONSTRAINT dd_reports_instrument_id_fkey
        FOREIGN KEY (instrument_id) REFERENCES instruments_universe(instrument_id)
    """)
    # Add report_type column for polymorphic analysis
    op.add_column(
        "dd_reports",
        sa.Column("report_type", sa.String(20), nullable=False, server_default="dd_report"),
    )
    op.execute("""
        ALTER TABLE dd_reports
        ADD CONSTRAINT chk_dd_report_type
        CHECK (report_type IN ('dd_report', 'bond_brief'))
    """)

    # --- universe_approvals ---
    _drop_fk_by_column(bind, "universe_approvals", "fund_id")
    op.alter_column("universe_approvals", "fund_id", new_column_name="instrument_id")
    op.execute("""
        ALTER TABLE universe_approvals
        ADD CONSTRAINT universe_approvals_instrument_id_fkey
        FOREIGN KEY (instrument_id) REFERENCES instruments_universe(instrument_id)
    """)

    # Rename dd_report_id → analysis_report_id, make nullable (bonds don't need DD)
    _drop_fk_by_column(bind, "universe_approvals", "dd_report_id")
    op.alter_column(
        "universe_approvals",
        "dd_report_id",
        new_column_name="analysis_report_id",
        nullable=True,
    )
    op.execute("""
        ALTER TABLE universe_approvals
        ADD CONSTRAINT universe_approvals_analysis_report_id_fkey
        FOREIGN KEY (analysis_report_id) REFERENCES dd_reports(id)
    """)

    # ═══════════════════════════════════════════════════════════════
    #  PHASE C: Seed screening config defaults
    # ═══════════════════════════════════════════════════════════════
    import json

    _SCREENING_LAYER1 = {
        "fund": {
            "min_aum_usd": 100_000_000,
            "min_track_record_years": 3,
            "allowed_domiciles": ["IE", "LU", "KY", "US", "GB"],
            "allowed_structures": ["UCITS", "Cayman_LP", "Delaware_LP", "SICAV"],
        },
        "bond": {
            "min_credit_rating": "BBB-",
            "min_remaining_maturity_years": 1,
            "min_outstanding_usd": 50_000_000,
            "excluded_issuer_types": [],
        },
        "equity": {
            "min_market_cap_usd": 1_000_000_000,
            "allowed_exchanges": ["NYSE", "NASDAQ", "LSE", "XETRA", "TSE", "HKEX"],
            "min_free_float_pct": 25,
            "excluded_sectors": [],
        },
    }

    _SCREENING_LAYER2 = {
        "blocks": {
            "US_EQUITY": {
                "criteria": {
                    "asset_class": "equity",
                    "geography": "US",
                    "max_pe_ratio": 40,
                    "min_dividend_yield_pct": 0,
                },
            },
            "GLOBAL_FI": {
                "criteria": {
                    "asset_class": "fixed_income",
                    "max_duration_years": 10,
                    "min_yield_pct": 3.0,
                },
            },
            "ALTERNATIVES": {
                "criteria": {
                    "allowed_strategies": ["long_short", "market_neutral"],
                    "max_management_fee_pct": 2.0,
                    "max_performance_fee_pct": 20.0,
                },
            },
        },
    }

    _SCREENING_LAYER3 = {
        "fund": {
            "weights": {
                "sharpe_ratio": 0.30,
                "max_drawdown": 0.25,
                "pct_positive_months": 0.20,
                "correlation_diversification": 0.25,
            },
            "min_data_period_days": 756,
        },
        "bond": {
            "weights": {
                "spread_vs_benchmark": 0.40,
                "liquidity_score": 0.30,
                "duration_efficiency": 0.30,
            },
        },
        "equity": {
            "weights": {
                "pe_relative_sector": 0.25,
                "roe": 0.25,
                "debt_equity": 0.20,
                "momentum_score": 0.30,
            },
        },
    }

    for config_type, config_value in [
        ("screening_layer1", _SCREENING_LAYER1),
        ("screening_layer2", _SCREENING_LAYER2),
        ("screening_layer3", _SCREENING_LAYER3),
    ]:
        config_json = json.dumps(config_value)
        bind.execute(
            sa.text("""
                INSERT INTO vertical_config_defaults (vertical, config_type, config)
                VALUES ('liquid_funds', :config_type, CAST(:config_value AS jsonb))
                ON CONFLICT (vertical, config_type) DO UPDATE
                SET config = EXCLUDED.config
            """),
            {"config_type": config_type, "config_value": config_json},
        )


def downgrade() -> None:
    bind = op.get_bind()

    # ── Remove seeded config ──────────────────────────────────────
    bind.execute(
        sa.text("""
            DELETE FROM vertical_config_defaults
            WHERE vertical = 'liquid_funds'
            AND config_type IN ('screening_layer1', 'screening_layer2', 'screening_layer3')
        """),
    )

    # ── Reverse universe_approvals renames ────────────────────────
    op.execute("ALTER TABLE universe_approvals DROP CONSTRAINT IF EXISTS universe_approvals_analysis_report_id_fkey")
    op.alter_column("universe_approvals", "analysis_report_id", new_column_name="dd_report_id", nullable=False)
    op.execute("""
        ALTER TABLE universe_approvals
        ADD CONSTRAINT universe_approvals_dd_report_id_fkey
        FOREIGN KEY (dd_report_id) REFERENCES dd_reports(id)
    """)

    op.execute("ALTER TABLE universe_approvals DROP CONSTRAINT IF EXISTS universe_approvals_instrument_id_fkey")
    op.alter_column("universe_approvals", "instrument_id", new_column_name="fund_id")
    op.execute("""
        ALTER TABLE universe_approvals
        ADD CONSTRAINT universe_approvals_fund_id_fkey
        FOREIGN KEY (fund_id) REFERENCES funds_universe(fund_id)
    """)

    # ── Reverse dd_reports changes ────────────────────────────────
    op.execute("ALTER TABLE dd_reports DROP CONSTRAINT IF EXISTS chk_dd_report_type")
    op.drop_column("dd_reports", "report_type")

    op.execute("ALTER TABLE dd_reports DROP CONSTRAINT IF EXISTS dd_reports_instrument_id_fkey")
    op.alter_column("dd_reports", "instrument_id", new_column_name="fund_id")
    op.execute("""
        ALTER TABLE dd_reports
        ADD CONSTRAINT dd_reports_fund_id_fkey
        FOREIGN KEY (fund_id) REFERENCES funds_universe(fund_id)
    """)

    # ── Reverse lipper_ratings rename ─────────────────────────────
    op.execute("ALTER TABLE lipper_ratings DROP CONSTRAINT IF EXISTS lipper_ratings_instrument_id_fkey")
    op.alter_column("lipper_ratings", "instrument_id", new_column_name="fund_id")
    op.execute("""
        ALTER TABLE lipper_ratings
        ADD CONSTRAINT lipper_ratings_fund_id_fkey
        FOREIGN KEY (fund_id) REFERENCES funds_universe(fund_id)
    """)

    # ── Reverse fund_risk_metrics rename ──────────────────────────
    op.execute("ALTER TABLE fund_risk_metrics DROP CONSTRAINT IF EXISTS fund_risk_metrics_instrument_id_fkey")
    op.alter_column("fund_risk_metrics", "instrument_id", new_column_name="fund_id")
    op.execute("""
        ALTER TABLE fund_risk_metrics
        ADD CONSTRAINT fund_risk_metrics_fund_id_fkey
        FOREIGN KEY (fund_id) REFERENCES funds_universe(fund_id)
    """)

    # ── Reverse nav_timeseries rename ─────────────────────────────
    op.execute("ALTER TABLE nav_timeseries DROP CONSTRAINT IF EXISTS nav_timeseries_instrument_id_fkey")
    op.alter_column("nav_timeseries", "instrument_id", new_column_name="fund_id")
    op.execute("""
        ALTER TABLE nav_timeseries
        ADD CONSTRAINT nav_timeseries_fund_id_fkey
        FOREIGN KEY (fund_id) REFERENCES funds_universe(fund_id)
    """)

    # ── Delete migrated data from instruments_universe ────────────
    op.execute("DELETE FROM instruments_universe WHERE instrument_type = 'fund'")


def _drop_fk_by_column(bind, table_name: str, column_name: str) -> None:
    """Drop FK constraint by discovering its name from pg_constraint."""
    result = bind.execute(
        sa.text("""
            SELECT conname FROM pg_constraint
            WHERE conrelid = CAST(:table_name AS regclass)
            AND contype = 'f'
            AND EXISTS (
                SELECT 1 FROM unnest(conkey) AS k
                JOIN pg_attribute a ON a.attrelid = conrelid AND a.attnum = k
                WHERE a.attname = :column
            )
        """),
        {"table_name": table_name, "column": column_name},
    ).fetchone()
    if result:
        op.execute(f"ALTER TABLE {table_name} DROP CONSTRAINT {result[0]}")
