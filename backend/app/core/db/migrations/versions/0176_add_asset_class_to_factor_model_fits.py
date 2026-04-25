"""add asset_class column to factor_model_fits

Splits the (panel-identifying) universe_hash from the (lookup-key)
asset_class. Worker writes asset_class explicitly; rail filters by it.
universe_hash remains MD5 of the panel for drift tracking.

Revision ID: 0176_add_asset_class_to_factor_model_fits
Revises: 0175_add_issuer_cik_to_cusip_map
Create Date: 2026-04-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0176_add_asset_class_to_factor_model_fits"
down_revision = "0175_add_issuer_cik_to_cusip_map"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "factor_model_fits",
        sa.Column(
            "asset_class",
            sa.String(length=32),
            nullable=False,
            server_default="Equity",
        ),
    )
    op.drop_index(
        "ix_factor_model_fits_lookup",
        table_name="factor_model_fits",
    )
    op.create_index(
        "ix_factor_model_fits_lookup",
        "factor_model_fits",
        ["engine", "asset_class", "fit_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_factor_model_fits_lookup",
        table_name="factor_model_fits",
    )
    op.create_index(
        "ix_factor_model_fits_lookup",
        "factor_model_fits",
        ["engine", "universe_hash", "converged", "fit_date"],
        unique=False,
    )
    op.drop_column("factor_model_fits", "asset_class")
