"""wealth_vector_chunks — fund-centric vector index for Wealth vertical.

Revision ID: 0059_wealth_vector_chunks
Revises: 0058
Create Date: 2026-03-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0059_wealth_vector_chunks"
down_revision: str | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create table via raw SQL — vector(3072) column inline.
    # pgvector extension already enabled by e2f3a4b5c6d7_pgvector_vector_chunks.
    op.execute("""
        CREATE TABLE IF NOT EXISTS wealth_vector_chunks (
            id TEXT PRIMARY KEY,
            organization_id UUID,
            entity_id TEXT,
            entity_type TEXT NOT NULL,
            source_type TEXT NOT NULL,
            section TEXT,
            content TEXT NOT NULL,
            language TEXT DEFAULT 'en',
            source_row_id TEXT,
            firm_crd TEXT,
            filing_date DATE,
            embedding vector(3072),
            embedding_model TEXT,
            embedded_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # HNSW index — halfvec(3072) cast for >2000 dims (same pattern as vector_chunks).
    op.execute("""
        CREATE INDEX IF NOT EXISTS wealth_vector_chunks_embedding_hnsw
            ON wealth_vector_chunks
            USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)
            WITH (m = 16, ef_construction = 64)
    """)

    # Auxiliary indexes
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_wvc_org
            ON wealth_vector_chunks (organization_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_wvc_entity_id
            ON wealth_vector_chunks (entity_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_wvc_firm_crd
            ON wealth_vector_chunks (firm_crd)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_wvc_entity
            ON wealth_vector_chunks (entity_type, entity_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_wvc_source
            ON wealth_vector_chunks (source_type, section)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_wvc_org_entity
            ON wealth_vector_chunks (organization_id, entity_type)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wealth_vector_chunks")
