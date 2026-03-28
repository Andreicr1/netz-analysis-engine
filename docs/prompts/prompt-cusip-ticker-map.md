# Prompt: Popular sec_cusip_ticker_map via OpenFIGI

## Contexto

`sec_cusip_ticker_map` existe no schema mas tem 0 rows. Esta tabela é necessária
para resolver CUSIP → issuer CIK/ticker em holdings N-PORT de renda fixa corporativa,
habilitando o `insider_sentiment_score` para fundos de Fixed Income e High Yield
(Fase 6 do prompt-insider-flow-signal.md).

**Fonte de CUSIPs:** `sec_nport_holdings` — corporate bond holdings (sector = 'CORP').
**API de resolução:** OpenFIGI (https://api.openfigi.com/v3/mapping)
- Gratuita com API key: 250 requests/minuto, 100 CUSIPs por request
- Com API key: header `X-OPENFIGI-APIKEY`
- Sem API key: 25 requests/minuto (fallback)

**API key:** variável de ambiente `OPENFIGI_API_KEY`

---

## Mandatory First Steps

1. Verificar schema atual da tabela:
   ```sql
   SELECT column_name, data_type
   FROM information_schema.columns
   WHERE table_name = 'sec_cusip_ticker_map'
   ORDER BY ordinal_position;
   ```

2. Contar CUSIPs únicos em N-PORT por sector:
   ```sql
   SELECT sector, count(distinct cusip) as unique_cusips
   FROM sec_nport_holdings
   WHERE cusip IS NOT NULL
   GROUP BY sector
   ORDER BY unique_cusips DESC;
   ```
   Foco: apenas `sector = 'CORP'` — municipals/GSEs/treasury não têm Form 345.

3. Verificar se há índice em `sec_cusip_ticker_map`:
   ```sql
   SELECT indexname, indexdef
   FROM pg_indexes
   WHERE tablename = 'sec_cusip_ticker_map';
   ```

---

## Fase 1 — Verificar schema; adicionar colunas se necessário

O schema atual de `sec_cusip_ticker_map` pode ter apenas `cusip` e `ticker`.
Precisamos também de `issuer_cik` para o match com Form 345.

Se `issuer_cik` não existir:
```sql
ALTER TABLE sec_cusip_ticker_map
    ADD COLUMN IF NOT EXISTS issuer_cik    VARCHAR,
    ADD COLUMN IF NOT EXISTS issuer_name   VARCHAR,
    ADD COLUMN IF NOT EXISTS security_type VARCHAR,   -- 'Common Stock', 'ADR', etc.
    ADD COLUMN IF NOT EXISTS exchange_code VARCHAR,   -- 'US', 'UN', etc.
    ADD COLUMN IF NOT EXISTS figi          VARCHAR,   -- OpenFIGI identifier
    ADD COLUMN IF NOT EXISTS composite_figi VARCHAR,  -- composite FIGI (preferred)
    ADD COLUMN IF NOT EXISTS resolved_at   TIMESTAMPTZ DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_cusip_map_cusip6
    ON sec_cusip_ticker_map(LEFT(cusip, 6));  -- prefix para match com bond holdings
CREATE INDEX IF NOT EXISTS idx_cusip_map_issuer_cik
    ON sec_cusip_ticker_map(issuer_cik) WHERE issuer_cik IS NOT NULL;
```

Se a tabela não tiver PK, adicionar:
```sql
ALTER TABLE sec_cusip_ticker_map
    ADD PRIMARY KEY (cusip);
```

Não criar migration separada se a tabela já existe — usar ALTER TABLE diretamente
no script de seed. Se precisar de migration, usar 0068.

---

## Fase 2 — Seed Script

Criar `backend/scripts/seed_cusip_ticker_map.py`.

### Interface CLI

```bash
python seed_cusip_ticker_map.py
    [--sector CORP]          # sector a processar (default: CORP)
    [--batch-size 100]       # CUSIPs por request OpenFIGI (max: 100)
    [--rate-limit 250]       # requests/minuto (default: 250 com API key)
    [--dry-run]              # não inserir, apenas logar
    [--resume]               # pular CUSIPs já resolvidos na tabela
```

### Lógica principal

```python
import asyncio
import aiohttp
import os
from asyncio import Semaphore

OPENFIGI_API_KEY = os.environ["OPENFIGI_API_KEY"]  # obrigatório
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
BATCH_SIZE = 100  # max por request
RATE_LIMIT = 250  # requests/minuto com API key → ~4.2 req/s
```

**Passo 1:** Buscar CUSIPs únicos do N-PORT:
```python
query = """
    SELECT DISTINCT cusip
    FROM sec_nport_holdings
    WHERE cusip IS NOT NULL
      AND sector = :sector
      AND LENGTH(cusip) = 9
"""
# Se --resume: adicionar AND cusip NOT IN (SELECT cusip FROM sec_cusip_ticker_map)
```

**Passo 2:** Chunkar em batches de 100 e chamar OpenFIGI:
```python
async def resolve_batch(session, cusips: list[str], semaphore: Semaphore) -> list[dict]:
    async with semaphore:
        payload = [{"idType": "ID_CUSIP", "idValue": cusip} for cusip in cusips]
        headers = {
            "Content-Type": "application/json",
            "X-OPENFIGI-APIKEY": OPENFIGI_API_KEY,
        }
        async with session.post(OPENFIGI_URL, json=payload, headers=headers) as resp:
            if resp.status == 429:
                await asyncio.sleep(60)  # rate limit — esperar 1 minuto
                return await resolve_batch(session, cusips, semaphore)
            resp.raise_for_status()
            return await resp.json()
```

**Passo 3:** Parsear response do OpenFIGI:
```python
def parse_figi_response(cusips: list[str], results: list[dict]) -> list[dict]:
    """
    OpenFIGI retorna uma lista com um item por CUSIP.
    Cada item tem 'data' (lista de matches) ou 'error'.
    Selecionar o match de equity mais relevante:
    - Preferir exchangeCode 'US' ou 'UN' (NYSE/NASDAQ)
    - securityType 'Common Stock' > 'ADR' > outros
    - Ignorar options, warrants, preferreds
    """
    rows = []
    for cusip, result in zip(cusips, results):
        if "error" in result or not result.get("data"):
            continue  # CUSIP não resolvido — pular
        
        candidates = result["data"]
        
        # Filtrar equity apenas
        equity = [
            c for c in candidates
            if c.get("securityType") in ("Common Stock", "ADR", "ETP")
        ]
        if not equity:
            continue
        
        # Priorizar US exchange
        us = [c for c in equity if c.get("exchCode") in ("US", "UN", "UA", "UW")]
        best = us[0] if us else equity[0]
        
        rows.append({
            "cusip": cusip,
            "ticker": best.get("ticker"),
            "issuer_name": best.get("name"),
            "security_type": best.get("securityType"),
            "exchange_code": best.get("exchCode"),
            "figi": best.get("figi"),
            "composite_figi": best.get("compositeFIGI"),
        })
    return rows
```

**Passo 4:** `issuer_cik` — OpenFIGI não retorna CIK diretamente.
Resolver via `sec_managers` ou `instruments_global` após inserção:
```python
# Pós-insert: tentar resolver issuer_cik via ticker match em sec_managers
UPDATE sec_cusip_ticker_map m
SET issuer_cik = (
    SELECT cik FROM sec_managers
    WHERE firm_name ILIKE m.issuer_name
    LIMIT 1
)
WHERE issuer_cik IS NULL AND issuer_name IS NOT NULL;
```
**Nota:** match por nome é fuzzy — aceitar cobertura parcial. O `issuer_cik`
é secundário; `ticker` é suficiente para `get_insider_sentiment_score()` via
`issuer_ticker`.

**Passo 5:** Upsert em batch:
```python
INSERT INTO sec_cusip_ticker_map
    (cusip, ticker, issuer_name, security_type, exchange_code, figi, composite_figi, resolved_at)
VALUES ...
ON CONFLICT (cusip) DO UPDATE SET
    ticker          = EXCLUDED.ticker,
    issuer_name     = EXCLUDED.issuer_name,
    security_type   = EXCLUDED.security_type,
    exchange_code   = EXCLUDED.exchange_code,
    figi            = EXCLUDED.figi,
    composite_figi  = EXCLUDED.composite_figi,
    resolved_at     = NOW();
```

---

## Validação

```bash
# Rodar o script
cd backend
OPENFIGI_API_KEY=your_key_here python scripts/seed_cusip_ticker_map.py \
    --sector CORP \
    --resume

# Verificar cobertura
psql $DATABASE_URL_SYNC -c "
SELECT
    count(*) AS total_resolved,
    count(ticker) AS with_ticker,
    count(issuer_cik) AS with_cik,
    round(count(ticker)::numeric / count(*) * 100, 1) AS pct_ticker_coverage
FROM sec_cusip_ticker_map;
"

# Cruzar com N-PORT para ver cobertura efetiva
psql $DATABASE_URL_SYNC -c "
SELECT
    count(distinct h.cusip) AS total_corp_cusips,
    count(distinct m.cusip) AS resolved_cusips,
    round(count(distinct m.cusip)::numeric /
          count(distinct h.cusip) * 100, 1) AS coverage_pct
FROM sec_nport_holdings h
LEFT JOIN sec_cusip_ticker_map m ON h.cusip = m.cusip
WHERE h.sector = 'CORP' AND h.cusip IS NOT NULL;
"

# Top 10 issuers resolvidos por market value no N-PORT
psql $DATABASE_URL_SYNC -c "
SELECT m.issuer_name, m.ticker, count(*) as positions,
    sum(h.market_value) as total_market_value
FROM sec_nport_holdings h
JOIN sec_cusip_ticker_map m ON h.cusip = m.cusip
WHERE h.sector = 'CORP'
GROUP BY m.issuer_name, m.ticker
ORDER BY total_market_value DESC
LIMIT 10;
"
```

**Resultados esperados:**
- ~26,000 CUSIPs CORP únicos no N-PORT
- Cobertura OpenFIGI: ~70-80% para corporate bonds (alguns são privados ou
  emissões antigas sem FIGI)
- Top issuers: Apple, Microsoft, JPMorgan, BofA — empresas com bonds amplamente
  mantidos em fundos e com insiders ativos em Form 345

---

## What NOT to Do

- Não chamar OpenFIGI sem `X-OPENFIGI-APIKEY` header em produção —
  rate limit cai para 25 req/min e o job vai levar horas
- Não tentar resolver municipals (MUN), GSEs (USGSE), treasuries (UST) —
  não têm Form 345; filtrar por `sector = 'CORP'` no N-PORT
- Não fazer requests síncronos — usar `aiohttp` com `asyncio.Semaphore`
  para respeitar rate limit sem bloquear
- Não ignorar HTTP 429 — implementar retry com backoff de 60s
- Não criar migration separada se a tabela já existe — ALTER TABLE direto
- Não assumir que `issuer_cik` vai ter cobertura alta — é best-effort via
  nome; `ticker` é a chave principal de uso
