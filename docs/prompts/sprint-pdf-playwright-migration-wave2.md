# Sprint: Playwright PDF Migration Wave 2 — Fact Sheet, DD Report, Content Reports

## Contexto

Na sessão anterior migramos a infraestrutura Playwright e criamos dois novos
relatórios (Long-Form DD + Monthly Client Report). O pacote `pdf/` já existe:

```
vertical_engines/wealth/pdf/
  __init__.py
  html_renderer.py        ← html_to_pdf(html) → bytes (Playwright Chromium)
  svg_charts.py           ← performance_line_chart(), drawdown_chart(), allocation_bars()
  templates/
    __init__.py
    long_form_dd.py       ← 4-page Long-Form DD template (já implementado)
    monthly_client.py     ← 4-page Monthly Client Report template (já implementado)
```

Agora migramos os 5 relatórios restantes de ReportLab → Playwright HTML/CSS:

1. **Fact Sheet Executive** (1-2 páginas) — substituir `fact_sheet/executive_renderer.py`
2. **Fact Sheet Institutional** (4-6 páginas) — substituir `fact_sheet/institutional_renderer.py`
3. **DD Report** (multi-página, 8 capítulos) — substituir `ai_engine/pdf/generate_dd_report_pdf.py`
4. **Content PDF** (genérico, usado por 3 engines abaixo) — substituir `content_pdf.py`
   - Investment Outlook
   - Flash Report
   - Manager Spotlight

**Após este sprint:** os ReportLab renderers podem ser removidos e `reportlab`
eliminado do `pyproject.toml` (se nenhum outro módulo usar).

---

## Regras Críticas do Codebase (ler antes de escrever código)

- Templates HTML são IP — ficam em arquivos `.py` como strings Python, nunca
  em `.html` servidos via API
- Import-linter: `pdf/` não pode importar de `dd_report/` ou vice-versa
- Reutilize `html_to_pdf()` de `pdf/html_renderer.py` — não crie novo renderer
- Reutilize `svg_charts.py` para gráficos (performance line, drawdown, allocation bars)
- Font stack: `-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif`
- CSS: `@page { size: A4; margin: 0; }`, `.page { page-break-after: always; }`
- `html.escape()` em todo texto do usuário
- Sem referências externas (fontes, imagens, CSS) — tudo inline/self-contained
- Sem `...` placeholders — implementar completamente cada template
- `from __future__ import annotations` em todos os arquivos
- Ruff clean (`F541` em f-strings sem placeholders é o erro mais comum)

---

## Passo 0 — Ler antes de escrever

```
backend/vertical_engines/wealth/pdf/html_renderer.py
backend/vertical_engines/wealth/pdf/svg_charts.py
backend/vertical_engines/wealth/pdf/templates/long_form_dd.py    ← referência de estilo
backend/vertical_engines/wealth/pdf/templates/monthly_client.py  ← referência de estilo
backend/vertical_engines/wealth/fact_sheet/models.py             ← FactSheetData
backend/vertical_engines/wealth/fact_sheet/fact_sheet_engine.py
backend/vertical_engines/wealth/fact_sheet/executive_renderer.py ← ReportLab (substituir)
backend/vertical_engines/wealth/fact_sheet/institutional_renderer.py ← ReportLab (substituir)
backend/vertical_engines/wealth/fact_sheet/i18n.py               ← LABELS, Language
backend/vertical_engines/wealth/dd_report/models.py              ← DDReportResult, ChapterResult
backend/vertical_engines/wealth/dd_report/dd_report_engine.py
backend/ai_engine/pdf/generate_dd_report_pdf.py                  ← ReportLab (substituir)
backend/vertical_engines/wealth/content_pdf.py                   ← ReportLab (substituir)
backend/vertical_engines/wealth/flash_report.py                  ← usa content_pdf.render_content_pdf
backend/vertical_engines/wealth/investment_outlook.py            ← usa content_pdf.render_content_pdf
backend/vertical_engines/wealth/manager_spotlight.py             ← usa content_pdf.render_content_pdf
backend/app/domains/wealth/routes/fact_sheets.py                 ← download_dd_report_pdf endpoint
```

---

## Passo 1 — Template: Fact Sheet Executive

Novo arquivo: `vertical_engines/wealth/pdf/templates/fact_sheet_executive.py`

Função: `render_fact_sheet_executive(data: FactSheetData, *, language: str = "en") -> str`

Recebe `FactSheetData` de `fact_sheet/models.py`. Campos disponíveis:
- `portfolio_name`, `profile`, `as_of`, `inception_date`
- `returns: ReturnMetrics` (mtd, qtd, ytd, one_year, three_year, since_inception, is_backtest)
- `risk: RiskMetrics` (annualized_vol, sharpe, max_drawdown, cvar_95)
- `holdings: list[HoldingRow]` (fund_name, block_id, weight)
- `allocations: list[AllocationBlock]` (block_id, weight)
- `nav_series: list[NavPoint]` (nav_date, nav, benchmark_nav) — converter para svg_charts.NavPoint
- `manager_commentary: str`
- `benchmark_label: str`

**Layout (1-2 páginas):**

**Página 1:**
- Header navy `#111827` com label "EXECUTIVE SUMMARY · FACT SHEET", nome do
  portfólio (20px, branco), data-base e perfil
- Bloco KPIs (4 colunas): MTD, YTD, 1Y, Since Inception — valores percentuais
  com cor (verde positivo, vermelho negativo)
- Performance chart SVG via `performance_line_chart()` (converter `nav_series`)
- Tabela de retornos (Portfolio vs Benchmark vs Active) por período
- Grid 2 colunas:
  - Allocation bars via `allocation_bars()`
  - Top Holdings tabela (top 8)
- Risk metrics: 4 cards (Vol, Sharpe, Max DD, CVaR)
- Manager Commentary bloco (se presente)
- Footer: disclaimer + data + "p. 1 of N"

**Página 2 (se houver mais de 8 holdings):**
- Continuação da tabela de holdings
- Nota de backtest (se `is_backtest=True`)

Labels via `i18n.LABELS[language]` — bilíngue PT/EN.

---

## Passo 2 — Template: Fact Sheet Institutional

Novo arquivo: `vertical_engines/wealth/pdf/templates/fact_sheet_institutional.py`

Função: `render_fact_sheet_institutional(data: FactSheetData, *, language: str = "en") -> str`

Mesmos dados de `FactSheetData`, mas com campos adicionais:
- `attribution: list[AttributionRow]` (block_name, allocation_effect, selection_effect, interaction_effect, total_effect)
- `stress: list[StressRow]` (name, start_date, end_date, portfolio_return, max_drawdown)
- `regimes: list[RegimePoint]` (regime_date, regime)
- `fee_drag: dict | None` (total_instruments, weighted_gross_return, weighted_net_return, weighted_fee_drag_pct, instruments[])

**Layout (4-6 páginas):**

**Página 1:** Igual ao Executive (header, KPIs, performance chart, retornos)

**Página 2:** Allocation + Holdings + Risk metrics

**Página 3:** Attribution Analysis
- Tabela Brinson-Fachler (Block, Allocation, Selection, Interaction, Total)
- Footer de totais

**Página 4:** Risk Deep-Dive
- Stress scenarios tabela
- Regime overlay (visual: barras horizontais coloridas por período de regime com
  rótulos Expansion/Contraction/Crisis sobre o eixo temporal)
- Fee Drag analysis (se `fee_drag` presente): tabela por fundo + resumo

**Página 5 (se necessário):** Fee comparison por fundo + disclaimer

Labels bilíngues PT/EN.

---

## Passo 3 — Template: DD Report

Novo arquivo: `vertical_engines/wealth/pdf/templates/dd_report.py`

Função: `render_dd_report(data: DDReportPDFData, *, language: str = "en") -> str`

Defina `DDReportPDFData` inline no template (ou em `dd_report/models.py` se
preferir evitar import circular):

```python
@dataclass(frozen=True)
class DDReportPDFData:
    fund_name: str
    fund_id: str
    as_of: date
    confidence_score: float      # 0-1
    decision_anchor: str | None  # "approve" | "reject" | "review"
    chapters: list  # list[ChapterResult] from dd_report/models.py
    language: str = "en"
```

`ChapterResult` campos: `tag`, `order`, `title`, `content_md` (Markdown string),
`evidence_refs: dict`, `quant_data: dict`, `critic_iterations: int`,
`critic_status: str`.

**Layout (multi-página, 8 capítulos):**

**Página 1 — Capa:**
- Header navy com "DUE DILIGENCE REPORT · CONFIDENTIAL"
- Fund name (22px, branco)
- "Prepared {date} · Netz Adversarial AI Engine"
- Confidence gauge: barra horizontal colorida (verde >0.8, amarelo 0.6-0.8,
  vermelho <0.6) com label "{score:.0%} Confidence"
- Decision anchor badge (APPROVE verde / REVIEW amarelo / REJECT vermelho)
- Table of Contents: 8 capítulos numerados
- Metadata: critic iterations, status, sources count

**Páginas 2+:**
- Page header com fund name + page number
- Cada capítulo: header com `border-left:3px solid #185FA5`,
  "CHAPTER N" (9px muted) + título (16px)
- `content_md` renderizado como HTML (converter markdown headings `## ` → `<h3>`,
  `**bold**` → `<strong>`, `- item` → `<li>`, parágrafos por `\n\n`)
- Evidence refs box: `background:#f0f4ff` com lista de fontes
- Quant data box (se presente): métricas em cards
- Separador entre capítulos (HR ou novo page-break a cada 2-3 capítulos)

**Página final:** Disclaimer + methodology note + confidence scoring explanation

---

## Passo 4 — Template: Content Reports (genérico)

Novo arquivo: `vertical_engines/wealth/pdf/templates/content_report.py`

Função: `render_content_report(content_md: str, *, title: str, subtitle: str = "", language: str = "en") -> str`

Substitui `content_pdf.render_content_pdf()`. Usado por 3 engines:
- Investment Outlook → `title="Investment Outlook"` / `"Perspectiva de Investimento"`
- Flash Report → `title="Market Flash Report"` / `"Relatório Flash de Mercado"`
- Manager Spotlight → `title="Manager Spotlight"`, `subtitle=fund_name` / `"Destaque do Gestor"`

**Layout (1-3 páginas):**

**Página 1:**
- Header navy com título (uppercase tracking) + subtítulo (se houver)
- Data
- Conteúdo markdown renderizado: `## heading` → `<h3>`, parágrafos, listas
- Footer: disclaimer bilíngue + paginação

**Páginas seguintes:** continuação do conteúdo (page-break automático via CSS)

---

## Passo 5 — Integrar nos engines existentes

### 5.1 `fact_sheet_engine.py`

O `FactSheetEngine.generate()` atualmente é **síncrono** e retorna `BytesIO`.
Playwright é async. Duas opções:

**Opção A (recomendada):** Adicione um método `async def generate_async(...)` que
usa os novos templates Playwright, mantendo o `generate()` síncrono existente
como fallback. Os callers async (rotas) usam `generate_async()`.

**Opção B:** Converta `generate()` para async. Isso impacta mais callers.

Implemente Opção A:

```python
async def generate_async(
    self,
    db: AsyncSession,
    *,
    portfolio_id: str,
    organization_id: str,
    format: FactSheetFormat = "executive",
    language: Language = "pt",
    as_of: date | None = None,
) -> bytes:
    """Generate fact-sheet PDF via Playwright (async). Returns raw PDF bytes."""
    # 1. Load data (reuse _build_fact_sheet_data via asyncio.to_thread)
    # 2. Render HTML via template
    # 3. html_to_pdf() → bytes
```

### 5.2 Content engines (flash_report, investment_outlook, manager_spotlight)

Cada engine tem `render_pdf()` síncrono. Adicione `async def render_pdf_async()`
que usa o novo template Playwright. Mantenha o método síncrono como fallback.

```python
async def render_pdf_async(self, content_md: str, *, language: Language = "pt") -> bytes:
    from vertical_engines.wealth.pdf.html_renderer import html_to_pdf
    from vertical_engines.wealth.pdf.templates.content_report import render_content_report
    html = render_content_report(content_md, title=..., language=language)
    return await html_to_pdf(html, print_background=True)
```

### 5.3 DD Report PDF

Em `ai_engine/pdf/generate_dd_report_pdf.py`, adicione:

```python
async def generate_dd_report_pdf_async(...) -> bytes:
    """Playwright-based DD Report PDF. Replaces ReportLab version."""
    from vertical_engines.wealth.pdf.html_renderer import html_to_pdf
    from vertical_engines.wealth.pdf.templates.dd_report import render_dd_report, DDReportPDFData
    data = DDReportPDFData(...)
    html = render_dd_report(data, language=language)
    return await html_to_pdf(html, print_background=True)
```

### 5.4 Route migration

No endpoint `download_dd_report_pdf` em `routes/fact_sheets.py`, chame a versão
async se disponível, fallback para ReportLab. Pattern:

```python
try:
    pdf_bytes = await generate_dd_report_pdf_async(...)
    return Response(content=pdf_bytes, media_type="application/pdf", ...)
except Exception:
    # Fallback to ReportLab
    pdf_buf = generate_dd_report_pdf(...)
    return Response(content=pdf_buf.read(), ...)
```

---

## Passo 6 — Testes

Em `backend/tests/test_pdf_playwright.py`, adicione testes para os novos templates:

```python
def test_fact_sheet_executive_template_renders():
    """render_fact_sheet_executive returns valid HTML."""
    ...

def test_fact_sheet_institutional_template_renders():
    """render_fact_sheet_institutional returns valid HTML."""
    ...

def test_dd_report_template_renders():
    """render_dd_report returns valid HTML with 8 chapters."""
    ...

def test_content_report_template_renders():
    """render_content_report returns valid HTML for markdown content."""
    ...
```

Execute `make check` ao final. Zero regressions.

---

## Passo 7 — Demo PDFs para validação visual

Após implementação, gere versões demo de TODOS os templates para validação visual.

Crie/atualize `backend/scripts/preview_playwright_pdfs.py` adicionando:

1. **Fact Sheet Executive** — dados mock com 8 holdings, NAV series 24 meses,
   retornos e risk metrics realistas
2. **Fact Sheet Institutional** — mesmos dados + attribution (5 blocos),
   stress (4 cenários), regimes (3 períodos), fee_drag (8 fundos)
3. **DD Report** — 8 capítulos com `content_md` markdown realista (2-3 parágrafos
   cada, com `## subheadings` e `**bold**`), confidence 0.82, decision "approve"
4. **Content Report — Investment Outlook** — 4 seções markdown (Global Macro,
   Regional, Asset Class Views, Portfolio Positioning)
5. **Content Report — Flash Report** — 3 seções curtas (Event, Impact, Actions)
6. **Content Report — Manager Spotlight** — 4 seções (Overview, Strategy,
   Performance, Assessment) com `subtitle="Vanguard S&P 500 ETF"`
7. **Long-Form DD** — manter o demo existente
8. **Monthly Client Report** — manter o demo existente

Salvar todos em `backend/.data/`:
```
preview_fact_sheet_executive.pdf
preview_fact_sheet_institutional.pdf
preview_dd_report.pdf
preview_content_investment_outlook.pdf
preview_content_flash_report.pdf
preview_content_manager_spotlight.pdf
preview_long_form_dd.pdf          (já existe)
preview_monthly_client.pdf        (já existe)
```

E os HTMLs correspondentes para debug de layout no browser.

Usar textos realistas de relatório financeiro institucional — não lorem ipsum.

---

## Checklist de Entrega

- [ ] `templates/fact_sheet_executive.py` — HTML completo, bilíngue PT/EN
- [ ] `templates/fact_sheet_institutional.py` — HTML completo, bilíngue PT/EN
- [ ] `templates/dd_report.py` — HTML completo com 8 capítulos markdown
- [ ] `templates/content_report.py` — HTML genérico para content engines
- [ ] `fact_sheet_engine.py` → `generate_async()` usando novo template
- [ ] `flash_report.py` → `render_pdf_async()` usando novo template
- [ ] `investment_outlook.py` → `render_pdf_async()` usando novo template
- [ ] `manager_spotlight.py` → `render_pdf_async()` usando novo template
- [ ] `generate_dd_report_pdf.py` → `generate_dd_report_pdf_async()` usando novo template
- [ ] Testes passando para todos os novos templates
- [ ] `make check` verde (lint + architecture + tests)
- [ ] 8 PDFs demo gerados em `backend/.data/` para validação visual
