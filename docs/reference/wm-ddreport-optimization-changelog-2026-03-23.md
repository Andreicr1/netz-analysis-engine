---
title: "Wealth DD Report — Optimization Changelog (Phases 0-4)"
date: 2026-03-23
origin: docs/plans/2026-03-20-wm-ddreport-optimization-backlog.md
status: ALL PHASES COMPLETE
---

# Wealth DD Report — Optimization Changelog

> Documento de referencia completo das 4 fases de otimizacao do DD Report engine.
> Descreve o pipeline de geracao, as alteracoes feitas em cada fase, e o comportamento
> esperado de cada capitulo apos as otimizacoes.

---

## 1. Visao Geral do Pipeline de Geracao

### Fluxo de Execucao

```
POST /api/v1/wealth/dd-reports/{fund_id}/generate
  -> asyncio.to_thread(_sync_generate)
    -> DDReportEngine.generate(db, instrument_id, actor_id, organization_id)
      1. _ensure_report_record()    — cria/carrega DDReport no banco (resume safety)
      2. _build_evidence()          — monta EvidencePack (frozen dataclass)
      3. _generate_all_chapters()   — gera capitulos 1-7 sequencial, depois cap 8
      4. compute_confidence_score() — scoring de confianca baseado em evidencia
      5. derive_decision_anchor()   — ancora de decisao (APPROVE/CONDITIONAL/REJECT)
      6. _persist_results()         — persiste DDChapter + atualiza DDReport
```

### Montagem do Evidence Pack

O `_build_evidence()` consulta 4 fontes de dados:

| Fonte | Metodo | Dados |
|---|---|---|
| **Fund table** | `db.query(Fund)` | Identidade: name, ISIN, ticker, fund_type, geography, asset_class, manager_name, currency, domicile, inception_date, aum_usd |
| **FundRiskMetrics** | `gather_quant_metrics()` | Metricas quant: retornos multi-periodo, Sharpe, Sortino, alpha, CVaR, volatility, beta, drawdown, drift score, momentum |
| **SEC 13F** | `gather_sec_13f_data()` | Holdings: sector_weights, drift_detected, drift_quarters |
| **SEC ADV** | `gather_sec_adv_data()` | Manager: AUM regulatorio, fee structure, compliance_disclosures, team bios, funds managed |

O resultado e um `EvidencePack` (frozen dataclass, thread-safe). Cada capitulo recebe uma visao filtrada via `filter_for_chapter(tag)`.

### Geracao por Capitulo

Para cada capitulo:

1. `filter_for_chapter(tag)` — filtra evidence context (ex: fee_analysis zera quant_profile)
2. `compute_source_metadata(tag)` — calcula `structured_data_complete/partial/absent`
3. Template Jinja2 e renderizado com context + source metadata → system prompt
4. `_build_user_content(tag, context)` — monta user message com dados brutos
5. LLM call (OpenAI) → resposta sanitizada via `sanitize_llm_text()` (6-stage pipeline)
6. `ChapterResult` (frozen dataclass) retornado

### Ordem dos 8 Capitulos

| Ordem | Tag | Titulo | Tipo |
|---|---|---|---|
| 1 | `executive_summary` | Executive Summary | ANALYTICAL |
| 2 | `investment_strategy` | Investment Strategy & Process | DESCRIPTIVE |
| 3 | `manager_assessment` | Fund Manager Assessment | ANALYTICAL |
| 4 | `performance_analysis` | Performance Analysis | ANALYTICAL |
| 5 | `risk_framework` | Risk Management Framework | ANALYTICAL |
| 6 | `fee_analysis` | Fee Analysis | DESCRIPTIVE |
| 7 | `operational_dd` | Operational Due Diligence | DESCRIPTIVE |
| 8 | `recommendation` | Recommendation | ANALYTICAL (synthesis) |

Capitulos 1-7 sao gerados sequencialmente. Capitulo 8 (Recommendation) e gerado depois, consumindo os primeiros 500 chars de cada capitulo anterior como `chapter_summaries`.

---

## 2. Phase 0 — Audit (Data Source Mapping)

**Status:** DONE
**Artefato:** `docs/reference/wm-ddreport-evidence-pack-audit-2026-03-20.md`
**Alteracoes em codigo:** Nenhuma (read-only investigation)

### O que foi feito

Mapeamento completo de cada variavel de template para sua fonte de dados, produzindo uma matriz de completude por capitulo.

### Descobertas criticas

1. **Campos declarados mas nunca populados:** `documents`, `scoring_data`, `macro_snapshot` no EvidencePack sao sempre `[]`/`{}`.
2. **SEC data nao conectado:** Nenhum dado SEC (ADV, 13F) chegava ao evidence pack antes das fases seguintes.
3. **`filter_for_chapter("fee_analysis")`** zera `quant_profile` e `risk_metrics` — capitulo recebe apenas identidade.
4. **Linguagem de hedging** identificada em 6 dos 8 templates, com acoes designadas por fase.

### Matriz de Completude (pre-otimizacao)

| Capitulo | Fund Identity | Quant/Risk | SEC Data | Completude |
|---|---|---|---|---|
| Executive Summary | 7 campos | 4 campos | — | FULL |
| Investment Strategy | 5 campos | — | — | PARTIAL (identity-only) |
| Manager Assessment | 4 campos | 4 campos | — | PARTIAL (no ADV) |
| Performance Analysis | 2 campos | 10 campos | — | FULL |
| Risk Framework | 2 campos | 15 campos | — | FULL |
| Fee Analysis | 4 campos | zeroed | — | MINIMAL |
| Operational DD | 3 campos | — | — | MINIMAL |
| Recommendation | 2 campos | — | — | FULL (synthesis) |

---

## 3. Phase 1 — Remove Hedging from Stable Chapters

**Status:** DONE
**Arquivos modificados:** 4 templates Jinja2

### Principio

Templates estavam usando linguagem especulativa ("where available", "if document evidence", "additional documentation", "site visits") para dados que nunca eram passados. Isso fazia o LLM gerar texto condicional sobre informacoes que nao existiam no contexto, diluindo a qualidade do output.

### Alteracoes por template

#### `fee_analysis.j2`
- **Antes:** "Where specific fee data is available from documents, cite exact figures. Where not, note the information gaps."
- **Depois:** "State available fee data directly. For fields not available from the data provider, write '[Not available from YFinance/FEfundinfo]' instead of speculating."
- **Motivo:** Nenhum documento e passado ao capitulo de fees. A instrucao "from documents" induzia o LLM a inventar dados.

#### `investment_strategy.j2`
- **Antes:** "If document evidence is available, cite specific sources. If not, note where additional documentation would strengthen the analysis."
- **Depois:** "Base your analysis on the fund identity and classification data provided. For strategy details not available from structured data, state plainly that the information is not available rather than speculating."
- **Motivo:** Capitulo recebe apenas identidade do fundo. "Cite specific sources" induzia citacao ficticia.

#### `operational_dd.j2`
- **Antes:** "Note where documentation is available vs. where additional operational due diligence site visits or calls would be needed."
- **Depois:** "Assess operational infrastructure based on available data. For information not reported by the data provider, write '[Not reported by provider]'. Do not reference site visits or calls."
- **Motivo:** Site visits e calls nao fazem parte do escopo de um DD report automatizado.

#### `executive_summary.j2`
- **Antes:** "evidence-based"
- **Depois:** "data-driven"
- **Motivo:** O report e baseado em dados estruturados, nao em "evidencia" documental (que nao chega ao template).

#### `manager_assessment.j2` — NAO MODIFICADO nesta fase
A linguagem "Provide specific evidence where available" era correta pre-ADV porque o capitulo realmente nao tinha dados de manager profile. A remocao aconteceu na Phase 3, quando dados ADV foram conectados.

---

## 4. Phase 2 — Source-Aware Context Block

**Status:** DONE
**Arquivos modificados:** `evidence_pack.py` + todos 8 templates

### Principio

Cada capitulo agora sabe exatamente quais dados estao presentes e quais estao ausentes, ANTES do LLM gerar texto. Isso elimina a necessidade de hedging generico — o template diz ao LLM o estado exato dos dados.

### Mecanismo implementado

#### `evidence_pack.py` — `compute_source_metadata(chapter_tag)`

Retorna um dict com:

```python
{
    "structured_data_complete": bool,   # Todos campos esperados presentes
    "structured_data_partial": bool,    # Alguns campos presentes
    "structured_data_absent": bool,     # Nenhum campo presente
    "data_providers": ["YFinance", ...],
    "available_fields": ["fund_name", ...],
    "missing_fields": ["adv_team", ...],
    "primary_provider": "YFinance",
}
```

#### `_CHAPTER_FIELD_EXPECTATIONS` — expectativas por capitulo

Define quais campos cada capitulo espera e de quais providers:

| Capitulo | Campos esperados | Providers |
|---|---|---|
| `fee_analysis` | fund_name, fund_type, currency | YFinance |
| `investment_strategy` | fund_name, fund_type, geography, asset_class, thirteenf_available, sector_weights | YFinance, SEC EDGAR 13F |
| `operational_dd` | fund_name, manager_name, domicile, compliance_disclosures | YFinance, SEC EDGAR ADV |
| `manager_assessment` | fund_name, manager_name, adv_aum_history, adv_compliance_disclosures, adv_team | YFinance, SEC EDGAR ADV |
| `performance_analysis` | sharpe_1y, return_1y, return_3m, return_1m, cvar_95_3m, max_drawdown_1y | YFinance |
| `risk_framework` | cvar_95_1m/3m/12m, volatility_1y, beta_1y, risk_metrics | YFinance |
| `executive_summary` | fund_name, fund_type, geography, asset_class, sharpe_1y, return_1y, cvar_95_3m | YFinance |
| `recommendation` | fund_name, fund_type, sharpe_1y, return_1y, cvar_95_3m, risk_metrics | YFinance |

#### Preamble no template

Todos 8 templates receberam o bloco padrao:

```jinja2
{% if structured_data_complete is defined %}
{% if structured_data_complete %}
## Data Availability
All structured data fields for this chapter are available from {{ primary_provider }}. Base your analysis on these fields directly.
{% elif structured_data_partial %}
## Data Availability
Partial structured data available from {{ data_providers | join(', ') }}.
Available: {{ available_fields | join(', ') }}.
Not available: {{ missing_fields | join(', ') }}.
For missing fields, write '[Not available from {{ primary_provider }}]'.
{% elif structured_data_absent %}
## Data Availability
No structured data available for this chapter. State this clearly and do not speculate.
{% endif %}
{% endif %}
```

### Comportamento esperado

- **`structured_data_complete`:** LLM usa os dados diretamente, sem ressalvas.
- **`structured_data_partial`:** LLM lista explicitamente o que falta, usando `[Not available from X]`.
- **`structured_data_absent`:** LLM declara ausencia e nao especula.

Para `manager_assessment`: `structured_data_complete` requer campos ADV presentes — apenas identidade YFinance = `partial` no maximo.

### Injecao no pipeline

`chapters.py:generate_chapter()` injeta source metadata no template context:

```python
if evidence_pack is not None:
    ctx.update(evidence_pack.compute_source_metadata(chapter_tag))
```

`dd_report_engine.py` passa `evidence_pack=evidence` a todas as chamadas de `generate_chapter()`.

---

## 5. Phase 3 — SEC Layer Integration

**Status:** DONE
**Arquivos criados:** `sec_injection.py`
**Arquivos modificados:** `evidence_pack.py`, `dd_report_engine.py`, `chapters.py`, 3 templates

### Principio

Conectar dados regulatorios SEC (13F holdings + ADV manager profile) ao evidence pack, dando ao LLM dados reais da SEC ao inves de depender apenas de identidade do fundo.

### Arquivo criado: `sec_injection.py`

Duas funcoes sync (compativel com `asyncio.to_thread()`):

#### `gather_sec_13f_data(db, manager_name, cik=None)`

1. Resolve `manager_name` → CIK via `sec_managers.firm_name` (case-insensitive)
2. Busca ate 8 quarters de `sec_13f_holdings` (lookback 8*92 dias)
3. Calcula `sector_weights` para quarter mais recente (exclui opcoes CALL/PUT)
4. Detecta drift (>5pp de mudanca em qualquer setor entre 2 quarters)
5. Retorna: `thirteenf_available`, `sector_weights`, `drift_detected`, `drift_quarters`

#### `gather_sec_adv_data(db, manager_name, crd_number=None)`

1. Resolve `manager_name` → CRD via `sec_managers.firm_name` (case-insensitive)
2. Busca `SecManager` → AUM (total/discretionary/non-discretionary), fee_types, compliance_disclosures
3. Busca `SecManagerFund` → fundos geridos (Schedule D)
4. Busca `SecManagerTeam` → bios, titulos, certificacoes, experiencia
5. Retorna: `compliance_disclosures`, `adv_aum_history`, `adv_fee_structure`, `adv_funds`, `adv_team`

### Campos adicionados ao EvidencePack

```python
# SEC 13F
thirteenf_available: bool = False
sector_weights: dict[str, float] = {}
drift_detected: bool = False
drift_quarters: int = 0

# SEC ADV
compliance_disclosures: int | None = None
adv_aum_history: dict[str, Any] = {}
adv_fee_structure: list[str] = []
adv_funds: list[dict[str, Any]] = []
adv_team: list[dict[str, Any]] = []
```

### Wiring no `dd_report_engine.py`

```python
# SEC data (global tables, no RLS — DB-only reads)
manager_name = fund.manager_name
sec_13f = gather_sec_13f_data(db, manager_name=manager_name)
sec_adv = gather_sec_adv_data(db, manager_name=manager_name)

return build_evidence_pack(
    fund_data=fund_data,
    quant_profile=quant_profile,
    risk_metrics=risk_metrics,
    sec_13f_data=sec_13f,
    sec_adv_data=sec_adv,
)
```

### Alteracoes nos templates

#### `investment_strategy.j2` — bloco 13F holdings verification

```jinja2
{% if thirteenf_available is defined and thirteenf_available %}
## SEC 13F Holdings Verification ({{ drift_quarters }} quarters of data)
The manager's most recent 13F-HR filing reports the following sector allocation:
{% for sector, weight in sector_weights.items() %}
- {{ sector }}: {{ "%.1f"|format(weight * 100) }}%
{% endfor %}
{% if drift_detected %}
**⚠ Sector drift detected:** Material shift (>5pp) in sector weights...
{% else %}
Sector allocation is stable quarter-over-quarter (no material drift detected).
{% endif %}
Cross-reference the stated investment strategy against this 13F sector allocation...
{% endif %}
```

**Comportamento esperado:**
- Se 13F disponivel: LLM ve alocacao setorial real e deve verificar consistencia com estrategia declarada.
- Se drift detectado: LLM sinaliza divergencia para equipe de investimentos.
- Se 13F indisponivel: bloco nao aparece, capitulo usa apenas identidade.

#### `operational_dd.j2` — bloco compliance disclosures

```jinja2
{% if compliance_disclosures is defined and compliance_disclosures is not none %}
## SEC Compliance Record
{% if compliance_disclosures > 0 %}
**⚠ {{ compliance_disclosures }} compliance disclosure(s)** on file with SEC/IAPD...
{% else %}
No compliance disclosures on file with SEC/IAPD. Clean regulatory record...
{% endif %}
{% else %}
## SEC Compliance Record
[SEC registration not confirmed] — Manager not found in SEC/IAPD database...
{% endif %}
```

**Comportamento esperado:**
- `compliance_disclosures = 0`: registro limpo, LLM menciona positivamente.
- `compliance_disclosures > 0`: flag de alerta, LLM deve referir Form ADV Part 1A Item 11.
- `compliance_disclosures = None` (nao encontrado): semantica de ausencia SEC, nao "provider didn't report".

#### `manager_assessment.j2` — ADV AUM, fees, team, key person detection

Template exibe blocos condicionais para:
- **Regulatory AUM** (total, discretionary, non-discretionary, total accounts) — de Form ADV Part 1A
- **Fee Structure** — fee types reportados a SEC
- **Key Personnel** — nome, titulo, experiencia, certificacoes de cada membro

Instrucoes condicionais no bloco Instructions:
- Se `adv_team` presente: "Flag key person risk if fewer than 3 senior professionals or if one individual holds multiple critical roles."
- Se `adv_team` ausente: "[Team data not available from SEC EDGAR ADV]"
- Se `adv_aum_history` presente: "Use the SEC-reported regulatory AUM figures as authoritative."
- Se `adv_fee_structure` presente: "Reference the SEC-reported fee types."

**Comportamento esperado:**
- Com ADV: capitulo usa dados regulatorios como fonte autoritativa, key person detection automatico.
- Sem ADV: capitulo funciona com identidade + quant apenas, sinaliza ausencia sem especular.

### User message enrichment (`chapters.py:_build_user_content`)

O user message agora inclui dados SEC para capitulos relevantes:
- `investment_strategy`: setor allocation + drift warning
- `manager_assessment`: regulatory AUM + team members
- `operational_dd`: compliance disclosures count

---

## 6. Phase 4 — Tighten Quant-Driven Chapters

**Status:** DONE
**Arquivos modificados:** 2 templates Jinja2

### Principio

`performance_analysis` e `risk_framework` recebem dados 100% deterministicos do `quant_engine` (CVaR, Sharpe, volatility, etc.). Numeros computados nao sao especulativos — ou atingem thresholds institucionais ou nao. Linguagem interpretativa ("interpret in context", "flag concerning trends") induzia o LLM a adicionar qualificadores desnecessarios.

### Alteracoes

#### `performance_analysis.j2`
- **Antes:** "Use the quantitative metrics provided. Interpret numbers in context (peer group, market conditions). Flag any performance anomalies."
- **Depois:** "Use the quantitative metrics provided. State each metric directly — Sharpe below 0.5 is subpar, drawdown beyond -15% is material, negative alpha indicates underperformance. Numbers either meet institutional thresholds or they do not."

**Comportamento esperado:** LLM faz afirmacoes diretas sobre cada metrica. "Sharpe de 0.32 e abaixo do threshold institucional de 0.5" ao inves de "Sharpe de 0.32 pode indicar, dependendo do contexto de mercado..."

#### `risk_framework.j2`
- **Antes:** "Interpret CVaR and risk metrics in context. Flag any concerning trends or limit breaches."
- **Depois:** "State each risk metric directly against institutional thresholds. CVaR breaching -5% at 95% confidence is material. Volatility above 15% annualized is elevated. Beta above 1.2 indicates amplified market exposure. Metrics either breach thresholds or they do not — no hedging."

**Comportamento esperado:** LLM compara cada metrica contra thresholds concretos. "CVaR 95% 3M de -7.2% excede o threshold material de -5%" ao inves de "CVaR de -7.2% pode ser preocupante dependendo do regime de mercado..."

### Thresholds institucionais definidos nos templates

| Metrica | Threshold | Significado |
|---|---|---|
| Sharpe (1Y) | < 0.5 | Subpar risk-adjusted return |
| Max Drawdown (1Y) | > -15% | Material loss event |
| Alpha (1Y) | < 0 | Underperformance vs benchmark |
| CVaR 95% | > -5% | Material tail risk |
| Volatility (1Y) | > 15% ann. | Elevated volatility |
| Beta (1Y) | > 1.2 | Amplified market exposure |

---

## 7. Resumo Final — Estado Pos-Otimizacao

### Arquivos criados

| Arquivo | Descricao |
|---|---|
| `dd_report/sec_injection.py` | Queries sync para 13F e ADV (DB-only) |
| `docs/reference/wm-ddreport-evidence-pack-audit-2026-03-20.md` | Audit artifact Phase 0 |

### Arquivos modificados

| Arquivo | Phases | Descricao das alteracoes |
|---|---|---|
| `dd_report/evidence_pack.py` | 2, 3 | Source metadata computation, SEC fields, `_CHAPTER_FIELD_EXPECTATIONS` |
| `dd_report/chapters.py` | 2, 3 | Source metadata injection, SEC data in user message |
| `dd_report/dd_report_engine.py` | 3 | SEC data gathering in `_build_evidence()` |
| `prompts/dd_chapters/fee_analysis.j2` | 1, 2 | Hedging removal + source-aware preamble |
| `prompts/dd_chapters/investment_strategy.j2` | 1, 2, 3 | Hedging removal + preamble + 13F verification block |
| `prompts/dd_chapters/operational_dd.j2` | 1, 2, 3 | Hedging removal + preamble + compliance disclosures block |
| `prompts/dd_chapters/manager_assessment.j2` | 2, 3 | Preamble + ADV AUM/fees/team blocks + key person detection |
| `prompts/dd_chapters/performance_analysis.j2` | 2, 4 | Preamble + threshold-based language |
| `prompts/dd_chapters/risk_framework.j2` | 2, 4 | Preamble + threshold-based language |
| `prompts/dd_chapters/executive_summary.j2` | 1, 2 | "evidence-based" → "data-driven" + preamble |
| `prompts/dd_chapters/recommendation.j2` | 2 | Source-aware preamble |

### Comportamento esperado por capitulo (pos-otimizacao)

| Capitulo | Dados disponiveis | Comportamento LLM |
|---|---|---|
| **Executive Summary** | Identidade + Sharpe/Return/CVaR/Manager Score | Resumo direto, data-driven, sem hedging |
| **Investment Strategy** | Identidade + 13F sector weights (se SEC match) | Se 13F: verifica alinhamento estrategia vs holdings reais. Se nao: declara ausencia |
| **Manager Assessment** | Identidade + Quant + ADV AUM/fees/team (se SEC match) | Se ADV: usa dados regulatorios como autoritativos + key person detection. Se nao: sinaliza parcialidade |
| **Performance Analysis** | Retornos multi-periodo + Sharpe/Sortino/Alpha/IR/Drawdown | Afirmacoes diretas contra thresholds. Sem "interpret in context" |
| **Risk Framework** | CVaR windows + Volatility + Beta + Tracking Error + DTW Drift | Cada metrica comparada contra threshold concreto. Sem "may indicate" |
| **Fee Analysis** | Identidade apenas (quant zerado) | Declara dados ausentes com `[Not available from YFinance/FEfundinfo]` |
| **Operational DD** | Identidade + compliance_disclosures (se SEC match) | Se SEC: contagem de disclosures com semantica clara. Se nao: "[SEC registration not confirmed]" |
| **Recommendation** | Identidade + summaries dos 7 capitulos anteriores | Decisao APPROVE/CONDITIONAL/REJECT vinculante, sem hedging |

### Testes

2630 testes passing em todas as fases. Nenhuma regressao introduzida.
