"""add pgvector extension and vector_chunks table with HNSW index

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-03-18 18:01:00.000000
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create vector_chunks table
    op.execute("""
        CREATE TABLE IF NOT EXISTS vector_chunks (
            id TEXT PRIMARY KEY,
            organization_id UUID NOT NULL,
            deal_id TEXT,
            fund_id TEXT,
            domain TEXT NOT NULL,
            doc_type TEXT,
            doc_id TEXT,
            title TEXT,
            content TEXT NOT NULL,
            page_start INTEGER,
            page_end INTEGER,
            chunk_index INTEGER,
            section_type TEXT,
            breadcrumb TEXT,
            governance_critical BOOLEAN DEFAULT FALSE,
            embedding vector(3072),
            embedding_model TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # HNSW index for approximate nearest neighbor search.
    # pgvector HNSW limits vector type to 2000 dims, but halfvec supports
    # up to 4000. Cast embedding to halfvec(3072) in the index expression
    # so the column stays vector(3072) (no app code changes needed).
    # Queries must cast to halfvec for index usage:
    #   ORDER BY embedding::halfvec(3072) <=> :query::halfvec(3072)
    op.execute("""
        CREATE INDEX IF NOT EXISTS vector_chunks_embedding_hnsw
            ON vector_chunks
            USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)
            WITH (m = 16, ef_construction = 64)
    """)

    # Tenant isolation index (RLS path)
    op.execute("""
        CREATE INDEX IF NOT EXISTS vector_chunks_org_id_idx
            ON vector_chunks (organization_id)
    """)

    # Composite index for frequent deal queries
    op.execute("""
        CREATE INDEX IF NOT EXISTS vector_chunks_org_deal_idx
            ON vector_chunks (organization_id, deal_id)
    """)

    # Composite index for fund policy queries
    op.execute("""
        CREATE INDEX IF NOT EXISTS vector_chunks_org_fund_idx
            ON vector_chunks (organization_id, fund_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vector_chunks")
    op.execute("DROP EXTENSION IF EXISTS vector")
