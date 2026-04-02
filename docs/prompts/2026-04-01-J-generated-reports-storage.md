# Prompt J — Generated Reports: Storage Routing + Persistent Registry

## Contexto

Dois problemas identificados no audit de R2:

1. `monthly_report.py` e `long_form_reports.py` constroem paths R2 via f-string,
   violando a regra arquitetural "nunca usar f-strings para storage paths".
   `storage_routing.py` não tem funções para esses dois tipos de relatório.

2. A referência ao PDF gerado fica apenas no Redis com TTL de 24h
   (`job:{id}:pdf_key`). Após 24h o download retorna 404, mesmo com o PDF
   ainda no R2. Não existe histórico persistente de relatórios gerados.

**Arquivos a ler antes de qualquer implementação:**
```
backend/ai_engine/pipeline/storage_routing.py              — funções existentes, padrão a seguir
backend/app/domains/wealth/routes/monthly_report.py        — f-string em _run_monthly_generation (~linha 190)
backend/app/domains/wealth/routes/long_form_reports.py     — f-string em _run_generation (~linha 205)
backend/app/core/db/migrations/versions/0020_wealth_documents.py — padrão de migration
backend/app/domains/wealth/models/model_portfolio.py       — modelo de referência para FK
```

---

## Parte 1 — Adicionar path functions ao storage_routing.py

**Arquivo:** `backend/ai_engine/pipeline/storage_routing.py`

Adicionar as duas funções após `gold_dd_report_path()`, seguindo
exatamente o padrão das funções existentes (docstring, validate, f-string).

```python
def gold_monthly_report_path(
    org_id: UUID,
    portfolio_id: str,
    job_id: str,
) -> str:
    """``gold/{org_id}/wealth/reports/monthly-{portfolio_id}/{job_id}.pdf``

    Stores generated monthly client report PDFs for model portfolios.
    job_id provides uniqueness across multiple generations for the same
    portfolio (e.g., mcr-{portfolio_id}-{hex}).
    """
    _validate_segment(portfolio_id, "portfolio_id")
    _validate_segment(job_id, "job_id")
    return f"gold/{org_id}/wealth/reports/monthly-{portfolio_id}/{job_id}.pdf"


def gold_long_form_report_path(
    org_id: UUID,
    portfolio_id: str,
    job_id: str,
) -> str:
    """``gold/{org_id}/wealth/reports/long-form-dd-{portfolio_id}/{job_id}.pdf``

    Stores generated long-form due diligence report PDFs for model portfolios.
    job_id provides uniqueness across multiple generations.
    """
    _validate_segment(portfolio_id, "portfolio_id")
    _validate_segment(job_id, "job_id")
    return f"gold/{org_id}/wealth/reports/long-form-dd-{portfolio_id}/{job_id}.pdf"
```

---

## Parte 2 — Substituir f-strings pelos path builders

### 2.1 Em `monthly_report.py`

Localizar em `_run_monthly_generation` o bloco:
```python
storage_key = (
    f"gold/{organization_id}/wealth/reports/"
    f"monthly-{portfolio_id}-{job_id}.pdf"
)
```

Substituir por:
```python
from ai_engine.pipeline.storage_routing import gold_monthly_report_path

storage_key = gold_monthly_report_path(
    org_id=uuid.UUID(organization_id),
    portfolio_id=portfolio_id,
    job_id=job_id,
)
```

O import deve ser local (dentro da função), seguindo o padrão já usado
no mesmo arquivo para outros imports de vertical_engines.

### 2.2 Em `long_form_reports.py`

Localizar em `_run_generation` o bloco:
```python
pdf_storage_key = (
    f"gold/{organization_id}/wealth/reports/"
    f"long-form-dd-{portfolio_id}-{job_id}.pdf"
)
```

Substituir por:
```python
from ai_engine.pipeline.storage_routing import gold_long_form_report_path

pdf_storage_key = gold_long_form_report_path(
    org_id=uuid.UUID(organization_id),
    portfolio_id=portfolio_id,
    job_id=job_id,
)
```

---

## Parte 3 — Tabela `wealth_generated_reports` (migration 0076)

### 3.1 Criar o modelo ORM

**Arquivo novo:** `backend/app/domains/wealth/models/generated_report.py`

```python
"""WealthGeneratedReport — persistent registry of system-generated PDFs."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, IdMixin, OrganizationScopedMixin


class WealthGeneratedReport(Base, IdMixin, OrganizationScopedMixin):
    """Persistent record of every generated PDF report stored in R2.

    Decoupled from Redis TTL — provides permanent download capability
    and history browsing via storage_path.
    """
    __tablename__ = "wealth_generated_reports"

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True,
    )
    report_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
        # Values: "monthly_report" | "long_form_dd" | "fact_sheet"
    )
    job_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    storage_path: Mapped[str] = mapped_column(String(800), nullable=False)
    # Human-readable filename for Content-Disposition header
    display_filename: Mapped[str] = mapped_column(String(300), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False,
    )
    generated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="completed",
        # Values: "completed" | "failed"
    )
```

### 3.2 Criar migration 0076

**Arquivo novo:** `backend/app/core/db/migrations/versions/0076_wealth_generated_reports.py`

```python
"""wealth_generated_reports — persistent PDF report registry

Revision ID: 0076_wealth_generated_reports
Revises: 0075_add_peer_percentile_columns
Create Date: 2026-04-01 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0076_wealth_generated_reports"
down_revision: str | None = "0075_add_peer_percentile_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wealth_generated_reports",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("portfolio_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("report_type", sa.String(50), nullable=False, index=True),
        sa.Column("job_id", sa.String(128), nullable=False, unique=True),
        sa.Column("storage_path", sa.String(800), nullable=False),
        sa.Column("display_filename", sa.String(300), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("generated_by", sa.String(128), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
    )
    op.create_index(
        "ix_wealth_gen_reports_org_portfolio",
        "wealth_generated_reports",
        ["organization_id", "portfolio_id"],
    )
    op.create_index(
        "ix_wealth_gen_reports_org_type",
        "wealth_generated_reports",
        ["organization_id", "report_type", "generated_at"],
    )


def downgrade() -> None:
    op.drop_table("wealth_generated_reports")
```

**ATENÇÃO:** Verificar qual é o `down_revision` correto lendo o topo de
`0075_add_peer_percentile_columns.py` antes de escrever a migration.
O `down_revision` deve ser o `revision` do arquivo 0075, não o nome do arquivo.

---

## Parte 4 — Persistir registro após geração bem-sucedida

### 4.1 Em `monthly_report.py` — `_run_monthly_generation`

Após o bloco de escrita no Redis (`await r.set(f"job:{job_id}:pdf_key", ...)`),
adicionar persistência no banco:

```python
# Persist permanent record (survives Redis TTL)
try:
    async with async_session_factory() as record_db:
        await set_rls_context(record_db, uuid.UUID(organization_id))
        from app.domains.wealth.models.generated_report import WealthGeneratedReport

        report_record = WealthGeneratedReport(
            organization_id=uuid.UUID(organization_id),
            portfolio_id=uuid.UUID(portfolio_id),
            report_type="monthly_report",
            job_id=job_id,
            storage_path=storage_key,
            display_filename=f"monthly-report-{portfolio_id}.pdf",
            size_bytes=len(pdf_bytes),
            status="completed",
        )
        record_db.add(report_record)
        await record_db.commit()
except Exception:
    logger.warning("monthly_report_record_failed", exc_info=True)
    # Never-raises: Redis key still works for 24h
```

### 4.2 Em `long_form_reports.py` — `_run_generation`

Após o bloco de escrita no Redis, adicionar:

```python
# Persist permanent record
try:
    async with async_session_factory() as record_db:
        await set_rls_context(record_db, uuid.UUID(organization_id))
        from app.domains.wealth.models.generated_report import WealthGeneratedReport

        report_record = WealthGeneratedReport(
            organization_id=uuid.UUID(organization_id),
            portfolio_id=uuid.UUID(portfolio_id),
            report_type="long_form_dd",
            job_id=job_id,
            storage_path=pdf_storage_key,
            display_filename=f"long-form-dd-{portfolio_id}.pdf",
            size_bytes=len(pdf_bytes),
            status="completed",
        )
        record_db.add(report_record)
        await record_db.commit()
except Exception:
    logger.warning("long_form_report_record_failed", exc_info=True)
```

---

## Parte 5 — Endpoint de download permanente

Adicionar endpoint que lê o storage_path do banco em vez do Redis,
eliminando a dependência do TTL.

### 5.1 Em `monthly_report.py` — adicionar nova rota

```python
@router.get(
    "/model-portfolios/{portfolio_id}/monthly-report/history",
    summary="List all generated monthly reports for a portfolio",
)
async def list_monthly_reports(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_org_id),
) -> list[dict]:
    from sqlalchemy import select
    from app.domains.wealth.models.generated_report import WealthGeneratedReport

    stmt = (
        select(WealthGeneratedReport)
        .where(
            WealthGeneratedReport.portfolio_id == portfolio_id,
            WealthGeneratedReport.report_type == "monthly_report",
            WealthGeneratedReport.status == "completed",
        )
        .order_by(WealthGeneratedReport.generated_at.desc())
        .limit(24)  # max 2 anos de histórico mensal
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return [
        {
            "id": str(r.id),
            "job_id": r.job_id,
            "display_filename": r.display_filename,
            "generated_at": r.generated_at.isoformat(),
            "size_bytes": r.size_bytes,
        }
        for r in rows
    ]


@router.get(
    "/model-portfolios/{portfolio_id}/monthly-report/download/{report_id}",
    summary="Download a historical monthly report PDF by record ID",
)
async def download_monthly_report_by_id(
    portfolio_id: uuid.UUID,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_org_id),
) -> Response:
    from sqlalchemy import select
    from app.domains.wealth.models.generated_report import WealthGeneratedReport

    stmt = select(WealthGeneratedReport).where(
        WealthGeneratedReport.id == report_id,
        WealthGeneratedReport.portfolio_id == portfolio_id,
        WealthGeneratedReport.report_type == "monthly_report",
    )
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail="Report not found")

    from app.services.storage_client import create_storage_client
    storage = create_storage_client()
    pdf_bytes = await storage.read(record.storage_path)

    if pdf_bytes is None:
        raise HTTPException(status_code=404, detail="PDF file not found in storage")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{record.display_filename}"',
        },
    )
```

Adicionar os mesmos dois endpoints em `long_form_reports.py`,
com `report_type == "long_form_dd"` e prefixo de rota análogo.

---

## Parte 6 — Registrar fact sheets também (backfill de tipo)

O `fact_sheets.py` já usa `gold_fact_sheet_path()` corretamente.
Mas o registro persistente não existe para fact sheets.

Após verificar como `fact_sheets.py` gera e armazena o PDF
(ler o arquivo antes de implementar), adicionar o mesmo bloco de
persistência de `WealthGeneratedReport` com `report_type="fact_sheet"`.

---

## Verificação e gates

```bash
# Backend
cd backend
make check

# Verificar migration específica
alembic heads          # deve mostrar 0076 como único head
alembic upgrade head   # aplica 0076

# Verificar que os path builders existem no módulo
python -c "from ai_engine.pipeline.storage_routing import gold_monthly_report_path, gold_long_form_report_path; print('OK')"
```

---

## Definition of Done

- [ ] `gold_monthly_report_path()` adicionada a `storage_routing.py` com docstring e validate
- [ ] `gold_long_form_report_path()` adicionada a `storage_routing.py` com docstring e validate
- [ ] `monthly_report.py` usa `gold_monthly_report_path()` — sem f-string para storage key
- [ ] `long_form_reports.py` usa `gold_long_form_report_path()` — sem f-string para storage key
- [ ] `WealthGeneratedReport` ORM model criado
- [ ] Migration `0076_wealth_generated_reports` criada com down_revision correto
- [ ] `_run_monthly_generation` persiste `WealthGeneratedReport` após upload ao R2
- [ ] `_run_generation` (long-form) persiste `WealthGeneratedReport` após upload ao R2
- [ ] Endpoints `/history` e `/download/{report_id}` adicionados para monthly e long-form
- [ ] `fact_sheets.py` também persiste `WealthGeneratedReport` com `report_type="fact_sheet"`
- [ ] `make check` verde — lint + typecheck + testes
- [ ] `alembic upgrade head` sem erros

## O que NÃO fazer

- Não alterar o fluxo Redis existente — manter `job:{id}:pdf_key` para download imediato
  (os dois mecanismos coexistem: Redis para download no momento, banco para histórico)
- Não criar frontend neste prompt — apenas backend e migration
- Não modificar `wealth_documents` — é uma tabela diferente com propósito diferente
  (documentos de usuário para AI pipeline, não relatórios gerados pelo sistema)
