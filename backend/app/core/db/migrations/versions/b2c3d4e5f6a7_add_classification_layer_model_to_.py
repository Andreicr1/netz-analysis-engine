"""add classification_layer and classification_model to document_reviews

Revision ID: b2c3d4e5f6a7
Revises: f5aca0aa8f32
Create Date: 2026-03-18
"""
from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "f5aca0aa8f32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_reviews", sa.Column("classification_layer", sa.Integer(), nullable=True))
    op.add_column("document_reviews", sa.Column("classification_model", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("document_reviews", "classification_model")
    op.drop_column("document_reviews", "classification_layer")
