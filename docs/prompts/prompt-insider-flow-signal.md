# Prompt: Insider Flow Signal — Form 345 Ingestão e Scoring

## Contexto

O dataset Form 345 (Forms 3, 4, 5) do SEC contém transações de insiders
(Officers, Directors, 10% Owners) em ações de empresas públicas. Este dado
pode ser usado para criar um `insider_sentiment_score` por empresa/ticker,
que complementa o `flows_momentum_score` existente no scoring de fundos.

**Dataset disponível (Q4 2025):**
`C:\Users\Andrei\Desktop\EDGAR FILES\2025q4_form345\`

| Arquivo | Rows | Campos chave |
|---|---|---|
| `SUBMISSION.tsv` | 36,422 | `ISSUERCIK`, `ISSUERTRADINGSYMBOL`, `DOCUMENT_TYPE` (3/4/5), `PERIOD_OF_REPORT` |
| `NONDERIV_TRANS.tsv` | 59,679 | `TRANS_CODE`, `TRANS_SHARES`, `TRANS_PRICEPERSHARE`, `TRANS_ACQUIRED_DISP_CD` (A/D), `TRANS_DATE` |
| `REPORTINGOWNER.tsv` | 39,603 | `RPTOWNERCIK`, `RPTOWNER_RELATIONSHIP` (Officer/Director/10% Owner), `RPTOWNER_TITLE` |
| `NONDERIV_HOLDING.tsv` | 17,522 | Form 3 holdings snapshot |
| `DERIV_TRANS.tsv` | — | Opções e derivativos (fora do escopo desta sessão) |

**Sinal relevante:**
- `TRANS_CODE = 'P'` — compra em mercado aberto (sinal bullish, informativo)
- `TRANS_CODE = 'S'` — venda em mercado aberto (sinal bearish, informativo)
- Excluir: `'A'` (award/grant), `'F'` (tax withholding), `'M'` (option exercise),
  `'G'` (gift), `'J'` (other) — não informativos sobre convicção do insider

**Filtro de relação:**
- Incluir: `Officer`, `Director` — sinais de convicção real
- Excluir: `10% Owner` (fundos/SPACs que negociam por razões de portfólio)

**Literatura:** Insider purchases têm maior poder preditivo em janela de 6-12 meses
(Seyhun 1986, Jeng et al. 2003). Compras são mais informativas que vendas
(vendas podem ser por diversificação/liquidez pessoal).

---

## Mandatory First Steps

1. Ler o scoring service atual:
   `backend/quant_engine/scoring_service.py`
   — confirmar assinatura real de `compute_fund_score()` antes de qualquer edição

2. Ler o worker inventory para encontrar o lock ID mais alto em uso:
   `docs/reference/database-inventory-reference.md` — seção "6. Worker Inventory"
   — o próximo lock ID deve ser `900_023` ou maior (verificar)

3. Ler padrão de migration existente:
   `app/core/db/migrations/versions/0066_fund_class_xbrl_fees.py`

4. Confirmar migration head atual:
   `cd backend && alembic -c alembic.ini current`

5. Ler 3 linhas de cada arquivo TSV do Form 345 para confirmar headers reais
   antes de escrever qualquer código de parse

---

## Fase 1 — Migration 0067: Tabela `sec_insider_transactions`

### Schema

```sql
CREATE TABLE sec_insider_transactions (
    -- Identifiers
    accession_number        VARCHAR NOT NULL,
    trans_sk                BIGINT NOT NULL,        -- NONDERIV_TRANS_SK (PK natural)

    -- Issuer (empresa cujas ações foram transacionadas)
    issuer_cik              VARCHAR NOT NULL,        -- SUBMISSION.ISSUERCIK
    issuer_ticker           VARCHAR,                 -- SUBMISSION.ISSUERTRADINGSYMBOL

    -- Reporting owner (insider)
    owner_cik               VARCHAR NOT NULL,        -- REPORTINGOWNER.RPTOWNERCIK
    owner_name              VARCHAR,                 -- REPORTINGOWNER.RPTOWNERNAME
    owner_relationship      VARCHAR,                 -- Officer / Director / 10% Owner
    owner_title             VARCHAR,                 -- CEO / CFO / General Counsel etc.

    -- Transaction
    trans_date              DATE NOT NULL,
    period_of_report        DATE,
    document_type           VARCHAR(1),              -- '3', '4', '5'
    trans_code              VARCHAR(2) NOT NULL,     -- P / S / A / F / M etc.
    trans_acquired_disp     VARCHAR(1),              -- A (acquired) / D (disposed)
    trans_shares            NUMERIC(20, 4),
    trans_price_per_share   NUMERIC(12, 4),
    trans_value             NUMERIC(20, 2)           -- computed: shares * price

        GENERATED ALWAYS AS (trans_shares * trans_price_per_share) STORED,

    shares_owned_after      NUMERIC(20, 4),         -- SHRS_OWND_FOLWNG_TRANS

    PRIMARY KEY (accession_number, trans_sk)
);

CREATE INDEX idx_insider_trans_issuer_cik    ON sec_insider_transactions(issuer_cik);
CREATE INDEX idx_insider_trans_issuer_ticker ON sec_insider_transactions(issuer_ticker)
    WHERE issuer_ticker IS NOT NULL;
CREATE INDEX idx_insider_trans_date          ON sec_insider_transactions(trans_date);
CREATE INDEX idx_insider_trans_code          ON sec_insider_transactions(trans_code);
CREATE INDEX idx_insider_trans_relationship  ON sec_insider_transactions(owner_relationship);
```

**Tabela global:** sem `organization_id`, sem RLS.
**Não é hypertable** — volume não justifica (59k rows/quarter). Tabela regular com índices.

### Derived aggregate view

```sql
CREATE MATERIALIZED VIEW sec_insider_sentiment AS
SELECT
    issuer_cik,
    issuer_ticker,
    date_trunc('quarter', trans_date)::date AS quarter,
    COUNT(*) FILTER (WHERE trans_code = 'P' AND owner_relationship != '10% Owner') AS buy_count,
    COUNT(*) FILTER (WHERE trans_code = 'S' AND owner_relationship != '10% Owner') AS sell_count,
    SUM(trans_value) FILTER (WHERE trans_code = 'P' AND owner_relationship != '10% Owner') AS buy_value,
    SUM(trans_value) FILTER (WHERE trans_code = 'S' AND owner_relationship != '10% Owner') AS sell_value,
    COUNT(DISTINCT owner_cik) FILTER (WHERE trans_code = 'P') AS unique_buyers,
    COUNT(DISTINCT owner_cik) FILTER (WHERE trans_code = 'S') AS unique_sellers
FROM sec_insider_transactions
WHERE trans_code IN ('P', 'S')
GROUP BY issuer_cik, issuer_ticker, date_trunc('quarter', trans_date)::date;

CREATE UNIQUE INDEX ON sec_insider_sentiment(issuer_cik, quarter);
CREATE INDEX ON sec_insider_sentiment(issuer_ticker) WHERE issuer_ticker IS NOT NULL;
```

---

## Fase 2 — ORM Model

Adicionar em `app/shared/models.py` após os modelos SEC existentes:

```python
class SecInsiderTransaction(Base):
    __tablename__ = "sec_insider_transactions"
    __table_args__ = (
        PrimaryKeyConstraint("accession_number", "trans_sk"),
        {"comment": "Form 3/4/5 insider transactions. Global table, no RLS."}
    )

    accession_number      = Column(String, nullable=False)
    trans_sk              = Column(BigInteger, nullable=False)
    issuer_cik            = Column(String, nullable=False)
    issuer_ticker         = Column(String)
    owner_cik             = Column(String, nullable=False)
    owner_name            = Column(String)
    owner_relationship    = Column(String)
    owner_title           = Column(String)
    trans_date            = Column(Date, nullable=False)
    period_of_report      = Column(Date)
    document_type         = Column(String(1))
    trans_code            = Column(String(2), nullable=False)
    trans_acquired_disp   = Column(String(1))
    trans_shares          = Column(Numeric(20, 4))
    trans_price_per_share = Column(Numeric(12, 4))
    trans_value           = Column(Numeric(20, 2))  # GENERATED ALWAYS — não incluir no INSERT
    shares_owned_after    = Column(Numeric(20, 4))
```

**Nota:** `trans_value` é coluna gerada (GENERATED ALWAYS AS STORED) — não incluir
em INSERT statements; ler normalmente em SELECT.

---

## Fase 3 — Seed Script

Criar `backend/scripts/seed_insider_transactions.py`.

### Lógica

```python
"""
Seed Form 345 insider transactions from EDGAR bulk TSV files.

Usage:
    python seed_insider_transactions.py --form345-dir "C:/Users/Andrei/Desktop/EDGAR FILES/2025q4_form345"
    python seed_insider_transactions.py --form345-dir "..." --dry-run
"""
```

1. Ler `SUBMISSION.tsv` → dict `accession → {issuer_cik, issuer_ticker, document_type, period_of_report}`
2. Ler `REPORTINGOWNER.tsv` → dict `accession → list[{owner_cik, owner_name, relationship, title}]`
   - Múltiplos owners por accession são possíveis — usar o primeiro (ou o com relationship mais relevante)
   - Prioridade: `Officer > Director > 10% Owner`
3. Ler `NONDERIV_TRANS.tsv` → iterar rows
4. Para cada row em NONDERIV_TRANS:
   - JOIN com SUBMISSION via `ACCESSION_NUMBER`
   - JOIN com REPORTINGOWNER via `ACCESSION_NUMBER`
   - Filtrar: só `TRANS_CODE IN ('P', 'S', 'A', 'F', 'M', 'G', 'J')` — gravar todos para análise futura
   - Parsear tipos: shares → `Decimal`, price → `Decimal`, date → `date`
   - Upsert via `ON CONFLICT (accession_number, trans_sk) DO UPDATE`
5. Batch upsert de 1,000 rows por vez via asyncpg

### Tratamento de dados

```python
INFORMATIVE_CODES = {'P', 'S'}  # mercado aberto — sinais
NON_INFORMATIVE_CODES = {'A', 'F', 'M', 'G', 'J'}  # ruído — gravar mas não usar no score

RELATIONSHIP_PRIORITY = {
    'Officer': 3,
    'Director': 2,
    '10% Owner': 1,
}

def parse_decimal(val: str) -> Decimal | None:
    if not val or val.strip() == '':
        return None
    try:
        return Decimal(val.strip())
    except InvalidOperation:
        return None

def parse_date_345(val: str) -> date | None:
    # Form 345 usa formato DD-MON-YYYY (ex: "29-OCT-2025")
    # ou YYYY-MM-DD dependendo do campo
    if not val or val.strip() == '':
        return None
    for fmt in ('%d-%b-%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(val.strip(), fmt).date()
        except ValueError:
            continue
    return None
```

### Output esperado

```
SUBMISSION: 36,422 rows carregados
REPORTINGOWNER: 39,603 rows carregados
NONDERIV_TRANS: 59,676 rows processados
  - P (open market purchases): ~8,000
  - S (open market sales): ~15,000
  - A/F/M/G/J (non-informative): ~36,000
Inserted/updated: 59,676 rows em sec_insider_transactions
Materialize sec_insider_sentiment: REFRESH MATERIALIZED VIEW
```

---

## Fase 4 — Worker de Ingestão

Criar `backend/app/domains/wealth/workers/form345_ingestion.py`.

### Padrão (seguir exatamente outros workers)

```python
LOCK_ID = 900_023  # verificar o próximo disponível antes de usar

async def run_form345_ingestion(db: AsyncSession) -> None:
    """
    Ingest Form 345 insider transactions from SEC EDGAR bulk quarterly files.
    Downloads latest quarter's Form 345 data and upserts into sec_insider_transactions.
    """
    acquired = await db.scalar(
        text("SELECT pg_try_advisory_lock(:lock_id)"),
        {"lock_id": LOCK_ID}
    )
    if not acquired:
        logger.info("form345_ingestion: lock not acquired, skipping")
        return

    try:
        await _ingest_form345(db)
        await db.execute(
            text("REFRESH MATERIALIZED VIEW CONCURRENTLY sec_insider_sentiment")
        )
        await db.commit()
    finally:
        await db.execute(
            text("SELECT pg_advisory_unlock(:lock_id)"),
            {"lock_id": LOCK_ID}
        )
```

**Fonte de dados:** SEC EDGAR bulk download URL pattern:
`https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/form.idx`

**Frequência:** Trimestral (dados Form 345 são publicados por quarter).

**Registrar em `backend/app/workers.py`** seguindo o padrão de outros workers.

---

## Fase 5 — insider_sentiment_score no Scoring Service

### 5A. Query helper

Criar função em `backend/app/domains/wealth/services/insider_queries.py`:

```python
def get_insider_sentiment_score(
    db: Session,
    *,
    issuer_cik: str | None = None,
    issuer_ticker: str | None = None,
    lookback_quarters: int = 4,
) -> float:
    """
    Returns insider_sentiment_score in [0, 100].
    
    Score > 50: net buying pressure (bullish)
    Score = 50: neutral
    Score < 50: net selling pressure (bearish)
    
    Uses only Officer + Director transactions (excludes 10% Owner).
    Uses only informative codes: P (purchase) and S (sale).
    """
```

**Fórmula:**
```python
# Últimos N quarters de dados
rows = query sec_insider_sentiment WHERE issuer_cik = ? AND quarter >= cutoff

buy_value  = sum(row.buy_value or 0 for row in rows)
sell_value = sum(row.sell_value or 0 for row in rows)
total      = buy_value + sell_value

if total == 0:
    return 50.0  # neutral — sem dados

# Net buying ratio → [0, 1] → escalar para [0, 100]
net_buy_ratio = buy_value / total  # 1.0 = só compras, 0.0 = só vendas
score = net_buy_ratio * 100

# Decay: penalizar se dados são antigos (> 2 quarters sem transação)
# (opcional — implementar se necessário)

return round(score, 2)
```

### 5B. Integrar em compute_fund_score()

**Arquivo:** `backend/quant_engine/scoring_service.py`

**Mandatory first step:** ler a assinatura REAL atual antes de editar.
Não assumir nenhum parâmetro — copiar a assinatura existente e apenas adicionar
`insider_sentiment_score: float | None = None`.

```python
def compute_fund_score(
    metrics: RiskMetrics,
    # ... parâmetros existentes, não alterar ...
    expense_ratio_pct: float | None = None,      # Phase 5B do plano anterior
    insider_sentiment_score: float | None = None, # NOVO
) -> tuple[float, dict[str, float]]:
```

Se `insider_sentiment_score` não é None e config tem weight `"insider_sentiment"` > 0:
```python
if insider_sentiment_score is not None and weights.get("insider_sentiment", 0) > 0:
    components["insider_sentiment"] = insider_sentiment_score * weights["insider_sentiment"]
```

**Backward-compatible:** default None = comportamento inalterado para todos os callers existentes.

### 5C. Wire no DD Report (opcional, Phase 5 do plano maior)

Em `dd_report_engine.py`, se `attrs.get("sec_cik")` existe:
```python
insider_score = get_insider_sentiment_score(
    db,
    issuer_cik=attrs.get("sec_cik"),
    issuer_ticker=attrs.get("ticker"),
    lookback_quarters=4
)
evidence_pack.insider_sentiment_score = insider_score
```

Adicionar ao capítulo `investment_strategy`:
```
Insider Activity (last 4 quarters): {insider_score:.0f}/100
({buy_count} buys totaling ${buy_value:.1f}M vs {sell_count} sells)
```

---

## Fase 6 — Conexão com N-PORT (Fund-level signal)

Para fundos com holdings N-PORT, o `insider_sentiment_score` pode ser
agregado ao nível do fundo ponderando pelos holdings.

**Match direto — sem CUSIP:** `sec_insider_transactions` já armazena
`issuer_cik` (de `SUBMISSION.ISSUERCIK`) e `issuer_ticker` (de
`SUBMISSION.ISSUERTRADINGSYMBOL`). N-PORT holdings têm `issuer_name` e
`cusip` mas não `issuer_cik` — o match se faz via `issuer_ticker`, que
está diretamente disponível no Form 345. Não há dependência de
`sec_cusip_ticker_map`.

**Arquivo:** `backend/vertical_engines/wealth/dd_report/sec_injection.py`
→ função `gather_fund_enrichment()` (Phase 1A do plano principal)

```python
# Se fundo tem N-PORT holdings, computar score agregado ponderado por pct_of_nav
if nport_holdings:
    insider_scores = []
    for holding in nport_holdings[:20]:  # top 20 posições por pct_of_nav
        issuer_cik = None

        ticker = holding.get("ticker")
        cusip  = holding.get("cusip")

        if ticker:
            # Equity holding — match direto via issuer_ticker
            score = get_insider_sentiment_score(db, issuer_ticker=ticker, lookback_quarters=4)
        elif cusip and cusip_map:
            # Corporate bond holding — resolver CUSIP → issuer_cik via sec_cusip_ticker_map
            # cusip_map = {cusip: issuer_cik} pré-carregado; vazio se tabela não populada
            issuer_cik = cusip_map.get(cusip[:6])  # CUSIP prefix (6 chars) identifica issuer
            if issuer_cik:
                score = get_insider_sentiment_score(db, issuer_cik=issuer_cik, lookback_quarters=4)
            else:
                continue  # municipal/GSE/treasury ou CUSIP não resolvido — pular
        else:
            continue  # sem ticker e sem CUSIP — pular

        if score == 50.0:
            continue  # sem dados para este issuer — não contaminar média

        weight = holding.get("pct_of_nav", 0) / 100
        insider_scores.append((score, weight))

    if insider_scores:
        total_weight = sum(w for _, w in insider_scores)
        if total_weight > 0:
            portfolio_insider_score = sum(s * w for s, w in insider_scores) / total_weight
            enrichment["portfolio_insider_sentiment"] = round(portfolio_insider_score, 1)
```

**`cusip_map` pre-loading:** carregar uma vez por chamada de `gather_fund_enrichment()`:
```python
cusip_map = {}
if sec_universe in ("registered_us",):
    rows = db.execute(text("SELECT cusip, issuer_cik FROM sec_cusip_ticker_map LIMIT 500000")).all()
    cusip_map = {r.cusip[:6]: r.issuer_cik for r in rows}
# Se tabela vazia (0 rows), cusip_map = {} → apenas equity holdings são usados (degradação graciosa)
```

**Nota sobre resolução de holdings:**

- **Equity holdings** (ticker presente): match direto via `issuer_ticker`. Sem dependência adicional.
- **Corporate bond holdings** (CUSIP presente, sem ticker): o issuer do bond é uma empresa
  pública cujos executivos fazem Form 345. O sinal é válido e relevante — insider sentiment
  do issuer é um sinal de crédito indireto. Requer CUSIP → issuer CIK/ticker via
  `sec_cusip_ticker_map` (atualmente 0 rows — tabela a popular).
- **Municipal bonds, GSEs, Gov Agency, US Treasury**: emissores são entidades governamentais
  sem Form 345. Pular silenciosamente é correto — fora do escopo por definição.

**Implicação:** `sec_cusip_ticker_map` é necessário para fixed income funds com holdings
corporativos. Sem ele, funds como "Corporate Bond", "High Yield" e "Credit" ficam sem
cobertura no score de portfólio (Fase 6). A Fase 6 deve verificar se a tabela está
populada antes de tentar o match por CUSIP — se não estiver, degradar graciosamente
(usar apenas equity holdings que têm ticker).

---

## Validação

```bash
# Migration aplicada
cd backend && alembic -c alembic.ini current

# Contagens pós-seed
psql $DATABASE_URL_SYNC -c "
SELECT
    trans_code,
    owner_relationship,
    count(*) as n,
    sum(trans_value) as total_value
FROM sec_insider_transactions
GROUP BY trans_code, owner_relationship
ORDER BY trans_code, owner_relationship;
"

# Sanity check do score — empresa com insiders comprando
psql $DATABASE_URL_SYNC -c "
SELECT issuer_ticker, buy_count, sell_count,
    round(buy_value::numeric, 0) as buy_value,
    round(sell_value::numeric, 0) as sell_value
FROM sec_insider_sentiment
WHERE buy_count > 0
ORDER BY buy_value DESC
LIMIT 10;
"

# Materialized view populada
psql $DATABASE_URL_SYNC -c "SELECT count(*) FROM sec_insider_sentiment;";

# Testes
cd backend && make check
```

**Sanity checks esperados:**
- ~8,000 transações com `trans_code = 'P'` (compras)
- ~15,000 transações com `trans_code = 'S'` (vendas — normal: executives diversificam)
- Empresas com muito buy: tipicamente small/mid-cap em recuperação
- Score de empresa com 100% compras = 100.0
- Score de empresa sem transações = 50.0 (neutral)

---

## Atualizar CLAUDE.md após execução

- Migration head: `0067_insider_transactions`
- Nova tabela global: `sec_insider_transactions`
- Nova materialized view: `sec_insider_sentiment`
- Novo worker: `form345_ingestion` (lock ID: verificar)
- Dataset fonte: Form 345 bulk quarterly, SEC EDGAR
- Novo parâmetro em `compute_fund_score()`: `insider_sentiment_score`

---

## What NOT to Do

- Não criar hypertable — volume trimestral (~60k rows) não justifica
- Não incluir `10% Owner` no score — negocia por razões de portfólio, não convicção
- Não incluir `TRANS_CODE` não-informativos (A/F/M/G/J) no cálculo do score
  (gravar na tabela para análise, excluir do score e da materialized view)
- Não modificar `lipper_score` — não existe no modelo
- Não hardcodar paths do dataset EDGAR — receber via argumento CLI `--form345-dir`
- Não usar `sec_cusip_ticker_map` para equity holdings — match é direto via `issuer_ticker`.
  Para corporate bond holdings, `sec_cusip_ticker_map` É necessário (CUSIP → issuer CIK).
  Verificar se a tabela está populada antes de usar; degradar graciosamente se vazia
- Não usar `lazy="select"` no ORM — seguir padrão `lazy="raise"`
- Não alterar outros parâmetros de `compute_fund_score()` além de adicionar
  `insider_sentiment_score` — ler a assinatura real antes de editar
- Não executar DDL dentro de transaction explícita
- `trans_value` é coluna gerada (GENERATED ALWAYS AS STORED) — não incluir em INSERT
