"""SEC data providers — 6 global tables.

Creates global tables (no organization_id, no RLS) for SEC/EDGAR data:
  - sec_managers: Form ADV manager catalog
  - sec_manager_funds: ADV Schedule D private funds
  - sec_manager_team: ADV Part 2A team bios
  - sec_13f_holdings: 13F quarterly holdings
  - sec_13f_diffs: Quarter-over-quarter changes
  - sec_institutional_allocations: Institutional 13F reverse lookup

All tables are GLOBAL (shared across all tenants), same pattern as
macro_data, benchmark_nav, allocation_blocks.

depends_on: 0022 (wealth_status_constraints).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0023_sec_data_providers"
down_revision = "0022_wealth_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════
    #  sec_managers — global table (no org_id, no RLS)
    #  Form ADV manager catalog. Natural PK on crd_number.
    # ═══════════════════════════════════════════════════════════════
    op.create_table(
        "sec_managers",
        sa.Column("crd_number", sa.Text(), nullable=False),
        sa.Column("cik", sa.Text()),
        sa.Column("firm_name", sa.Text(), nullable=False),
        sa.Column("sec_number", sa.Text()),
        sa.Column("registration_status", sa.Text()),
        sa.Column("aum_total", sa.BigInteger()),
        sa.Column("aum_discretionary", sa.BigInteger()),
        sa.Column("aum_non_discretionary", sa.BigInteger()),
        sa.Column("total_accounts", sa.Integer()),
        sa.Column("fee_types", postgresql.JSONB()),
        sa.Column("client_types", postgresql.JSONB()),
        sa.Column("state", sa.Text()),
        sa.Column("country", sa.Text()),
        sa.Column("website", sa.Text()),
        sa.Column("compliance_disclosures", sa.Integer()),
        sa.Column("last_adv_filed_at", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("data_fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("crd_number"),
    )
    op.create_index(
        "idx_sec_managers_cik",
        "sec_managers",
        ["cik"],
        postgresql_where=sa.text("cik IS NOT NULL"),
    )

    # ═══════════════════════════════════════════════════════════════
    #  sec_manager_funds — global table (no org_id, no RLS)
    #  ADV Schedule D private funds. FK to sec_managers.
    # ═══════════════════════════════════════════════════════════════
    op.create_table(
        "sec_manager_funds",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("crd_number", sa.Text(), sa.ForeignKey("sec_managers.crd_number", ondelete="CASCADE"), nullable=False),
        sa.Column("fund_name", sa.Text(), nullable=False),
        sa.Column("fund_id", sa.Text()),
        sa.Column("gross_asset_value", sa.BigInteger()),
        sa.Column("fund_type", sa.Text()),
        sa.Column("is_fund_of_funds", sa.Boolean()),
        sa.Column("investor_count", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("data_fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crd_number", "fund_name", name="uq_sec_manager_funds_crd_name"),
    )

    # ═══════════════════════════════════════════════════════════════
    #  sec_manager_team — global table (no org_id, no RLS)
    #  ADV Part 2A team bios. FK to sec_managers.
    # ═══════════════════════════════════════════════════════════════
    op.create_table(
        "sec_manager_team",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("crd_number", sa.Text(), sa.ForeignKey("sec_managers.crd_number", ondelete="CASCADE"), nullable=False),
        sa.Column("person_name", sa.Text(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("role", sa.Text()),
        sa.Column("education", postgresql.JSONB()),
        sa.Column("certifications", postgresql.ARRAY(sa.Text())),
        sa.Column("years_experience", sa.Integer()),
        sa.Column("bio_summary", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("data_fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crd_number", "person_name", name="uq_sec_manager_team_crd_person"),
    )

    # ═══════════════════════════════════════════════════════════════
    #  sec_13f_holdings — global table (no org_id, no RLS)
    #  13F quarterly holdings.
    # ═══════════════════════════════════════════════════════════════
    op.create_table(
        "sec_13f_holdings",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("cik", sa.Text(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("accession_number", sa.Text(), nullable=False),
        sa.Column("cusip", sa.Text(), nullable=False),
        sa.Column("issuer_name", sa.Text(), nullable=False),
        sa.Column("asset_class", sa.Text()),
        sa.Column("shares", sa.BigInteger()),
        sa.Column("market_value", sa.BigInteger()),
        sa.Column("discretion", sa.Text()),
        sa.Column("voting_sole", sa.BigInteger()),
        sa.Column("voting_shared", sa.BigInteger()),
        sa.Column("voting_none", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("data_fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cik", "report_date", "cusip", name="uq_sec_13f_holdings_cik_date_cusip"),
    )
    op.create_index("idx_sec_13f_holdings_cik_report_date", "sec_13f_holdings", ["cik", "report_date"])
    # Covering index for cross-manager portfolio overlap queries
    op.execute("""
        CREATE INDEX idx_sec_13f_holdings_cusip_report_date
        ON sec_13f_holdings (cusip, report_date)
        INCLUDE (cik, shares, market_value)
    """)

    # ═══════════════════════════════════════════════════════════════
    #  sec_13f_diffs — global table (no org_id, no RLS)
    #  Quarter-over-quarter changes.
    # ═══════════════════════════════════════════════════════════════
    op.create_table(
        "sec_13f_diffs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("cik", sa.Text(), nullable=False),
        sa.Column("cusip", sa.Text(), nullable=False),
        sa.Column("issuer_name", sa.Text(), nullable=False),
        sa.Column("quarter_from", sa.Date(), nullable=False),
        sa.Column("quarter_to", sa.Date(), nullable=False),
        sa.Column("shares_before", sa.BigInteger()),
        sa.Column("shares_after", sa.BigInteger()),
        sa.Column("shares_delta", sa.BigInteger()),
        sa.Column("value_before", sa.BigInteger()),
        sa.Column("value_after", sa.BigInteger()),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("weight_before", sa.Float()),
        sa.Column("weight_after", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cik", "cusip", "quarter_from", "quarter_to", name="uq_sec_13f_diffs_cik_cusip_quarters"),
    )
    op.create_index("idx_sec_13f_diffs_cik_quarter_to", "sec_13f_diffs", ["cik", "quarter_to"])
    op.create_index("idx_sec_13f_diffs_cusip_quarter_to", "sec_13f_diffs", ["cusip", "quarter_to"])

    # Action CHECK constraint
    op.execute("""
        ALTER TABLE sec_13f_diffs
        ADD CONSTRAINT chk_sec_13f_diffs_action
        CHECK (action IN ('NEW_POSITION', 'INCREASED', 'DECREASED', 'EXITED', 'UNCHANGED'))
    """)

    # ═══════════════════════════════════════════════════════════════
    #  sec_institutional_allocations — global table (no org_id, no RLS)
    #  Institutional 13F reverse lookup.
    # ═══════════════════════════════════════════════════════════════
    op.create_table(
        "sec_institutional_allocations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("filer_cik", sa.Text(), nullable=False),
        sa.Column("filer_name", sa.Text(), nullable=False),
        sa.Column("filer_type", sa.Text()),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("target_cusip", sa.Text(), nullable=False),
        sa.Column("target_issuer", sa.Text(), nullable=False),
        sa.Column("market_value", sa.BigInteger()),
        sa.Column("shares", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("filer_cik", "report_date", "target_cusip", name="uq_sec_inst_alloc_filer_date_cusip"),
    )
    # Covering index for reverse lookup (who holds this security)
    op.execute("""
        CREATE INDEX idx_sec_inst_alloc_target_cusip_date
        ON sec_institutional_allocations (target_cusip, report_date DESC)
        INCLUDE (filer_cik, filer_name, filer_type, market_value, shares)
    """)
    op.create_index("idx_sec_inst_alloc_filer_cik_date", "sec_institutional_allocations", ["filer_cik", "report_date"])


def downgrade() -> None:
    op.drop_table("sec_institutional_allocations")
    op.drop_table("sec_13f_diffs")
    op.execute("DROP INDEX IF EXISTS idx_sec_13f_holdings_cusip_report_date")
    op.drop_table("sec_13f_holdings")
    op.drop_table("sec_manager_team")
    op.drop_table("sec_manager_funds")
    op.drop_table("sec_managers")
