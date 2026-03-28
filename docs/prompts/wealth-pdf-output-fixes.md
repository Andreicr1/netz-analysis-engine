# Wealth PDF Output — Três Correções

## Contexto

Três problemas distintos afetam os PDFs do vertical Wealth. Todos os PDFs
produzidos agora carregam o logo Necker (provedor do Netz Private Credit Fund)
no header — sem relação com o Wealth. O `ManagerSpotlight` busca dados de um
model deprecado. O `LongFormReportEngine` não tem renderer PDF.

Este prompt cobre os três em sequência. Leia cada arquivo listado antes de
editar qualquer coisa.

---

## Problema 1 — Logo Necker em todos os PDFs do Wealth (CRÍTICO)

### Diagnóstico

`ai_engine/pdf/pdf_base.py` — `netz_header_footer()` hardcoda `LOGO_NECKER`
no header de páginas 2+ de **todos** os relatórios. No Wealth, Necker não tem
relação nenhuma: é um provedor do Netz Private Credit Fund.

**Callers Wealth afetados:**
- `vertical_engines/wealth/fact_sheet/executive_renderer.py`
- `vertical_engines/wealth/fact_sheet/institutional_renderer.py`
- `vertical_engines/wealth/content_pdf.py` → FlashReport + ManagerSpotlight
  + InvestmentOutlook

**Callers Credit (devem continuar recebendo Necker):**
- `ai_engine/pdf/` — Deep Review, IC Memo etc. (não mexer)

### Arquivos a ler antes de editar

```
backend/ai_engine/pdf/pdf_base.py          ← função a modificar
backend/vertical_engines/wealth/fact_sheet/executive_renderer.py
backend/vertical_engines/wealth/fact_sheet/institutional_renderer.py
backend/vertical_engines/wealth/content_pdf.py
```

### Alteração em `pdf_base.py`

Adicionar parâmetro `right_logo_path` em `netz_header_footer()`.
**Backward-compatible** — default mantém o comportamento atual do Credit.

```python
# ANTES:
def netz_header_footer(
    canvas: Any,
    doc: Any,
    *,
    report_title: str = "Netz Report",
    confidentiality: str = "CONFIDENTIAL — INTERNAL USE ONLY",
) -> None:

# DEPOIS:
def netz_header_footer(
    canvas: Any,
    doc: Any,
    *,
    report_title: str = "Netz Report",
    confidentiality: str = "CONFIDENTIAL — INTERNAL USE ONLY",
    right_logo_path: str | None = LOGO_NECKER,   # ← novo parâmetro
) -> None:
```

Dentro da função, substituir a referência hardcoded à constante `LOGO_NECKER`
pelo parâmetro `right_logo_path`. Localizar o bloco `# 4. Necker logo —
right-aligned` e alterar a condição de guarda:

```python
# ANTES:
if os.path.isfile(LOGO_NECKER):
    try:
        ...
        canvas.drawImage(
            LOGO_NECKER,
            ...
        )
    except Exception:
        canvas.setFont(...)
        canvas.drawRightString(w - rm, title_y, "NECKER")

# DEPOIS:
if right_logo_path and os.path.isfile(right_logo_path):
    try:
        ...
        canvas.drawImage(
            right_logo_path,
            ...
        )
    except Exception:
        pass   # sem fallback de texto para logo ausente no Wealth
```

### Alterações nos 3 callers Wealth

Em cada caller, na closure `_on_page` que chama `netz_header_footer`, adicionar
`right_logo_path=None`:

**`executive_renderer.py`:**
```python
def _on_page(canvas: Any, doc_obj: Any) -> None:
    netz_header_footer(
        canvas, doc_obj,
        report_title=...,
        confidentiality=...,
        right_logo_path=None,   # ← adicionar
    )
```

**`institutional_renderer.py`:** mesma alteração na closure `_on_page`.

**`content_pdf.py`:** mesma alteração na closure `_on_page`.

**Callers Credit** (não tocar): nenhum deles passa `right_logo_path`, então
continuam usando o default `LOGO_NECKER` — comportamento preservado.

---

## Problema 2 — `ManagerSpotlight` usa model `Fund` deprecado

### Diagnóstico

`vertical_engines/wealth/manager_spotlight.py` — `_gather_fund_data()` importa
e consulta `app.domains.wealth.models.fund.Fund`, que mapeia para
`funds_universe` — tabela marcada como DEPRECATED no próprio docstring do
arquivo:

> *"This file is retained only for backward compatibility... It will be removed
> alongside migration 0012"*

O model correto é `Instrument` em `app.domains.wealth.models.instrument`,
tabela `instruments_universe`. Se `funds_universe` estiver vazia (ou já
removida), `_gather_fund_data` retorna sempre `{"instrument_id": ...,
"name": "Unknown Fund"}` silenciosamente, e o LLM gera um Spotlight sem
nenhum dado real do fundo.

### Arquivos a ler antes de editar

```
backend/vertical_engines/wealth/manager_spotlight.py
backend/app/domains/wealth/models/instrument.py   ← schema correto
backend/app/domains/wealth/models/fund.py         ← DEPRECATED, para referência
```

### Alteração em `manager_spotlight.py`

Substituir `_gather_fund_data()` inteiramente:

```python
# ANTES:
def _gather_fund_data(self, db: Session, instrument_id: str, organization_id: str) -> dict[str, Any]:
    from app.domains.wealth.models.fund import Fund

    fund = (
        db.query(Fund)
        .filter(Fund.fund_id == instrument_id, Fund.organization_id == organization_id)
        .first()
    )
    if not fund:
        return {"instrument_id": instrument_id, "name": "Unknown Fund"}

    return {
        "instrument_id": str(fund.fund_id),
        "name": fund.name,
        ...
    }

# DEPOIS:
def _gather_fund_data(self, db: Session, instrument_id: str, organization_id: str) -> dict[str, Any]:
    from app.domains.wealth.models.instrument import Instrument

    instrument = (
        db.query(Instrument)
        .filter(
            Instrument.instrument_id == instrument_id,
            Instrument.organization_id == organization_id,
        )
        .first()
    )
    if not instrument:
        return {"instrument_id": instrument_id, "name": "Unknown Fund"}

    attrs = instrument.attributes or {}
    return {
        "instrument_id": str(instrument.instrument_id),
        "name": instrument.name,
        "isin": instrument.isin,
        "ticker": instrument.ticker,
        "fund_type": attrs.get("fund_type") or instrument.asset_class,
        "geography": instrument.geography,
        "asset_class": instrument.asset_class,
        "manager_name": attrs.get("manager_name"),
        "currency": instrument.currency,
        "domicile": attrs.get("domicile"),
        "inception_date": str(attrs["inception_date"]) if attrs.get("inception_date") else None,
        "aum_usd": float(attrs["aum_usd"]) if attrs.get("aum_usd") else None,
        "sec_crd": attrs.get("sec_crd"),   # ← necessário para vector search futuro
    }
```

**Campos mapeados:**
- `fund_id` → `instrument_id`
- `fund_type` → `attrs.get("fund_type") or asset_class` (JSONB attributes)
- `manager_name` → `attrs.get("manager_name")` (JSONB)
- `domicile` → `attrs.get("domicile")` (JSONB)
- `inception_date` → `attrs.get("inception_date")` (JSONB)
- `aum_usd` → `attrs.get("aum_usd")` (JSONB)
- `name`, `isin`, `ticker`, `geography`, `asset_class`, `currency` → colunas diretas
- `sec_crd` → `attrs.get("sec_crd")` (JSONB) — necessário para `search_fund_firm_context_sync` na injeção de vector search subsequente

---

## Problema 3 — `LongFormReportEngine` não tem renderer PDF

### Diagnóstico

`long_form_report_engine.py` — `generate()` retorna `LongFormReportResult`
com 8 `ChapterResult`, cada um contendo um dict `content` com dados
estruturados (dicts, listas, floats). Não existe `render_pdf()`. A rota que
serve o relatório não tem como gerar um PDF para o cliente.

**Estrutura do `content` por capítulo:**
- Ch1 `macro_context`: `{as_of_date, regions, global_summary, risk_assessment}`
- Ch2 `strategic_allocation`: `{profile, blocks: [{block_id, display_name, target_weight, rationale}]}`
- Ch3 `portfolio_composition`: `{current_date, previous_date, total_funds, deltas: [{block_id, current_weight, previous_weight, delta}]}`
- Ch4 `performance_attribution`: `{available, total_portfolio_return, total_benchmark_return, total_excess_return, allocation_total, selection_total, interaction_total, sectors: [...]}`
- Ch5 `risk_decomposition`: `{available, portfolio_cvar_95, portfolio_var_95, n_observations, blocks: [...]}`
- Ch6 `fee_analysis`: `{available, weighted_fee_drag_pct, inefficient_count, instruments: [...]}`
- Ch7 `per_fund_highlights`: `{total_funds, newcomers, exits, top_movers: [...]}`
- Ch8 `forward_outlook`: `{available, published_at, content: {...}}`

### Arquivo a criar

```
backend/vertical_engines/wealth/long_form_report/pdf_renderer.py
```

### Arquivo a ler antes de criar

```
backend/ai_engine/pdf/pdf_base.py        ← build_netz_styles, create_netz_document,
                                            netz_header_footer, build_institutional_table,
                                            safe_text, ORANGE, NAVY
backend/vertical_engines/wealth/long_form_report/models.py  ← LongFormReportResult, ChapterResult
backend/vertical_engines/wealth/fact_sheet/i18n.py          ← LABELS, format_date, format_pct, Language
backend/vertical_engines/wealth/fact_sheet/executive_renderer.py  ← padrão de layout a seguir
```

### Interface pública do renderer

```python
def render_long_form_pdf(
    result: LongFormReportResult,
    *,
    portfolio_name: str,
    language: Language = "pt",
) -> BytesIO:
    """Render LongFormReportResult as branded Netz institutional PDF.

    Returns BytesIO seeked to 0.
    Never raises — returns empty PDF on failure.
    """
```

### Layout por capítulo

O renderer itera sobre `result.chapters` em ordem. Cada capítulo com
`status != "completed"` ou `content` vazio recebe um placeholder
`"[Chapter not available]"` — nunca causa falha.

**Cap 1 — Macro Context**: `global_summary` como parágrafo `body`. Tabela
de regiões se `regions` for lista de dicts com `region` + `composite_score`.
`risk_assessment` como parágrafo subsequente.

**Cap 2 — Strategic Allocation**: Tabela com colunas
`[Block, Target Weight %, Rationale]`. `target_weight` formatado como pct.

**Cap 3 — Portfolio Composition**: Tabela de deltas
`[Block, Current %, Previous %, Delta]`. Delta positivo em verde, negativo
em vermelho via `colors.green` / `colors.red` (não usar severity_color).

**Cap 4 — Performance Attribution**: Se `available=False`, parágrafo
explicativo. Se disponível: linha de resumo
`Portfolio: X% | Benchmark: Y% | Excess: Z%` + tabela
`[Sector, Allocation, Selection, Interaction, Total]`.

**Cap 5 — Risk Decomposition**: Se `available=False`, placeholder. Se
disponível: `Portfolio CVaR 95%: X%` + tabela
`[Block, CVaR 95%, VaR 95%]`.

**Cap 6 — Fee Analysis**: Se `available=False`, placeholder. Se disponível:
`Weighted fee drag: X%` + tabela
`[Fund, Total Fee %, Fee Drag %, Efficient]`.

**Cap 7 — Per-Fund Highlights**: Parágrafo com `total_funds`, `newcomers`,
`exits`. Tabela top movers `[Fund, Block, Weight %]`.

**Cap 8 — Forward Outlook**: Se `available=False`, placeholder. Se
disponível: renderizar `content` (dict do InvestmentOutlook) como parágrafos
estruturados. `published_at` como meta.

### Integração com `LongFormReportEngine`

Adicionar `render_pdf()` ao engine **após** criar o renderer:

```python
# Em long_form_report_engine.py — adicionar método público:
def render_pdf(
    self,
    result: LongFormReportResult,
    *,
    portfolio_name: str,
    language: str = "pt",
) -> BytesIO:
    """Render LongFormReportResult as PDF. Never raises."""
    from vertical_engines.wealth.long_form_report.pdf_renderer import render_long_form_pdf
    try:
        return render_long_form_pdf(result, portfolio_name=portfolio_name, language=language)
    except Exception:
        logger.exception("long_form_pdf_render_failed", portfolio_id=result.portfolio_id)
        from io import BytesIO
        return BytesIO()
```

### Padrão de header/footer

Usar `netz_header_footer` com `right_logo_path=None` (sem Necker — Wealth):

```python
def _on_page(canvas: Any, doc_obj: Any) -> None:
    netz_header_footer(
        canvas, doc_obj,
        report_title=f"{portfolio_name} — {labels['long_form_report_title']}",
        confidentiality=labels["confidential"],
        right_logo_path=None,
    )
```

> **Nota**: `labels["long_form_report_title"]` pode não existir em `i18n.py`.
> Verificar antes. Se ausente, usar string literal
> `"Relatório Institucional"` (pt) / `"Institutional Report"` (en) diretamente.

---

## O que NÃO fazer

- **Não** modificar nenhum caller do Credit em `ai_engine/pdf/` — eles devem
  continuar recebendo `LOGO_NECKER` via default
- **Não** importar `Fund` em código novo — sempre usar `Instrument`
- **Não** criar um PDF renderer genérico que tente cobrir todos os engines —
  `render_long_form_pdf` é específico para `LongFormReportResult`
- **Não** usar `build_ic_cover_story()` no Wealth — é para o IC Memo do Credit
- **Não** fazer chamadas LLM no renderer PDF — o conteúdo já está em
  `ChapterResult.content`
- **Não** levantar exceções no renderer — never-raises, retornar `BytesIO()`
  vazio em caso de falha

---

## Ordem de execução

1. Leia todos os arquivos listados em cada problema antes de editar
2. Aplique Problema 1 (logo) — 4 arquivos, cirúrgico
3. Aplique Problema 2 (Fund→Instrument) — 1 arquivo, ~30 linhas
4. Crie `pdf_renderer.py` (Problema 3) — arquivo novo
5. Adicione `render_pdf()` ao engine (Problema 3)
6. Execute `make check` — zero novos erros esperados

---

## Definition of Done

- [ ] `netz_header_footer` aceita `right_logo_path: str | None = LOGO_NECKER`
- [ ] Os 3 callers Wealth passam `right_logo_path=None`
- [ ] Callers Credit não foram modificados (preservam default)
- [ ] `ManagerSpotlight._gather_fund_data` usa `Instrument`, não `Fund`
- [ ] `backend/vertical_engines/wealth/long_form_report/pdf_renderer.py` criado
- [ ] `LongFormReportEngine.render_pdf()` adicionado
- [ ] `make check` passa sem novos erros
