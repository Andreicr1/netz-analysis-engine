# Prompt — Wealth Embedding v2: Structured Summary Chunks

## Objetivo

Evoluir o `wealth_embedding_worker.py` para gerar **chunks de resumo estruturado** a partir de dados tabulares SEC e ESMA, além dos chunks narrativos já existentes (brochures, DD chapters, macro reviews).

O objetivo final é alimentar o AI Agent do sistema com contexto completo sobre fundos e gestores — tanto texto narrativo quanto dados estruturados transformados em prosa legível.

## Contexto

### Estado atual do worker

O worker `wealth_embedding_worker.py` processa 5 fontes:

| Source | entity_type | source_type | Conteúdo |
|--------|-------------|-------------|----------|
| ADV brochures | `"firm"` | `"brochure"` | Texto narrativo (filosofia, métodos, risco) |
| ESMA funds | `"fund"` | `"esma_fund"` | Nome + tipo + domicílio (pouco semântico) |
| ESMA managers | `"firm"` | `"esma_manager"` | Nome + país + status (pouco semântico) |
| DD chapters | `"fund"` | `"dd_chapter"` | Texto narrativo de DD reports (org-scoped) |
| Macro reviews | `"macro"` | `"macro_review"` | Texto narrativo de decisões macro (org-scoped) |

**Problema:** ESMA funds e ESMA managers geram embeddings de strings curtas (`"Fund Name | UCITS | LU"`) que não carregam semântica real. Os dados estruturados SEC (holdings, AUM, team, fundos privados) não são vetorizados de todo. O agente AI não tem contexto sobre posições, tamanho, estratégia, ou equipe.

### Arquitetura de destino

Substituir os chunks fracos (ESMA fund/manager name-only) e adicionar novos chunks de resumo para:

| Nova Source | entity_type | source_type | Conteúdo gerado |
|-------------|-------------|-------------|-----------------|
| SEC Manager Profile | `"firm"` | `"sec_manager_profile"` | Resumo do gestor (AUM, tipo de fundos, team, compliance) |
| SEC Registered Fund | `"fund"` | `"sec_fund_profile"` | Resumo do fundo (AUM, tipo, top holdings N-PORT, share classes) |
| SEC 13F Holdings Summary | `"firm"` | `"sec_13f_summary"` | Resumo do portfólio institucional (top positions, concentração, setores) |
| SEC Private Funds | `"firm"` | `"sec_private_funds"` | Resumo dos fundos privados (Schedule D, GAV, tipos) |
| ESMA Fund Profile | `"fund"` | `"esma_fund_profile"` | Resumo enriquecido do fundo UCITS (nome, gestora, domicílio, tipo) |
| ESMA Manager Profile | `"firm"` | `"esma_manager_profile"` | Resumo enriquecido do manager (nome, país, nº fundos, status) |

## Tabelas-fonte (schemas relevantes)

### sec_managers (Global, PK: crd_number)
```
crd_number TEXT PK
cik TEXT nullable (13F filer CIK)
firm_name TEXT
registration_status TEXT
aum_total BIGINT (dollars)
aum_discretionary BIGINT
total_accounts INT
fee_types JSONB
client_types JSONB
state TEXT, country TEXT, website TEXT
compliance_disclosures INT
last_adv_filed_at DATE
private_fund_count INT, hedge_fund_count INT, pe_fund_count INT,
vc_fund_count INT, real_estate_fund_count INT, other_fund_count INT
total_private_fund_assets BIGINT
```

### sec_manager_team (Global, FK: crd_number → sec_managers)
```
crd_number TEXT
person_name TEXT
title TEXT nullable
role TEXT nullable
certifications TEXT[] nullable
years_experience INT nullable
bio_summary TEXT nullable
```

### sec_manager_funds (Global, FK: crd_number → sec_managers, UQ: crd_number+fund_name)
```
crd_number TEXT
fund_name TEXT
fund_id TEXT nullable
gross_asset_value BIGINT nullable
fund_type TEXT nullable
is_fund_of_funds BOOLEAN nullable
investor_count INT nullable
```

### sec_registered_funds (Global, PK: cik)
```
cik TEXT PK (fund CIK, NÃO é o CIK da firma)
crd_number TEXT nullable FK → sec_managers (link ao adviser)
fund_name TEXT
fund_type TEXT ('mutual_fund','etf','closed_end','interval_fund')
ticker TEXT nullable
total_assets BIGINT nullable
inception_date DATE nullable
last_nport_date DATE nullable
```

### sec_fund_classes (Global, PK: cik+series_id+class_id)
```
cik TEXT FK → sec_registered_funds
series_id TEXT, series_name TEXT nullable
class_id TEXT, class_name TEXT nullable
ticker TEXT nullable
```

### sec_13f_holdings (Global hypertable, UQ: cik+report_date+cusip)
```
cik TEXT (firm CIK, do 13F filer)
report_date DATE
cusip TEXT, issuer_name TEXT
sector TEXT nullable
shares BIGINT nullable, market_value BIGINT nullable
```

### sec_nport_holdings (Global hypertable, PK: report_date+cik+cusip)
```
cik TEXT (fund CIK)
report_date DATE
cusip TEXT, issuer_name TEXT nullable
sector TEXT nullable
market_value BIGINT nullable, quantity NUMERIC nullable
pct_of_nav NUMERIC nullable
```

### esma_funds (Global, PK: isin)
```
isin TEXT PK
fund_name TEXT
esma_manager_id TEXT FK → esma_managers
domicile TEXT nullable
fund_type TEXT nullable
host_member_states TEXT[] nullable
yahoo_ticker TEXT nullable
```

### esma_managers (Global, PK: esma_id)
```
esma_id TEXT PK
lei TEXT nullable
company_name TEXT
country TEXT nullable
authorization_status TEXT nullable
fund_count INT nullable
sec_crd_number TEXT nullable (cross-ref to US)
```

## wealth_vector_chunks (destino)

```python
class WealthVectorChunk(Base):
    __tablename__ = "wealth_vector_chunks"

    id: str                    # PK, formato: "{source_type}_{entity_key}"
    organization_id: str|None  # NULL para dados globais SEC/ESMA
    entity_id: str|None        # CRD, CIK, ISIN, instrument_id
    entity_type: str           # "firm", "fund", "macro" — NUNCA "manager"
    source_type: str           # discriminador da fonte
    section: str|None          # sub-seção opcional
    content: str               # texto para embedding (o resumo gerado)
    language: str|None         # "en"
    source_row_id: str|None    # referência à fonte
    firm_crd: str|None         # CRD da gestora (para lookup por instrument.attributes.sec_crd)
    filing_date: date|None     # data da última atualização da fonte
    embedding: Vector(3072)    # text-embedding-3-large
    embedding_model: str|None
    embedded_at: datetime|None
```

## Implementação

### Novas funções no worker

Adicionar ao `wealth_embedding_worker.py` (após as 5 fontes existentes):

#### F. `_embed_sec_manager_profiles(db)` → source_type=`"sec_manager_profile"`

**Query:** JOIN `sec_managers` com contagens de `sec_manager_team`, `sec_manager_funds`, e verificação de existência em `wealth_vector_chunks`.

**Template de texto (NÃO usar LLM — gerar com f-string/template):**

```
{firm_name} (CRD {crd_number}) is a {registration_status} investment adviser
based in {state}, {country}. Total AUM: ${aum_total:,.0f} (${aum_discretionary:,.0f}
discretionary). Manages {total_accounts} accounts.

Fund breakdown: {private_fund_count} private funds, {hedge_fund_count} hedge funds,
{pe_fund_count} PE funds, {vc_fund_count} VC funds. Total private fund assets:
${total_private_fund_assets:,.0f}.

Investment team ({team_count} professionals): {top_3_team_members}.

Fee structures: {fee_types_summary}.
Client types: {client_types_summary}.
Last ADV filed: {last_adv_filed_at}.
Compliance disclosures: {compliance_disclosures}.
```

**id format:** `sec_manager_profile_{crd_number}`
**entity_type:** `"firm"`
**entity_id:** `crd_number`
**firm_crd:** `crd_number`

#### G. `_embed_sec_fund_profiles(db)` → source_type=`"sec_fund_profile"`

**Query:** JOIN `sec_registered_funds` com `sec_fund_classes` (share classes) e últimas N-PORT holdings (top 10 por market_value do report_date mais recente). LEFT JOIN `sec_managers` para nome do adviser.

**Template:**

```
{fund_name} (CIK {cik}) is a {fund_type} managed by {adviser_name} (CRD {crd_number}).
Total assets: ${total_assets:,.0f}. Inception: {inception_date}. Currency: {currency}.

Share classes: {class_list}.

Top 10 holdings (as of {last_nport_date}):
{holdings_list — "issuer_name (sector): pct_of_nav%" para cada}

Sector allocation: {sector_breakdown}.
```

**id format:** `sec_fund_profile_{cik}`
**entity_type:** `"fund"`
**entity_id:** `cik`
**firm_crd:** `crd_number` (do adviser)

#### H. `_embed_sec_13f_summaries(db)` → source_type=`"sec_13f_summary"`

**Query:** Para cada `cik` distinto em `sec_13f_holdings` no report_date mais recente:
- Top 20 posições por market_value
- Concentração (top 5, top 10, HHI)
- Breakdown por sector

**Template:**

```
13F Portfolio of {firm_name} (CIK {cik}, CRD {crd_number}) as of {report_date}.
Total market value: ${total_value:,.0f}. Position count: {position_count}.

Top 20 holdings:
{holdings_list — "issuer_name: ${market_value:,.0f} ({weight:.1f}%)" para cada}

Concentration: Top 5 = {top5_pct:.1f}%, Top 10 = {top10_pct:.1f}%.

Sector breakdown:
{sector_list — "sector: {pct:.1f}% (${value:,.0f})" para cada}
```

**id format:** `sec_13f_summary_{cik}_{report_date}` (inclui data para versionamento)
**entity_type:** `"firm"`
**entity_id:** `cik`
**firm_crd:** `crd_number` (via sec_managers.cik JOIN)
**filing_date:** `report_date`

**Importante:** Manter apenas o mais recente. Na detecção de pendentes, verificar se já existe chunk para o `report_date` mais recente.

#### I. `_embed_sec_private_funds(db)` → source_type=`"sec_private_funds"`

**Query:** Agrupar `sec_manager_funds` por `crd_number`.

**Template:**

```
Private fund portfolio of {firm_name} (CRD {crd_number}):
{fund_count} private funds, total GAV: ${total_gav:,.0f}.

Funds:
{fund_list — "- {fund_name} ({fund_type}): GAV ${gav:,.0f}, {investor_count} investors" para cada}

Fund-of-funds: {fof_count}. Fund types: {type_breakdown}.
```

**id format:** `sec_private_funds_{crd_number}`
**entity_type:** `"firm"`
**entity_id:** `crd_number`
**firm_crd:** `crd_number`

#### J. `_embed_esma_fund_profiles(db)` → source_type=`"esma_fund_profile"`

**Substitui** o atual `_embed_esma_funds` (source_type=`"esma_fund"`).

**Query:** JOIN `esma_funds` com `esma_managers` para nome da gestora.

**Template:**

```
{fund_name} (ISIN {isin}) is a {fund_type} UCITS fund domiciled in {domicile}.
Managed by {manager_name} ({manager_country}).
Distributed in: {host_member_states_list}.
Yahoo ticker: {yahoo_ticker or 'not available'}.
```

**id format:** `esma_fund_profile_{isin}`
**entity_type:** `"fund"`
**entity_id:** `isin`

#### K. `_embed_esma_manager_profiles(db)` → source_type=`"esma_manager_profile"`

**Substitui** o atual `_embed_esma_managers` (source_type=`"esma_manager"`).

**Query:** JOIN `esma_managers` com COUNT de `esma_funds` para número real de fundos.

**Template:**

```
{company_name} (ESMA ID {esma_id}) is a {authorization_status} UCITS management company
based in {country}. LEI: {lei or 'not available'}.
Manages {actual_fund_count} UCITS funds across {domicile_count} domiciles.
{f"Cross-registered with US SEC as CRD {sec_crd_number}." if sec_crd_number else ""}
```

**id format:** `esma_manager_profile_{esma_id}`
**entity_type:** `"firm"`
**entity_id:** `esma_id`
**firm_crd:** `sec_crd_number` (se existir)

## Regras de implementação

### Padrão existente (seguir estritamente)

1. **Incremental:** LEFT JOIN com `wealth_vector_chunks` para detectar já-processados (`w.id IS NULL`)
2. **Batch embedding:** `async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)`
3. **Batch upsert:** `_batch_upsert(db, rows)` — `ON CONFLICT DO UPDATE` no `id`
4. **Per-source try/except:** Cada fonte tem seu próprio try/except com rollback (já implementado no loop principal)
5. **LIMIT 10000:** Cada query deve ter LIMIT para evitar OOM. Se houver mais, o worker incremental processa na próxima execução.
6. **Sem LLM:** Todo texto gerado por template/f-string. Sem chamada a OpenAI para gerar texto — apenas para embedding.
7. **DISTINCT ON:** Usar onde houver risco de duplicatas no batch (ex: brochures já teve esse bug).

### Migração dos source_types ESMA

Os novos `esma_fund_profile` e `esma_manager_profile` **substituem** `esma_fund` e `esma_manager`:
1. Remover as funções `_embed_esma_funds` e `_embed_esma_managers` antigas
2. Adicionar as novas `_embed_esma_fund_profiles` e `_embed_esma_manager_profiles`
3. Adicionar cleanup no início do worker para DELETE rows com source_type IN ('esma_fund', 'esma_manager') — one-time migration

### Registro no loop principal

```python
for source_name, coro_fn in [
    ("brochure", _embed_brochure_sections),           # A (existente)
    ("sec_manager_profile", _embed_sec_manager_profiles),  # F (novo)
    ("sec_fund_profile", _embed_sec_fund_profiles),        # G (novo)
    ("sec_13f_summary", _embed_sec_13f_summaries),         # H (novo)
    ("sec_private_funds", _embed_sec_private_funds),        # I (novo)
    ("esma_fund_profile", _embed_esma_fund_profiles),      # J (substitui B)
    ("esma_manager_profile", _embed_esma_manager_profiles), # K (substitui C)
    ("dd_chapters", _embed_dd_chapters),                    # D (existente)
    ("macro_reviews", _embed_macro_reviews),                # E (existente)
]:
```

### Search functions (pgvector_search_service.py)

As 3 funções de busca existentes usam `entity_type` e `firm_crd` como filtro — não usam `source_type` diretamente. Os novos chunks são automaticamente encontráveis pelas buscas existentes:

- `search_fund_firm_context_sync(sec_crd=X)` → encontra brochures + sec_manager_profile + sec_13f_summary + sec_private_funds (todos com firm_crd=X)
- `search_esma_funds_sync()` → precisa ser atualizado para filtrar `source_type = 'esma_fund_profile'` em vez de `'esma_fund'`
- `search_fund_analysis_sync()` → DD chapters e macro reviews (sem mudança)

Verificar `pgvector_search_service.py` e ajustar filtros se necessário.

### Estimativa de volume e custo

| Source | Rows | Tokens/chunk (est.) | Total tokens | Custo ($0.13/1M) |
|--------|------|---------------------|-------------|-------------------|
| sec_manager_profile | ~3,000 | ~200 | 600k | $0.08 |
| sec_fund_profile | ~400 (com N-PORT) | ~300 | 120k | $0.02 |
| sec_13f_summary | ~3,000 | ~500 | 1.5M | $0.20 |
| sec_private_funds | ~2,000 | ~300 | 600k | $0.08 |
| esma_fund_profile | ~10,400 | ~50 | 520k | $0.07 |
| esma_manager_profile | ~660 | ~60 | 40k | $0.01 |
| **Total novas fontes** | | | **~3.4M** | **~$0.45** |

Custo total com brochures (10k × 500 tok): **~$1.10 por execução completa**.

## Testes

Adicionar/atualizar `tests/test_wealth_embedding_worker.py`:
1. Cada nova função `_embed_*` deve ter um teste unitário que mocka `async_generate_embeddings` e verifica que o SQL roda sem erro e gera os rows esperados
2. Testar idempotência: segunda chamada com mesmos dados → 0 novos rows
3. Testar que `_embed_sec_fund_profiles` inclui holdings do N-PORT
4. Testar que `_embed_sec_13f_summaries` calcula concentração corretamente

## Arquivos a modificar

1. `backend/app/domains/wealth/workers/wealth_embedding_worker.py` — novas funções F-K, remover B e C antigos
2. `backend/app/domains/wealth/services/pgvector_search_service.py` — ajustar filtros de source_type se necessário
3. `backend/tests/test_wealth_embedding_worker.py` — novos testes

## Validação

Após deploy, verificar via SQL:

```sql
SELECT source_type, COUNT(*), AVG(length(content)) as avg_content_len
FROM wealth_vector_chunks
GROUP BY source_type
ORDER BY source_type;
```

Esperado:
- `brochure`: ~10k rows, avg ~2000 chars
- `sec_manager_profile`: ~3k rows, avg ~500 chars
- `sec_fund_profile`: ~400 rows, avg ~800 chars
- `sec_13f_summary`: ~3k rows, avg ~1200 chars
- `sec_private_funds`: ~2k rows, avg ~600 chars
- `esma_fund_profile`: ~10k rows, avg ~200 chars
- `esma_manager_profile`: ~660 rows, avg ~200 chars
- `esma_fund` e `esma_manager`: 0 rows (migrados/deletados)
