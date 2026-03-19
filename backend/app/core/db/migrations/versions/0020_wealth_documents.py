"""wealth_documents and wealth_document_versions tables

Revision ID: 0020_wealth_docs
Revises: f5aca0aa8f32
Create Date: 2026-03-19 18:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_wealth_docs"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── wealth_documents ─────────────────────────────────────
    op.create_table(
        "wealth_documents",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("portfolio_id", sa.Uuid(as_uuid=True), nullable=True, index=True),
        sa.Column("instrument_id", sa.Uuid(as_uuid=True), nullable=True, index=True),
        sa.Column("title", sa.String(300), nullable=False, index=True),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(200), nullable=True),
        sa.Column("root_folder", sa.String(200), nullable=False, server_default="documents", index=True),
        sa.Column("subfolder_path", sa.String(800), nullable=True),
        sa.Column("domain", sa.Text(), nullable=True, index=True),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("updated_by", sa.String(128), nullable=True),
        sa.UniqueConstraint("organization_id", "root_folder", "subfolder_path", "title", name="uq_wealth_docs_org_folder_title"),
    )
    op.create_index("ix_wealth_docs_org_portfolio", "wealth_documents", ["organization_id", "portfolio_id"])
    op.create_index("ix_wealth_docs_org_instrument", "wealth_documents", ["organization_id", "instrument_id"])

    # ── wealth_document_versions ─────────────────────────────
    # Reuse existing document_ingestion_status_enum (created by credit migration)
    op.create_table(
        "wealth_document_versions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("document_id", sa.Uuid(as_uuid=True), sa.ForeignKey("wealth_documents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("portfolio_id", sa.Uuid(as_uuid=True), nullable=True, index=True),
        sa.Column("version_number", sa.Integer(), nullable=False, index=True),
        sa.Column("blob_uri", sa.String(800), nullable=True),
        sa.Column("blob_path", sa.String(800), nullable=True, index=True),
        sa.Column("checksum", sa.String(128), nullable=True),
        sa.Column("file_size_bytes", sa.Numeric(20, 0), nullable=True),
        sa.Column("content_type", sa.String(200), nullable=True),
        sa.Column("ingestion_status", sa.String(32), nullable=False, server_default="PENDING", index=True),
        sa.Column("ingestion_error", sa.JSON(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_by", sa.String(200), nullable=True, index=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("updated_by", sa.String(128), nullable=True),
    )
    op.create_index("ix_wealth_doc_ver_doc_ver", "wealth_document_versions", ["document_id", "version_number"], unique=True)

    # ── RLS policies ─────────────────────────────────────────
    # Must use (SELECT current_setting(...)) subselect for performance
    for table in ("wealth_documents", "wealth_document_versions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))
        """)
        op.execute(f"""
            CREATE POLICY {table}_tenant_insert ON {table}
            FOR INSERT
            WITH CHECK (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))
        """)


def downgrade() -> None:
    for table in ("wealth_document_versions", "wealth_documents"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_insert ON {table}")
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.drop_table(table)
