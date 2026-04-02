# Prompt K — Generated Reports UI + DD Report Storage Fix

## Contexto

Dois objetivos neste sprint:

1. **Frontend:** Adicionar seção "Generated Reports" na página de model-portfolio,
   listando fact sheets, monthly reports e long-form DD reports históricos
   com download permanente via os endpoints criados no Prompt J.

2. **Backend:** Corrigir o storage dos DD Reports.
   Problema atual: `GET /fact-sheets/dd-reports/{report_id}/download` regenera
   o PDF a cada request (Playwright + LLM render). Não existe storage_path no
   modelo. O `gold_dd_report_path()` existe no storage_routing.py mas nunca é
   usado. Fix: gerar PDF na aprovação, persistir no R2, servir do cache.

---

## Arquivos a ler OBRIGATORIAMENTE antes de implementar

```
backend/app/domains/wealth/routes/fact_sheets.py          — download_dd_report_pdf (linha 238+)
backend/app/domains/wealth/routes/dd_reports.py           — approve_dd_report (linha 375+)
backend/app/domains/wealth/models/dd_report.py            — campos do DDReport (sem storage_path)
backend/ai_engine/pipeline/storage_routing.py             — gold_dd_report_path() já existe
backend/app/core/db/migrations/versions/0076_wealth_generated_reports.py — migration recente
frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.server.ts — loader atual
frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte    — UI atual
frontends/wealth/src/lib/types/model-portfolio.ts         — tipos existentes
```

---

## PARTE 1 — Backend: DD Report PDF Storage Fix

### 1.1 Adicionar `storage_path` e `pdf_language` ao DDReport ORM

**Arquivo:** `backend/app/domains/wealth/models/dd_report.py`

Adicionar dois campos ao modelo `DDReport` após `rejection_reason`:

```python
storage_path: Mapped[str | None] = mapped_column(String(800), nullable=True)
pdf_language: Mapped[str | None] = mapped_column(String(5), nullable=True)
```

### 1.2 Migration 0077

**Arquivo novo:** `backend/app/core/db/migrations/versions/0077_dd_report_storage_path.py`

Verificar `down_revision` correto lendo o topo de `0076_wealth_generated_reports.py`.

```python
"""Add storage_path and pdf_language to dd_reports

Revision ID: 0077_dd_report_storage_path
Revises: 0076_wealth_generated_reports
Create Date: 2026-04-01 00:00:00.000000
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "0077_dd_report_storage_path"
down_revision: str | None = "0076_wealth_generated_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("dd_reports", sa.Column("storage_path", sa.String(800), nullable=True))
    op.add_column("dd_reports", sa.Column("pdf_language", sa.String(5), nullable=True))


def downgrade() -> None:
    op.drop_column("dd_reports", "storage_path")
    op.drop_column("dd_reports", "pdf_language")
```

### 1.3 Gerar e persistir PDF na aprovação

**Arquivo:** `backend/app/domains/wealth/routes/dd_reports.py`

Em `approve_dd_report`, após o `await write_audit_event(...)` e antes do
`await db.commit()`, adicionar geração e armazenamento do PDF:

```python
# Generate and persist PDF on approval (cache for fast future downloads)
try:
    from sqlalchemy.orm import selectinload as _sil
    report_with_chapters = (await db.execute(
        select(DDReport)
        .options(_sil(DDReport.chapters))
        .where(DDReport.id == report.id)
    )).scalar_one()

    chapters_data = [
        {
            "chapter_tag": ch.chapter_tag,
            "chapter_order": ch.chapter_order,
            "content_md": ch.content_md,
        }
        for ch in sorted(report_with_chapters.chapters, key=lambda c: c.chapter_order)
    ]

    # Prefer pt as default language; fund name from instrument
    pdf_language = "pt"
    from app.domains.wealth.models.fund import Fund
    fn_row = (await db.execute(
        select(Fund.name).where(Fund.fund_id == report.instrument_id)
    )).scalar_one_or_none()
    fund_name = fn_row or "Fund"
    confidence = float(report.confidence_score) if report.confidence_score else None

    from ai_engine.pdf.generate_dd_report_pdf import generate_dd_report_pdf_async
    pdf_bytes = await generate_dd_report_pdf_async(
        fund_name=fund_name,
        report_id=str(report.id),
        chapters=chapters_data,
        confidence_score=confidence,
        decision_anchor=report.decision_anchor,
        language=pdf_language,
    )

    if pdf_bytes:
        from ai_engine.pipeline.storage_routing import gold_dd_report_path
        from app.services.storage_client import get_storage_client
        import uuid as _uuid

        storage_key = gold_dd_report_path(
            org_id=_uuid.UUID(str(report.organization_id)),
            vertical="wealth",
            report_id=str(report.id),
            language=pdf_language,
        )
        storage = get_storage_client()
        await storage.write(storage_key, pdf_bytes, content_type="application/pdf")

        report.storage_path = storage_key
        report.pdf_language = pdf_language

        logger.info(
            "dd_report_pdf_stored_on_approval",
            report_id=str(report.id),
            storage_path=storage_key,
            size_bytes=len(pdf_bytes),
        )
except Exception:
    # Never-raises: approval succeeds even if PDF generation fails
    logger.warning("dd_report_pdf_generation_on_approval_failed",
                   report_id=str(report.id), exc_info=True)
```

### 1.4 Modificar `download_dd_report_pdf` para usar cache R2

**Arquivo:** `backend/app/domains/wealth/routes/fact_sheets.py`

No handler `download_dd_report_pdf`, ANTES da geração Playwright,
verificar se já existe PDF cacheado:

```python
# Check R2 cache first (set on approval)
if report.storage_path:
    try:
        from app.services.storage_client import get_storage_client
        storage = get_storage_client()
        cached_bytes = await storage.read(report.storage_path)
        if cached_bytes:
            safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", fund_name)
            filename = f"dd_report_{safe_name}_{language}.pdf"
            return Response(
                content=cached_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
    except Exception:
        logger.warning("dd_report_cache_miss", report_id=str(report_id), exc_info=True)
        # Fall through to on-demand generation
```

Inserir este bloco logo após a busca do `fund_name` e antes do bloco de geração Playwright.

### 1.5 DDReportSummary schema — expor storage_path

**Arquivo:** `backend/app/domains/wealth/schemas/dd_report.py`

Adicionar ao `DDReportSummary`:
```python
storage_path: str | None = None
pdf_language: str | None = None
```

---

## PARTE 2 — Frontend: Generated Reports UI

### 2.1 Tipos TypeScript

**Arquivo:** `frontends/wealth/src/lib/types/model-portfolio.ts`

Adicionar:

```typescript
export interface GeneratedReport {
  id: string;
  report_type: 'monthly_report' | 'long_form_dd' | 'fact_sheet';
  job_id: string;
  storage_path: string;
  display_filename: string;
  generated_at: string;
  size_bytes: number | null;
  status: 'completed' | 'failed';
}
```

### 2.2 Estender o SSR loader

**Arquivo:** `frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.server.ts`

Adicionar ao `Promise.all` existente:

```typescript
api.get<GeneratedReport[]>(
  `/reporting/model-portfolios/${params.portfolioId}/monthly-report/history`
).catch(() => [] as GeneratedReport[]),
api.get<GeneratedReport[]>(
  `/reporting/model-portfolios/${params.portfolioId}/long-form-report/history`
).catch(() => [] as GeneratedReport[]),
```

Retornar `monthlyReports` e `longFormReports` no objeto de return.

Adicionar import do tipo no topo:
```typescript
import type { GeneratedReport } from '$lib/types/model-portfolio';
```

### 2.3 Criar `GeneratedReportsPanel.svelte`

**Arquivo novo:** `frontends/wealth/src/lib/components/model-portfolio/GeneratedReportsPanel.svelte`

O painel lista os três tipos de relatório gerados para o portfólio em abas ou
seções colapsáveis: Fact Sheets, Monthly Reports, Long-Form DD Reports.

Props:
```typescript
interface Props {
  portfolioId: string;
  factSheets: FactSheet[];       // já existe no loader
  monthlyReports: GeneratedReport[];
  longFormReports: GeneratedReport[];
}
```

Layout de cada seção (usar o padrão SectionCard existente):

**Cabeçalho:** título do tipo + contagem de itens + botão de trigger (ex: "Generate Monthly Report")

**Tabela de itens:**
- `generated_at` formatado (data + hora curta)
- `display_filename` truncado
- `size_bytes` formatado (ex: "2.3 MB") usando formatadores do `@investintell/ui`
- Botão "Download" — faz fetch do endpoint de download permanente e aciona download do browser

**Botão de download — padrão correto:**
```typescript
async function downloadReport(report: GeneratedReport) {
  const api = createClientApiClient(getToken);
  const type = report.report_type;
  const endpoint =
    type === 'monthly_report'
      ? `/reporting/model-portfolios/${portfolioId}/monthly-report/download/${report.id}`
      : `/reporting/model-portfolios/${portfolioId}/long-form-report/download/${report.id}`;

  const blob = await api.getBlob(endpoint);  // usa api.getBlob() existente no @investintell/ui
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = report.display_filename;
  a.click();
  URL.revokeObjectURL(url);
}
```

Para fact sheets, o download já existe via `GET /fact-sheets/{path}/download`.
Reutilizar o padrão existente na página.

**Empty state por seção:** "No {type} reports generated yet."
Com botão de trigger se o usuário tiver role IC.

**Triggers:**
- Monthly Report → `POST /reporting/model-portfolios/{id}/monthly-report`
  (já conectado no frontend via `MonthlyReportPanel.svelte` — verificar se existe
  e reutilizar ou chamar diretamente)
- Long-Form DD → `POST /reporting/model-portfolios/{id}/long-form-report`
  (já conectado em `LongFormReportPanel.svelte` — verificar se existe)
- Fact Sheet → `POST /fact-sheets/model-portfolios/{id}` (já conectado)

Se os panels de trigger já existirem como componentes, **não duplicar** — apenas
adicionar o histórico de relatórios abaixo de cada trigger existente.

### 2.4 Integrar na página de model-portfolio

**Arquivo:** `frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte`

Importar e renderizar `GeneratedReportsPanel` passando os dados do loader.

Posição sugerida: após a seção de Fact Sheets existente, antes das IC Views.

```svelte
<GeneratedReportsPanel
  portfolioId={data.portfolioId}
  factSheets={data.factSheets}
  monthlyReports={data.monthlyReports}
  longFormReports={data.longFormReports}
/>
```

Se a página já tem seções separadas para Fact Sheets, Monthly Reports e Long-Form
via panels de trigger, adicionar o histórico inline abaixo de cada trigger existente
em vez de criar um painel separado.

---

## Regras críticas

- **Never-raises no bloco de geração PDF em `approve_dd_report`** — a aprovação
  deve suceder mesmo se o PDF falhar. Usar try/except amplo com `logger.warning`.
- **`gold_dd_report_path()` é o único path permitido** para DD Report PDFs —
  sem f-strings, sem caminhos ad-hoc.
- **`api.getBlob()`** para downloads — não usar fetch() bruto para binários.
- **Formatadores do `@investintell/ui`** — nunca `.toFixed()` nem `.toLocaleString()`.
- **Lazy load para historical reports** — se a lista for longa, limitar a 12 itens
  no loader e adicionar link "Ver todos" se `length === 12`.
- **Não alterar** o fluxo de download on-demand do `download_dd_report_pdf` para
  relatórios antigos sem `storage_path` — o fallback de geração é necessário para
  compatibilidade com relatórios existentes.

---

## Definition of Done

- [ ] `storage_path` e `pdf_language` adicionados ao DDReport ORM
- [ ] Migration 0077 criada com down_revision correto
- [ ] `approve_dd_report` gera e persiste PDF no R2 via `gold_dd_report_path()`
- [ ] `download_dd_report_pdf` usa cache R2 quando `storage_path` existe
- [ ] `DDReportSummary` schema expõe `storage_path` e `pdf_language`
- [ ] `GeneratedReport` tipo TypeScript criado
- [ ] Loader de `[portfolioId]/+page.server.ts` busca monthly e long-form history
- [ ] `GeneratedReportsPanel.svelte` criado com listagem + download dos 3 tipos
- [ ] Download via `api.getBlob()` funcionando para monthly e long-form
- [ ] `pnpm run check` 0 erros no wealth frontend
- [ ] `make check` verde no backend (lint + typecheck + 3179+ testes)
- [ ] `alembic upgrade head` aplica 0077 sem erros
