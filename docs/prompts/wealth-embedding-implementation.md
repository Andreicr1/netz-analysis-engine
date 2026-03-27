# Wealth Vector Embedding — Prompt de Implementação

## Contexto

O vertical Wealth tem ~30k rows de conteúdo semântico sem embedding.
Esta tarefa cria a infraestrutura completa de vetorização fund-centric.

**Spec de referência completo:**
`docs/reference/wealth-vector-embedding-spec.md` — ler antes de começar.

**Princípio arquitetural crítico (fund-centric-pivot-audit.md):**
- `entity_type="manager"` NÃO EXISTE neste sistema — manager = PM individual
- Brochures ADV e ESMA managers usam `entity_type="firm"` (RIA / ManCo)
- A API de busca é sempre fund-centric: caller passa `instrument_id` ou CRD

---

## Leitura obrigatória antes de qualquer edição

```
backend/app/domains/credit/documents/models/vector_chunk.py
backend/ai_engine/extraction/pgvector_search_service.py
backend/ai_engine/extraction/embedding_service.py
backend/app/domains/wealth/workers/brochure_ingestion.py
backend/app/domains/admin/routes/worker_registry.py
backend/app/core/db/base.py                          (para Base e OrganizationScopedMixin)
backend/app/domains/wealth/models/instrument.py      (para campos attributes JSONB)
backend/app/domains/wealth/models/dd_report.py       (para FK instrument_id)
backend/app/domains/wealth/models/macro.py           (para campos macro_reviews)
```

Verificar também o head atual de migrations:
```bash
alembic current
```

---

## Arquivos a criar

```
backend/app/domains/wealth/models/wealth_vector_chunk.py     (novo)
backend/app/domains/wealth/workers/wealth_embedding_worker.py (novo)
backend/app/core/db/migrations/versions/0059_wealth_vector_chunks.py (novo)
```

## Arquivos a modificar

```
backend/ai_engine/extraction/pgvector_search_service.py      (adicionar 3 funções)
backend/app/domains/admin/routes/worker_registry.py          (registrar worker)
railway.toml                                                  (novo cron)
```

---

## Etapa 1 — Model `WealthVectorChunk`

Criar `backend/app/domains/wealth/models/wealth_vector_chunk.py`:

```python
from __future__ import annotations
import datetime as dt
from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Date, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db.base import Base

class WealthVectorChunk(Base):
    """Índice vetorial fund-centric para o vertical Wealth.

    Separado de vector_chunks (Credit/deal-centric).
    organization_id nullable: NULL = dado global (SEC/ESMA, sem tenant).

    entity_type values:
      "firm"  — RIA / Management Company (brochure ADV, ESMA manager)
      "fund"  — instrumento fundo (ESMA fund, DD chapter)
      "macro" — macro review
    NUNCA usar "manager" — manager = PM individual no domínio do sistema.

    firm_crd: CRD da firma gestora, preenchido para entity_type="firm".
    Índice que habilita: instrument.attributes["sec_crd"] → firm_crd → chunks.
    """
    __tablename__ = "wealth_vector_chunks"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    organization_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), nullable=True, index=True
    )
    entity_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(Text, nullable=True, default="en")
    source_row_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    firm_crd: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    filing_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(3072), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedded_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

---

## Etapa 2 — Migration `0059_wealth_vector_chunks.py`

Usar o número de revisão correto (verificar `alembic current` primeiro).
Seguir o padrão de migrations existentes para HNSW index (autocommit obrigatório).

```python
"""wealth_vector_chunks — índice vetorial fund-centric

Revision ID: <gerar>
Revises: <head atual>
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade() -> None:
    op.create_table(
        "wealth_vector_chunks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(), nullable=True),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=True, server_default="en"),
        sa.Column("source_row_id", sa.Text(), nullable=True),
        sa.Column("firm_crd", sa.Text(), nullable=True),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("embedding", sa.Text(), nullable=True),   # declarado como Text aqui,
        # Vector(3072) aplicado abaixo via ALTER — pgvector requer autocommit
        sa.Column("embedding_model", sa.Text(), nullable=True),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )

    # Converter embedding para vector(3072) e criar HNSW index em autocommit
    bind = op.get_bind()
    with bind.execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(sa.text(
            "ALTER TABLE wealth_vector_chunks "
            "ALTER COLUMN embedding TYPE vector(3072) "
            "USING embedding::vector(3072)"
        ))
        conn.execute(sa.text("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS
            wealth_vector_chunks_embedding_idx
            ON wealth_vector_chunks
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """))

    # Índices auxiliares (dentro de transaction normal)
    op.create_index("ix_wvc_org", "wealth_vector_chunks", ["organization_id"])
    op.create_index("ix_wvc_entity_id", "wealth_vector_chunks", ["entity_id"])
    op.create_index("ix_wvc_firm_crd", "wealth_vector_chunks", ["firm_crd"])
    op.create_index("ix_wvc_entity", "wealth_vector_chunks",
                    ["entity_type", "entity_id"])
    op.create_index("ix_wvc_source", "wealth_vector_chunks",
                    ["source_type", "section"])
    op.create_index("ix_wvc_org_entity", "wealth_vector_chunks",
                    ["organization_id", "entity_type"])

def downgrade() -> None:
    op.drop_table("wealth_vector_chunks")
```

**ATENÇÃO:** Verificar como as migrations existentes que usam Vector/pgvector
tratam o tipo — ler a migration de `vector_chunks` como referência antes de
escrever esta.

---

## Etapa 3 — Worker `wealth_embedding_worker.py`

Criar `backend/app/domains/wealth/workers/wealth_embedding_worker.py`.

### Constantes e imports obrigatórios

```python
"""Wealth embedding worker — vetoriza fontes Wealth em wealth_vector_chunks.

Fontes:
  A. sec_manager_brochure_text → entity_type="firm", source_type="brochure"
  B. esma_funds                → entity_type="fund", source_type="esma_fund"
  C. esma_managers             → entity_type="firm", source_type="esma_manager"
  D. dd_chapters               → entity_type="fund", source_type="dd_chapter"
  E. macro_reviews             → entity_type="macro", source_type="macro_review"

Advisory lock: 900_041 (global)
Frequência: diário (cron 3h UTC)
"""
from datetime import datetime, timezone
from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from ai_engine.extraction.embedding_service import async_generate_embeddings
from app.core.db.engine import async_session_factory as async_session
from app.domains.wealth.models.wealth_vector_chunk import WealthVectorChunk

logger = structlog.get_logger()

WEALTH_EMBEDDING_LOCK_ID = 900_041
EMBED_BATCH_SIZE = 100
UPSERT_BATCH_SIZE = 200

BROCHURE_EMBED_SECTIONS = frozenset({
    "investment_philosophy", "methods_of_analysis", "advisory_business",
    "risk_management", "performance_fees", "full_brochure",
})

BROCHURE_SECTION_LABELS = {
    "investment_philosophy": "Investment Philosophy",
    "methods_of_analysis": "Methods of Analysis",
    "advisory_business": "Advisory Business",
    "risk_management": "Risk Management",
    "performance_fees": "Performance Fees",
    "full_brochure": "ADV Part 2A Brochure",
}
```

### Entry point e helpers

```python
async def run_wealth_embedding() -> dict:
    async with async_session() as db:
        lock = await db.execute(
            text(f"SELECT pg_try_advisory_lock({WEALTH_EMBEDDING_LOCK_ID})")
        )
        if not lock.scalar():
            logger.warning("wealth_embedding.lock_held")
            return {"status": "skipped", "reason": "lock_held"}
        try:
            stats: dict = {}
            stats["brochure"]      = await _embed_brochure_sections(db)
            stats["esma_funds"]    = await _embed_esma_funds(db)
            stats["esma_managers"] = await _embed_esma_managers(db)
            stats["dd_chapters"]   = await _embed_dd_chapters(db)
            stats["macro_reviews"] = await _embed_macro_reviews(db)
            logger.info("wealth_embedding.complete", **stats)
            return {"status": "completed", **stats}
        finally:
            try:
                await db.execute(
                    text(f"SELECT pg_advisory_unlock({WEALTH_EMBEDDING_LOCK_ID})")
                )
            except Exception:
                pass


async def _batch_upsert(db: AsyncSession, rows: list[dict]) -> None:
    """Upsert em wealth_vector_chunks com ON CONFLICT DO UPDATE."""
    for i in range(0, len(rows), UPSERT_BATCH_SIZE):
        chunk = rows[i : i + UPSERT_BATCH_SIZE]
        stmt = pg_insert(WealthVectorChunk.__table__).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "content": stmt.excluded.content,
                "embedding": stmt.excluded.embedding,
                "embedding_model": stmt.excluded.embedding_model,
                "embedded_at": stmt.excluded.embedded_at,
                "updated_at": func.now(),
            },
        )
        await db.execute(stmt)
    await db.commit()
```

### Fonte A — Brochures ADV

```python
async def _embed_brochure_sections(db: AsyncSession) -> dict:
    """Embeda seções semânticas de sec_manager_brochure_text → entity_type='firm'."""
    result = await db.execute(text("""
        SELECT b.crd_number, b.section, b.content, b.filing_date
        FROM sec_manager_brochure_text b
        LEFT JOIN wealth_vector_chunks w
          ON w.id = 'brochure_' || b.crd_number || '_' || b.section
        WHERE b.section = ANY(:sections)
          AND (w.id IS NULL
               OR (b.filing_date IS NOT NULL
                   AND b.filing_date > w.embedded_at::date))
        ORDER BY b.crd_number
        LIMIT 10000
    """), {"sections": list(BROCHURE_EMBED_SECTIONS)})

    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = [
        f"[{BROCHURE_SECTION_LABELS.get(r.section, r.section)}] {r.content[:4000]}"
        for r in rows
    ]
    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    upsert_rows = [
        {
            "id": f"brochure_{r.crd_number}_{r.section}",
            "organization_id": None,
            "entity_id": r.crd_number,
            "entity_type": "firm",        # firma RIA — NUNCA "manager"
            "source_type": "brochure",
            "section": r.section,
            "content": texts[i],
            "language": "en",
            "source_row_id": r.crd_number,
            "firm_crd": r.crd_number,     # índice fund→firma
            "filing_date": r.filing_date,
            "embedding": batch.vectors[i],
            "embedding_model": batch.model,
            "embedded_at": now,
        }
        for i, r in enumerate(rows)
    ]
    await _batch_upsert(db, upsert_rows)
    logger.info("wealth_embedding.brochure_done", embedded=len(rows))
    return {"embedded": len(rows)}
```

### Fonte B — ESMA Funds

```python
async def _embed_esma_funds(db: AsyncSession) -> dict:
    """Embeda esma_funds → entity_type='fund' (objeto de análise direto)."""
    result = await db.execute(text("""
        SELECT e.isin, e.fund_name, e.fund_type, e.domicile, e.esma_manager_id
        FROM esma_funds e
        LEFT JOIN wealth_vector_chunks w ON w.id = 'esma_fund_' || e.isin
        WHERE e.fund_name IS NOT NULL
          AND w.id IS NULL
        ORDER BY e.isin
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = [
        f"{r.fund_name} | {r.fund_type or 'UCITS'} | {r.domicile or ''}"
        for r in rows
    ]
    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    upsert_rows = [
        {
            "id": f"esma_fund_{r.isin}",
            "organization_id": None,
            "entity_id": r.isin,
            "entity_type": "fund",
            "source_type": "esma_fund",
            "section": None,
            "content": texts[i],
            "language": "en",
            "source_row_id": r.isin,
            "firm_crd": None,
            "filing_date": None,
            "embedding": batch.vectors[i],
            "embedding_model": batch.model,
            "embedded_at": now,
        }
        for i, r in enumerate(rows)
    ]
    await _batch_upsert(db, upsert_rows)
    logger.info("wealth_embedding.esma_funds_done", embedded=len(rows))
    return {"embedded": len(rows)}
```

### Fonte C — ESMA Managers

```python
async def _embed_esma_managers(db: AsyncSession) -> dict:
    """Embeda esma_managers → entity_type='firm' (Management Company)."""
    result = await db.execute(text("""
        SELECT e.esma_id, e.company_name, e.country,
               e.authorization_status, e.sec_crd_number
        FROM esma_managers e
        LEFT JOIN wealth_vector_chunks w ON w.id = 'esma_manager_' || e.esma_id
        WHERE e.company_name IS NOT NULL
          AND w.id IS NULL
        ORDER BY e.esma_id
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = [
        f"{r.company_name} | {r.country or ''} | {r.authorization_status or ''}"
        for r in rows
    ]
    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    upsert_rows = [
        {
            "id": f"esma_manager_{r.esma_id}",
            "organization_id": None,
            "entity_id": r.esma_id,
            "entity_type": "firm",        # Management Company — NUNCA "manager"
            "source_type": "esma_manager",
            "section": None,
            "content": texts[i],
            "language": "en",
            "source_row_id": r.esma_id,
            "firm_crd": r.sec_crd_number, # preenchido se linkado a RIA americana
            "filing_date": None,
            "embedding": batch.vectors[i],
            "embedding_model": batch.model,
            "embedded_at": now,
        }
        for i, r in enumerate(rows)
    ]
    await _batch_upsert(db, upsert_rows)
    logger.info("wealth_embedding.esma_managers_done", embedded=len(rows))
    return {"embedded": len(rows)}
```

### Fontes D e E — DD Chapters e Macro Reviews

```python
async def _embed_dd_chapters(db: AsyncSession) -> dict:
    """Embeda dd_chapters org-scoped → entity_type='fund'.

    entity_id = instrument_id do fundo analisado (via dd_reports FK).
    Lê instrument_id via dd_reports — ler o modelo dd_report antes de
    escrever esta query para confirmar o nome exato da FK.
    """
    result = await db.execute(text("""
        SELECT c.id AS chapter_id,
               r.instrument_id,
               r.organization_id,
               c.chapter_tag,
               c.content_md
        FROM dd_chapters c
        JOIN dd_reports r ON r.id = c.report_id
        LEFT JOIN wealth_vector_chunks w ON w.id = 'dd_chapter_' || c.id::text
        WHERE c.content_md IS NOT NULL
          AND length(c.content_md) > 100
          AND w.id IS NULL
        ORDER BY c.id
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = [r.content_md[:6000] for r in rows]
    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    upsert_rows = [
        {
            "id": f"dd_chapter_{r.chapter_id}",
            "organization_id": str(r.organization_id),
            "entity_id": str(r.instrument_id),
            "entity_type": "fund",        # instrumento analisado = o fundo
            "source_type": "dd_chapter",
            "section": r.chapter_tag,
            "content": texts[i],
            "language": "en",
            "source_row_id": str(r.chapter_id),
            "firm_crd": None,
            "filing_date": None,
            "embedding": batch.vectors[i],
            "embedding_model": batch.model,
            "embedded_at": now,
        }
        for i, r in enumerate(rows)
    ]
    await _batch_upsert(db, upsert_rows)
    logger.info("wealth_embedding.dd_chapters_done", embedded=len(rows))
    return {"embedded": len(rows)}


async def _embed_macro_reviews(db: AsyncSession) -> dict:
    """Embeda macro_reviews org-scoped → entity_type='macro'.

    Embeda decision_rationale como chunk principal.
    Ler o modelo macro_reviews antes de escrever esta query para confirmar
    o nome exato das colunas (decision_rationale, organization_id, report_json).
    """
    result = await db.execute(text("""
        SELECT id, organization_id, decision_rationale, created_at
        FROM macro_reviews
        WHERE decision_rationale IS NOT NULL
          AND length(decision_rationale) > 50
          AND NOT EXISTS (
              SELECT 1 FROM wealth_vector_chunks
              WHERE id = 'macro_review_' || macro_reviews.id::text || '_rationale'
          )
        ORDER BY id
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = [r.decision_rationale[:6000] for r in rows]
    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    upsert_rows = [
        {
            "id": f"macro_review_{r.id}_rationale",
            "organization_id": str(r.organization_id),
            "entity_id": str(r.id),
            "entity_type": "macro",
            "source_type": "macro_review",
            "section": "rationale",
            "content": texts[i],
            "language": "en",
            "source_row_id": str(r.id),
            "firm_crd": None,
            "filing_date": r.created_at.date() if r.created_at else None,
            "embedding": batch.vectors[i],
            "embedding_model": batch.model,
            "embedded_at": now,
        }
        for i, r in enumerate(rows)
    ]
    await _batch_upsert(db, upsert_rows)
    logger.info("wealth_embedding.macro_reviews_done", embedded=len(rows))
    return {"embedded": len(rows)}
```

**Instrução:** antes de finalizar as queries de `_embed_dd_chapters` e
`_embed_macro_reviews`, ler os modelos `dd_report.py` e `macro.py` para
confirmar os nomes exatos de colunas e FKs.

---

## Etapa 4 — Registrar worker

Em `backend/app/domains/admin/routes/worker_registry.py`, dentro de
`_build_registry()`, adicionar:

```python
from app.domains.wealth.workers.wealth_embedding_worker import run_wealth_embedding

# na seção de global workers:
"wealth_embedding": (run_wealth_embedding, "global", _HEAVY),
```

---

## Etapa 5 — Cron no railway.toml

Adicionar ao `railway.toml` (ler o arquivo primeiro para seguir o padrão existente):

```toml
[[crons]]
name = "wealth-embedding"
schedule = "0 3 * * *"
command = "python -m app.workers.cli wealth_embedding"
```

---

## Etapa 6 — Search Service: 3 funções fund-centric

Em `backend/ai_engine/extraction/pgvector_search_service.py`, adicionar
ao final (antes de qualquer linha `if __name__ == "__main__"`):

### 6.1 `search_fund_firm_context_sync`

```python
def search_fund_firm_context_sync(
    *,
    query_vector: list[float],
    sec_crd: str | None = None,
    esma_manager_id: str | None = None,
    section_filter: list[str] | None = None,
    top: int = 20,
) -> list[dict[str, Any]]:
    """Busca semântica de contexto da firma gestora de um fundo.

    Fund-centric: o caller resolve instrument_id → sec_crd antes de chamar.
    Aceita sec_crd (US funds via ADV brochure) ou esma_manager_id (UCITS).
    Retorna entity_type="firm" da wealth_vector_chunks.
    """
    if not sec_crd and not esma_manager_id:
        return []

    params: dict[str, Any] = {
        "embedding": str(query_vector),
        "entity_type": "firm",
        "top": top,
    }
    if sec_crd:
        params["firm_crd"] = sec_crd
        extra_filter = "AND firm_crd = :firm_crd"
    else:
        params["esma_manager_id"] = esma_manager_id
        extra_filter = "AND entity_id = :esma_manager_id"

    section_clause = ""
    if section_filter:
        params["sections"] = section_filter
        section_clause = "AND section = ANY(:sections)"

    query = text(f"""
        SELECT id, entity_id, entity_type, source_type, section,
               content, source_row_id, firm_crd, filing_date,
               1 - (embedding <=> CAST(:embedding AS vector)) AS score
        FROM wealth_vector_chunks
        WHERE entity_type = :entity_type
          {extra_filter}
          {section_clause}
          AND embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:embedding AS vector)
        LIMIT :top
    """)
    engine = _get_sync_engine()
    with engine.connect() as conn:
        result = conn.execute(query, params)
        return [dict(r) for r in result.mappings().all()]
```

### 6.2 `search_esma_funds_sync`

```python
def search_esma_funds_sync(
    *,
    query_vector: list[float],
    domicile_filter: str | None = None,
    top: int = 20,
) -> list[dict[str, Any]]:
    """Busca semântica de fundos UCITS por nome/tipo/domicílio.

    Retorna entity_type="fund" (fundos ESMA, objeto de análise direto).
    """
    params: dict[str, Any] = {
        "embedding": str(query_vector),
        "top": top,
        "source_type": "esma_fund",
    }
    extra = ""
    if domicile_filter:
        params["domicile"] = domicile_filter
        extra = "AND content LIKE '%| ' || :domicile || '%'"

    query = text(f"""
        SELECT id, entity_id, source_type, content, source_row_id,
               1 - (embedding <=> CAST(:embedding AS vector)) AS score
        FROM wealth_vector_chunks
        WHERE source_type = :source_type
          AND embedding IS NOT NULL
          {extra}
        ORDER BY embedding <=> CAST(:embedding AS vector)
        LIMIT :top
    """)
    engine = _get_sync_engine()
    with engine.connect() as conn:
        result = conn.execute(query, params)
        return [dict(r) for r in result.mappings().all()]
```

### 6.3 `search_fund_analysis_sync`

```python
def search_fund_analysis_sync(
    *,
    organization_id: str,
    query_vector: list[float],
    instrument_id: str | None = None,
    source_type: str | None = None,
    top: int = 20,
) -> list[dict[str, Any]]:
    """Busca semântica em análises org-scoped de fundos.

    Fund-centric: instrument_id filtra chunks do fundo específico.
    Usado para DD chapters (source_type="dd_chapter") e macro reviews.
    """
    params: dict[str, Any] = {
        "embedding": str(query_vector),
        "org_id": validate_uuid(organization_id, "organization_id"),
        "top": top,
    }
    clauses: list[str] = []
    if source_type:
        params["source_type"] = source_type
        clauses.append("AND source_type = :source_type")
    if instrument_id:
        params["instrument_id"] = validate_uuid(instrument_id, "instrument_id")
        clauses.append("AND entity_id = :instrument_id")

    query = text(f"""
        SELECT id, entity_id, entity_type, source_type, section,
               content, source_row_id,
               1 - (embedding <=> CAST(:embedding AS vector)) AS score
        FROM wealth_vector_chunks
        WHERE organization_id = CAST(:org_id AS uuid)
          AND embedding IS NOT NULL
          {''.join(clauses)}
        ORDER BY embedding <=> CAST(:embedding AS vector)
        LIMIT :top
    """)
    engine = _get_sync_engine()
    with engine.connect() as conn:
        result = conn.execute(query, params)
        return [dict(r) for r in result.mappings().all()]
```

---

## Etapa 7 — Testes

Criar `backend/tests/test_wealth_embedding_worker.py`.

Cobrir:
- `_embed_brochure_sections`: idempotência (reroda sem duplicar), entity_type="firm"
- `_embed_esma_funds`: entity_type="fund", isin como entity_id
- `_embed_esma_managers`: entity_type="firm", firm_crd preenchido quando sec_crd_number disponível
- `_embed_dd_chapters`: organization_id preenchido, entity_id = instrument_id
- `run_wealth_embedding`: advisory lock impede segunda execução concorrente
- `search_fund_firm_context_sync`: retorna vazio quando sec_crd e esma_manager_id ambos None
- `search_fund_analysis_sync`: filtra por instrument_id corretamente

---

## Definition of Done

- [ ] `WealthVectorChunk` model sem `OrganizationScopedMixin`
- [ ] Migration `0059` com HNSW index em autocommit
- [ ] Worker com 5 fontes — entity_type nunca é `"manager"`
- [ ] `firm_crd` preenchido em brochures e esma_managers
- [ ] Lock ID `900_041` em `worker_registry.py`
- [ ] 3 funções fund-centric em `pgvector_search_service.py`
- [ ] Cron `wealth_embedding` em `railway.toml`
- [ ] `make check` passa (31/31 import-linter contracts)

## O que NÃO fazer

- Não usar `entity_type="manager"` — manager = PM individual no sistema
- Não usar `OrganizationScopedMixin` no model (força NOT NULL em org_id)
- Não adicionar RLS policy na tabela (dados globais têm org_id NULL)
- Não modificar `vector_chunks` (tabela do Credit, não tocar)
- Não embeddar seções operacionais de brochure: `brokerage_practices`,
  `custody`, `code_of_ethics`, `disciplinary`, `client_types`, `fees_compensation`
- Não fazer JOIN com `instruments_universe` no worker — as queries globais
  (brochure, esma) não têm org_id e não podem cruzar com tabelas org-scoped
- Não chamar OpenAI diretamente — usar sempre `async_generate_embeddings`
  do `ai_engine.extraction.embedding_service`

## Failure modes antecipados

- `dd_chapters.report_id` FK: ler o modelo antes de escrever a query —
  confirmar se é `report_id` ou outro nome
- `macro_reviews.organization_id`: confirmar que coluna existe no modelo
  antes de usar na query
- Migration: se `vector(3072)` falhar no `CREATE TABLE`, usar a abordagem
  de `ALTER COLUMN` pós-criação com autocommit (padrão das migrations existentes)
- Import linter: `wealth_embedding_worker.py` importa de `ai_engine/` —
  verificar se este import é permitido ou se precisa de intermediário
