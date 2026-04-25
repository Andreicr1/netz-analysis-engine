"""curated institutions seed

Revision ID: 0097_curated_institutions_seed
Revises: 0096_discovery_fcl_keyset_indexes
Create Date: 2026-04-08
"""
import sqlalchemy as sa
from alembic import op

revision = "0097_curated_institutions_seed"
down_revision = "0096_discovery_fcl_keyset_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "curated_institutions",
        sa.Column("institution_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("cik", sa.String(20), nullable=True),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("country", sa.String(3), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index(
        "idx_curated_institutions_category",
        "curated_institutions",
        ["category", "display_order"],
    )

    seed = [
        # Endowments
        ("yale_endowment", "Yale University Endowment", "endowment", "USA"),
        ("harvard_endowment", "Harvard University Endowment", "endowment", "USA"),
        ("princeton_endowment", "Princeton University Endowment", "endowment", "USA"),
        ("mit_endowment", "MIT Investment Management Company", "endowment", "USA"),
        ("stanford_endowment", "Stanford Management Company", "endowment", "USA"),
        ("columbia_endowment", "Columbia University Endowment", "endowment", "USA"),
        ("penn_endowment", "University of Pennsylvania Endowment", "endowment", "USA"),
        ("notre_dame_endowment", "University of Notre Dame Endowment", "endowment", "USA"),
        # Family offices
        ("olayan_group", "Olayan Group", "family_office", "SAU"),
        ("iconiq_capital", "ICONIQ Capital", "family_office", "USA"),
        ("pictet_wealth", "Pictet Wealth Management", "family_office", "CHE"),
        ("rockefeller_cm", "Rockefeller Capital Management", "family_office", "USA"),
        ("bessemer_trust", "Bessemer Trust", "family_office", "USA"),
        # Foundations
        ("gates_foundation", "Bill & Melinda Gates Foundation Trust", "foundation", "USA"),
        # Sovereign funds
        ("norges_bank", "Norges Bank Investment Management", "sovereign_fund", "NOR"),
        ("temasek", "Temasek Holdings", "sovereign_fund", "SGP"),
    ]
    conn = op.get_bind()
    for i, (inst_id, name, category, country) in enumerate(seed):
        conn.execute(
            sa.text(
                """
                INSERT INTO curated_institutions
                  (institution_id, name, category, country, display_order, active)
                VALUES (:id, :name, :cat, :country, :ord, true)
                ON CONFLICT (institution_id) DO NOTHING
                """
            ),
            {"id": inst_id, "name": name, "cat": category, "country": country, "ord": i * 10},
        )


def downgrade() -> None:
    op.drop_index("idx_curated_institutions_category", table_name="curated_institutions")
    op.drop_table("curated_institutions")
