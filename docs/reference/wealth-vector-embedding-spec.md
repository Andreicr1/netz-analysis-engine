# Wealth Vector Embedding — Spec de Implementação

## Contexto

O `vector_chunks` atual foi desenhado para o vertical Credit (deal_id central,
organization_id obrigatório, docs de deal). O vertical Wealth tem ~30k rows de
conteúdo semântico rico sem nenhum embedding:

| Tabela | Rows | Conteúdo |
|--------|------|----------|
| `sec_manager_brochure_text` | 17,837 | Texto ADV Part 2A (11 seções) |
| `esma_funds` | 10,436 | fund_name + fund_type + domicile |
| `esma_managers` | 658 | company_name + country |
| `dd_chapters` | 96 (crescimento) | content_md por capítulo (LLM-generated) |
| `macro_reviews` | 4 (crescimento) | decision_rationale + narrativa JSON |

**Objetivo:** habilitar busca semântica no agente AI (Copilot RAG) sobre
fundos, contexto da firma gestora, fundos europeus, análises qualitativas e
contexto macro.

## Princípio Fund-Centric (fund-centric-pivot-audit.md)

**O objeto de análise é sempre o fundo, nunca a firma.**

- `"manager"` no sistema = Portfolio Manager (indivíduo), não a firma RIA
- A firma RIA (Investment Adviser) é contexto do fundo, não o objeto de análise
- O agente AI deve buscar por fundo (`instrument_id` / ISIN) e obter contexto
  da firma como resultado derivado, nunca buscar pela firma diretamente

**Implicações para o design de embedding:**

| Fonte | Objeto real | `entity_type` correto |
|-------|------------|----------------------|
| ADV Part 2A brochure | RIA firma | `"firm"` (não "manager") |
| ESMA managers | Management company | `"firm"` |
| ESMA funds | Fundo UCITS | `"fund"` ✅ |
| DD chapters | Instrumento analisado | `"fund"` ✅ |
| Macro reviews | Review de macro | `"macro"` ✅ |

A API de busca expõe apenas interfaces fund-centric. Internamente resolve
`instrument_id → sec_crd / esma_manager_id → chunks da firma`.

---

## Decisão de Arquitetura

**NÃO modificar `vector_chunks`** — ela serve o Credit bem, com schema
deal-centric e RLS obrigatório. Dados globais SEC/ESMA não têm org_id.

**Criar `wealth_vector_chunks`** — nova tabela com schema entity-centric,
suportando tanto dados globais (organization_id NULL) quanto org-scoped.

**Padrão dual-write mantido:** storage relacional é source of truth.
`wealth_vector_chunks` é índice derivado — rebuild via script se necessário.

---

## 1. Nova Tabela: `wealth_vector_chunks`

### Migration: `0059_wealth_vector_chunks.py`

```python
# ATENÇÃO: CREATE INDEX usa autocommit (fora de transaction block)
# Seguir padrão das migrations de hypertable (usar connection.execution_options)

def upgrade() -> None:
    op.create_table(
        "wealth_vector_chunks",
        sa.Column("id", sa.Text(), primary_key=True),
        # Escopo — nullable para dados globais (SEC, ESMA)
        sa.Column("organization_id", postgresql.UUID(), nullable=True, index=True),
        # Entidade de referência
        sa.Column("entity_id", sa.Text(), nullable=True, index=True),
        sa.Column("entity_type", sa.Text(), nullable=False),
        # "firm" | "fund" | "macro" | "dd_chapter"
        # "firm"  = RIA / Management Company (ADV brochure, ESMA manager)
        # "fund"  = instrumento fundo (ESMA fund, DD chapter)
        # NÃO usar "manager" — manager = PM individual (ver fund-centric-pivot-audit.md)
        # Fonte e seção
        sa.Column("source_type", sa.Text(), nullable=False),
        # "brochure" | "esma_fund" | "esma_manager" | "dd_chapter" | "macro_review"
        sa.Column("section", sa.Text(), nullable=True),
        # seção dentro da fonte (ex: "methods_of_analysis")
        # Conteúdo
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=True, server_default="en"),
        # Metadados de rastreabilidade
        sa.Column("source_row_id", sa.Text(), nullable=True),
        # PK da row fonte (crd_number, isin, chapter_id, etc.)
        sa.Column("firm_crd", sa.Text(), nullable=True, index=True),
        # CRD da firma gestora — preenchido para brochures e esma_manager chunks
        # Permite resolver instrument → sec_crd → chunks da firma
        sa.Column("filing_date", sa.Date(), nullable=True),
        # Embedding
        sa.Column("embedding", Vector(3072), nullable=True),
        sa.Column("embedding_model", sa.Text(), nullable=True),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    # Índice HNSW para busca ANN — fora de transaction
    with op.get_bind().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(sa.text("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS
            wealth_vector_chunks_embedding_idx
            ON wealth_vector_chunks
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """))
    # Índices auxiliares
    op.create_index("ix_wvc_entity", "wealth_vector_chunks",
                    ["entity_type", "entity_id"])
    op.create_index("ix_wvc_source", "wealth_vector_chunks",
                    ["source_type", "section"])
    op.create_index("ix_wvc_org_entity", "wealth_vector_chunks",
                    ["organization_id", "entity_type"])
    op.create_index("ix_wvc_firm_crd", "wealth_vector_chunks", ["firm_crd"])
```

**Sem RLS na tabela** — dados globais (NULL org_id) exigem que a política
seja aplicada na query, não via policy de tabela. Todas as queries do search
service usam WHERE explícito.


---

## 2. SQLAlchemy Model

**Arquivo:** `backend/app/domains/wealth/models/wealth_vector_chunk.py`

```python
from __future__ import annotations
import datetime as dt
from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Date, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db.base import Base

class WealthVectorChunk(Base):
    __tablename__ = "wealth_vector_chunks"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    organization_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), nullable=True, index=True
    )  # NULL = dado global (SEC/ESMA)
    entity_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    # "firm" | "fund" | "macro" | "dd_chapter"
    # NUNCA "manager" — manager = PM individual no domínio do sistema
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(Text, nullable=True, default="en")
    source_row_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    firm_crd: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    # CRD da firma gestora — preenchido para entity_type="firm"
    # Permite resolver: instrument.attributes["sec_crd"] → firm_crd → chunks
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

**Sem `OrganizationScopedMixin`** — mixin força NOT NULL em organization_id,
incompatível com dados globais.

---

## 3. Worker: `wealth_embedding_worker.py`

**Arquivo:** `backend/app/domains/wealth/workers/wealth_embedding_worker.py`
**Lock ID:** `900_041`
**Frequência:** Diário (cron) + on-demand após brochure_extract

### 3.1 Fontes e estratégia de embedding por tipo

#### Fonte A — `sec_manager_brochure_text` (global, sem org_id)

Seções com alto valor semântico para busca de contexto da firma:
```python
BROCHURE_EMBED_SECTIONS = {
    "investment_philosophy", "methods_of_analysis", "advisory_business",
    "risk_management", "performance_fees", "full_brochure"
}
# Seções excluídas (operacional, baixo valor semântico):
# brokerage_practices, custody, code_of_ethics, disciplinary,
# client_types, fees_compensation
```

**ID formula:** `brochure_{crd_number}_{section}`
**entity_type:** `"firm"` ← firma RIA, não "manager" (ver fund-centric-pivot-audit.md)
**entity_id:** `crd_number`
**firm_crd:** `crd_number` ← duplicado para facilitar a resolução fund→firma
**Texto embeddado:** `f"[{section_label}] {content}"` — prefixo de seção

#### Fonte B — `esma_funds` (global, sem org_id)

**ID formula:** `esma_fund_{isin}`
**entity_type:** `"fund"` ← objeto de análise direto
**entity_id:** `isin`
**firm_crd:** `None` (ESMA não tem CRD; esma_manager_id fica em source_row_id)
**Texto embeddado:**
```python
f"{fund_name} | {fund_type} | {domicile}"
# Exemplo: "Amundi Funds - Global Aggregate Bond | UCITS | LU"
```

#### Fonte C — `esma_managers` (global, sem org_id)

**ID formula:** `esma_manager_{esma_id}`
**entity_type:** `"firm"` ← Management Company (firma, não PM individual)
**entity_id:** `esma_id`
**firm_crd:** `sec_crd_number` se preenchido em `esma_managers`, else `None`
**Texto embeddado:** `f"{company_name} | {country} | {authorization_status}"`

#### Fonte D — `dd_chapters` (org-scoped)

**ID formula:** `dd_chapter_{chapter_id}`
**entity_type:** `"fund"` ← o instrumento analisado é o fundo
**entity_id:** `str(instrument_id)` — via dd_reports FK
**firm_crd:** `None` (DD chapter é análise do fundo, não da firma)
**Texto embeddado:** `content_md`

#### Fonte E — `macro_reviews` (org-scoped)

**ID formula:** `macro_review_{review_id}_{section}`
**entity_type:** `"macro"`
**entity_id:** `str(review_id)`
**firm_crd:** `None`
**Texto embeddado:** `decision_rationale` + narrativas do `report_json`


### 3.2 Estrutura do worker

```python
WEALTH_EMBEDDING_LOCK_ID = 900_041
EMBED_BATCH_SIZE = 100        # chunks por batch OpenAI
UPSERT_BATCH_SIZE = 200       # rows por batch DB

async def run_wealth_embedding() -> dict:
    """Embed todas as fontes Wealth pendentes → wealth_vector_chunks.

    Idempotente: processa apenas rows sem embedding ou com source
    atualizado após o último embedded_at.
    Advisory lock global — escopo: sem org_id (dados globais e multi-tenant).
    """
    async with async_session() as db:
        locked = await _acquire_lock(db, WEALTH_EMBEDDING_LOCK_ID)
        if not locked:
            return {"status": "skipped", "reason": "lock_held"}
        try:
            stats = {}
            stats["brochure"] = await _embed_brochure_sections(db)
            stats["esma_funds"] = await _embed_esma_funds(db)
            stats["esma_managers"] = await _embed_esma_managers(db)
            stats["dd_chapters"] = await _embed_dd_chapters(db)
            stats["macro_reviews"] = await _embed_macro_reviews(db)
            return {"status": "completed", **stats}
        finally:
            await _release_lock(db, WEALTH_EMBEDDING_LOCK_ID)
```

### 3.3 Padrão de embedding incremental

Cada `_embed_*` segue o mesmo padrão — processar apenas pending:

```python
async def _embed_brochure_sections(db: AsyncSession) -> dict:
    # 1. Buscar rows sem embedding ou com filing_date > embedded_at
    pending = await db.execute(text("""
        SELECT b.crd_number, b.section, b.content, b.filing_date
        FROM sec_manager_brochure_text b
        LEFT JOIN wealth_vector_chunks w
          ON w.id = 'brochure_' || b.crd_number || '_' || b.section
        WHERE b.section = ANY(:sections)
          AND (w.id IS NULL OR b.filing_date > w.embedded_at::date)
        ORDER BY b.crd_number
    """), {"sections": list(BROCHURE_EMBED_SECTIONS)})

    rows = pending.fetchall()
    if not rows:
        return {"embedded": 0, "skipped": 0}

    # 2. Preparar textos com prefixo de seção
    SECTION_LABELS = {
        "investment_philosophy": "Investment Philosophy",
        "methods_of_analysis": "Methods of Analysis",
        "advisory_business": "Advisory Business",
        "risk_management": "Risk Management",
        "performance_fees": "Performance Fees",
        "full_brochure": "ADV Part 2A Brochure",
    }
    texts = [
        f"[{SECTION_LABELS.get(r.section, r.section)}] {r.content[:4000]}"
        for r in rows
    ]

    # 3. Embed em batches
    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    # 4. Upsert em wealth_vector_chunks
    upsert_rows = [
        {
            "id": f"brochure_{r.crd_number}_{r.section}",
            "organization_id": None,          # dado global
            "entity_id": r.crd_number,
            "entity_type": "firm",    # firma RIA — nunca "manager"
            "source_type": "brochure",
            "section": r.section,
            "content": texts[i],
            "language": "en",
            "source_row_id": r.crd_number,
            "firm_crd": r.crd_number,  # índice para resolução fund→firma
            "filing_date": r.filing_date,
            "embedding": batch.vectors[i],
            "embedding_model": batch.model,
            "embedded_at": datetime.utcnow(),
        }
        for i, r in enumerate(rows)
    ]
    await _batch_upsert(db, upsert_rows)
    return {"embedded": len(rows)}
```

### 3.4 Upsert com conflict resolution

```python
async def _batch_upsert(db: AsyncSession, rows: list[dict]) -> None:
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.domains.wealth.models.wealth_vector_chunk import WealthVectorChunk

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


---

## 4. Search Service Extension

**Arquivo:** `backend/ai_engine/extraction/pgvector_search_service.py`
**Adição:** novas funções de busca em `wealth_vector_chunks`

### Princípio: API fund-centric

O agente AI nunca busca "por firma". Ele busca "contexto de um fundo".
A resolução `instrument_id → sec_crd → chunks da firma` é interna ao
search service — o caller sempre passa `instrument_id` ou `isin`.

### 4.1 Busca fund-centric de contexto da firma (principal)

```python
def search_fund_firm_context_sync(
    *,
    query_vector: list[float],
    sec_crd: str | None = None,         # instrument.attributes["sec_crd"]
    esma_manager_id: str | None = None, # instrument.attributes["esma_manager_id"]
    section_filter: list[str] | None = None,
    top: int = 20,
) -> list[dict[str, Any]]:
    """Busca semântica de contexto da firma gestora de um fundo específico.

    Fund-centric: o caller resolve instrument_id → sec_crd antes de chamar.
    Aceita sec_crd (US funds) ou esma_manager_id (UCITS funds).
    Retorna chunks do brochure ADV ou do ESMA manager da firma.

    Exemplo de uso no agente:
        crd = instrument.attributes.get("sec_crd")
        chunks = search_fund_firm_context_sync(
            query_vector=embed("investment philosophy"),
            sec_crd=crd,
            section_filter=["investment_philosophy", "methods_of_analysis"],
        )
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

### 4.2 Busca de fundos ESMA (fund-centric — por ISIN ou semântica)

```python
def search_esma_funds_sync(
    *,
    query_vector: list[float],
    domicile_filter: str | None = None,
    top: int = 20,
) -> list[dict[str, Any]]:
    """Busca semântica de fundos UCITS por nome/tipo/domicílio.

    Retorna fundos (entity_type="fund") — objeto de análise direto.
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

### 4.3 Busca org-scoped por fundo (DD chapters, macro reviews)

```python
def search_fund_analysis_sync(
    *,
    organization_id: str,
    query_vector: list[float],
    instrument_id: str | None = None,  # filtrar por fundo específico
    source_type: str | None = None,    # "dd_chapter" | "macro_review"
    top: int = 20,
) -> list[dict[str, Any]]:
    """Busca semântica em análises org-scoped de fundos.

    Fund-centric: quando instrument_id fornecido, retorna apenas chunks
    do fundo específico (entity_id = instrument_id para dd_chapter).
    """
    params: dict[str, Any] = {
        "embedding": str(query_vector),
        "org_id": str(organization_id),
        "top": top,
    }
    clauses = []
    if source_type:
        params["source_type"] = source_type
        clauses.append("AND source_type = :source_type")
    if instrument_id:
        params["instrument_id"] = str(instrument_id)
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

## 5. Integração com Copilot RAG (global_agent)

O agente AI opera exclusivamente com identidades de fundo. A resolução para
contexto de firma é interna ao search service.

**Lógica de roteamento fund-centric:**

```python
# No global_agent — o agente recebe fund_id (instrument_id ou ISIN)

# 1. Contexto da firma gestora (filosofia, estratégia, risco)
#    → Resolver: instrument.attributes.get("sec_crd")
#    → search_fund_firm_context_sync(
#          query_vector=embed(query),
#          sec_crd=sec_crd,
#          section_filter=["investment_philosophy", "methods_of_analysis"]
#      )

# 2. Fundos europeus similares (busca por nome/estratégia)
#    → search_esma_funds_sync(query_vector=embed(query))

# 3. Análise qualitativa do fundo (DD report chapters)
#    → search_fund_analysis_sync(
#          organization_id=org_id,
#          query_vector=embed(query),
#          instrument_id=fund_id,
#          source_type="dd_chapter"
#      )

# 4. Contexto macro atual
#    → search_fund_analysis_sync(
#          organization_id=org_id,
#          query_vector=embed(query),
#          source_type="macro_review"
#      )
```

**Resolução de identidade no agente:**

```python
# O agente recebe instrument_id, precisa resolver para sec_crd
async def get_firm_context_ids(db: AsyncSession, instrument_id: str) -> dict:
    result = await db.execute(
        select(Instrument.attributes)
        .where(Instrument.id == instrument_id)
    )
    attrs = result.scalar_one_or_none() or {}
    return {
        "sec_crd": attrs.get("sec_crd"),           # US registered funds
        "esma_manager_id": attrs.get("esma_manager_id"),  # UCITS funds
    }
# O agente nunca assume que conhece a firma — sempre resolve via atributos do instrumento
```

---

## 6. Registro no CLI e Railway Cron

**Em `app/workers/cli.py`:** adicionar `"wealth_embedding"` ao dispatcher.

**Em `railway.toml`:** adicionar cron diário:

```toml
[[crons]]
name = "wealth-embedding"
schedule = "0 3 * * *"     # 3h UTC — após brochure_extract (2h UTC)
command = "python -m app.workers.cli wealth_embedding"
```

**Dependência de ordem:**
```
brochure_download (weekly) → brochure_extract (on-demand) → wealth_embedding (daily)
sec_adv_ingestion (monthly) → wealth_embedding (daily, incremental)
esma_ingestion (daily) → wealth_embedding (daily)
```

---

## 7. Estimativa de volume e custo

### Rows a embeddar (inicial)

| Fonte | Rows | Chunks | Tokens estimados |
|-------|------|--------|-----------------|
| Brochures (6 seções × ~3k CRDs) | ~17,837 filtrados → ~7,000 | 7,000 | ~10M |
| ESMA funds | 10,436 | 10,436 | ~500k |
| ESMA managers | 658 | 658 | ~30k |
| DD chapters (atual) | 96 | 96 | ~200k |
| Macro reviews | 4 | ~20 | ~40k |
| **Total inicial** | | **~18,210** | **~11M** |

### Custo OpenAI (text-embedding-3-large)

- $0.13 / 1M tokens
- ~11M tokens → **~$1.43 inicial**
- Incremental diário: centavos (apenas rows novos/atualizados)

---

## 8. Definition of Done

- [ ] Migration `0059_wealth_vector_chunks.py` criada e aplicada
- [ ] Model `WealthVectorChunk` em `app/domains/wealth/models/`
- [ ] Worker `wealth_embedding_worker.py` com 5 fontes implementadas
- [ ] Lock ID `900_041` registrado em `worker_registry.py`
- [ ] 3 funções de busca fund-centric adicionadas ao `pgvector_search_service.py`:
      `search_fund_firm_context_sync`, `search_esma_funds_sync`, `search_fund_analysis_sync`
- [ ] `"wealth_embedding"` registrado no `cli.py`
- [ ] Cron `0 3 * * *` em `railway.toml`
- [ ] Testes: `test_wealth_embedding_worker.py` (idempotência, incremental, fallback)
- [ ] `make check` passa (31/31 contracts — import-linter)
- [ ] Seed inicial executado: ~18k chunks com embeddings

## Failure Modes e Mitigações

| Cenário | Mitigação |
|---------|-----------|
| OpenAI rate limit durante seed inicial | Batch size 100, retry com backoff em `async_generate_embeddings` |
| Seção de brochure > 8192 tokens | Truncar a 4000 chars antes do embed (conteúdo inicial do texto) |
| `organization_id` NULL causa erro de cast | Usar `CAST(:org_id AS uuid)` só nas queries org-scoped |
| DD chapter sem instrument_id (FK inválida) | Skip silencioso com log warning |
| ESMA fund sem fund_name | Skip — sem conteúdo para embeddar |
| Worker falha no meio do seed | Incremental por design — reroda só pending |
