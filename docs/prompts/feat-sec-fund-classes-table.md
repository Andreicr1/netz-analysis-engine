# Prompt — `sec_fund_classes` table + class-level catalog entries

## Contexto

Cada fundo SEC registrado (mutual fund, ETF, closed-end) pode ter múltiplas **series** (estratégias) e cada series pode ter múltiplas **share classes** (Class A, Class B, Institutional, etc.). Cada share class tem:

- Ticker diferente
- ISIN diferente
- Fee structure diferente (expense ratio, loads)
- NAV e retornos diferentes (por causa dos fees)
- Potencialmente restrições de investimento diferentes

O modelo atual tem **1 row por CIK (registrant)** em `sec_registered_funds`, com apenas 1 `series_id` + 1 `class_id`. Isso é insuficiente para:
- Fee drag analysis (precisa dos fees da classe correta)
- Retornos precisos (cada classe tem NAV diferente)
- Decisão de investimento (se não pode investir na classe institucional, precisa da retail)

## Objetivo

1. Criar tabela `sec_fund_classes` — uma row por share class
2. Enriquecer o worker `nport_fund_discovery` para parsear TODAS as series/classes do filing header SGML
3. Atualizar o catalog query para retornar entries por class (não por fund)
4. Atualizar o schema `UnifiedFundItem` para incluir `series_id`, `series_name`, `class_id`, `class_name`

## Arquivos a modificar

### 1. Migration `0057_sec_fund_classes.py`

```
backend/app/core/db/migrations/versions/0057_sec_fund_classes.py
```

- `revision = "0057_sec_fund_classes"`
- `down_revision = "0056_wealth_content"`
- Tabela GLOBAL (sem organization_id, sem RLS) — mesma política que `sec_registered_funds`

Schema:
```sql
CREATE TABLE sec_fund_classes (
    cik          TEXT NOT NULL REFERENCES sec_registered_funds(cik) ON DELETE CASCADE,
    series_id    TEXT NOT NULL,
    series_name  TEXT,
    class_id     TEXT NOT NULL,
    class_name   TEXT,
    ticker       TEXT,

    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    data_fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (cik, series_id, class_id)
);

CREATE INDEX ix_sec_fund_classes_ticker ON sec_fund_classes (ticker) WHERE ticker IS NOT NULL;
CREATE INDEX ix_sec_fund_classes_cik ON sec_fund_classes (cik);
```

### 2. ORM Model em `backend/app/shared/models.py`

Adicionar `SecFundClass` model:
```python
class SecFundClass(Base):
    __tablename__ = "sec_fund_classes"

    cik: Mapped[str] = mapped_column(Text, ForeignKey("sec_registered_funds.cik", ondelete="CASCADE"), primary_key=True)
    series_id: Mapped[str] = mapped_column(Text, primary_key=True)
    class_id: Mapped[str] = mapped_column(Text, primary_key=True)
    series_name: Mapped[str | None] = mapped_column(Text)
    class_name: Mapped[str | None] = mapped_column(Text)
    ticker: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    data_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

### 3. Worker `backend/app/domains/wealth/workers/nport_fund_discovery.py`

A função `_parse_series_class_header` atualmente extrai apenas a PRIMEIRA series/class. Precisa extrair TODAS e retornar como lista.

O filing header SGML tem esta estrutura (exemplo real de AB BOND FUND, CIK 0000003794):
```
<SERIES-AND-CLASSES-CONTRACTS-DATA>
<EXISTING-SERIES-AND-CLASSES-CONTRACTS>
<SERIES>
<OWNER-CIK>0000003794
<SERIES-ID>S000027379
<SERIES-NAME>AB Municipal Bond Inflation Strategy
<CLASS-CONTRACT>
<CLASS-CONTRACT-ID>C000082624
<CLASS-CONTRACT-NAME>Class A
<CLASS-CONTRACT-TICKER-SYMBOL>AUNAX
</CLASS-CONTRACT>
<CLASS-CONTRACT>
<CLASS-CONTRACT-ID>C000082625
<CLASS-CONTRACT-NAME>Class C
<CLASS-CONTRACT-TICKER-SYMBOL>AUNCX
</CLASS-CONTRACT>
</SERIES>
</EXISTING-SERIES-AND-CLASSES-CONTRACTS>
</SERIES-AND-CLASSES-CONTRACTS-DATA>
```

Mudanças:

**a) Reescrever `_parse_series_class_header`** para extrair todas as series/classes:

```python
def _parse_series_class_header(sgml_text: str, result: dict) -> None:
    """Extract ALL series and classes from EDGAR filing header SGML.

    Populates result["fund_classes"] with list of dicts:
    [{"series_id": "S000027379", "series_name": "...", "class_id": "C000082624",
      "class_name": "Class A", "ticker": "AUNAX"}, ...]

    Also sets result["ticker"] to the first found ticker (for backward compat),
    and result["series_id"]/result["class_id"] to the first found.
    """
    import re

    classes: list[dict] = []

    # Parse SERIES blocks
    series_blocks = re.split(r'<SERIES>', sgml_text)
    for block in series_blocks[1:]:  # skip text before first <SERIES>
        sid_m = re.search(r'<SERIES-ID>\s*(\S+)', block)
        sname_m = re.search(r'<SERIES-NAME>\s*(.+?)(?:\n|<)', block)
        series_id = sid_m.group(1).strip() if sid_m else None
        series_name = sname_m.group(1).strip() if sname_m else None

        if not series_id:
            continue

        # Parse CLASS-CONTRACT blocks within this series
        class_blocks = re.split(r'<CLASS-CONTRACT>', block)
        for cb in class_blocks[1:]:
            cid_m = re.search(r'<CLASS-CONTRACT-ID>\s*(\S+)', cb)
            cname_m = re.search(r'<CLASS-CONTRACT-NAME>\s*(.+?)(?:\n|<)', cb)
            ticker_m = re.search(r'<CLASS-CONTRACT-TICKER-SYMBOL>\s*(\S+)', cb)

            if not cid_m:
                continue

            classes.append({
                "series_id": series_id,
                "series_name": series_name,
                "class_id": cid_m.group(1).strip(),
                "class_name": cname_m.group(1).strip() if cname_m else None,
                "ticker": ticker_m.group(1).strip().upper() if ticker_m else None,
            })

    result["fund_classes"] = classes

    # Backward compat: set first ticker/series/class on result
    if classes:
        first = classes[0]
        if not result.get("ticker") and first.get("ticker"):
            result["ticker"] = first["ticker"]
        if not result.get("series_id"):
            result["series_id"] = first["series_id"]
        if not result.get("class_id"):
            result["class_id"] = first["class_id"]
```

**b) Após o upsert em `sec_registered_funds`, fazer upsert das classes:**

No loop principal de `run_nport_fund_discovery`, após o batch upsert dos funds, adicionar:

```python
# Upsert fund classes
fund_classes = fund_data.get("fund_classes", [])
if fund_classes:
    for fc in fund_classes:
        await db.execute(
            text("""
                INSERT INTO sec_fund_classes
                    (cik, series_id, series_name, class_id, class_name, ticker, data_fetched_at)
                VALUES (:cik, :series_id, :series_name, :class_id, :class_name, :ticker, now())
                ON CONFLICT (cik, series_id, class_id) DO UPDATE SET
                    series_name = COALESCE(EXCLUDED.series_name, sec_fund_classes.series_name),
                    class_name = COALESCE(EXCLUDED.class_name, sec_fund_classes.class_name),
                    ticker = COALESCE(EXCLUDED.ticker, sec_fund_classes.ticker),
                    data_fetched_at = now()
            """),
            {"cik": cik, **fc},
        )
    await db.commit()
```

Nota: não pode ser dentro do batch upsert de funds porque precisa do CIK já existir (FK constraint).

### 4. Schema `backend/app/domains/wealth/schemas/catalog.py`

Adicionar campos ao `UnifiedFundItem`:
```python
class UnifiedFundItem(BaseModel):
    # ... campos existentes ...
    series_id: str | None = None
    series_name: str | None = None
    class_id: str | None = None
    class_name: str | None = None
```

### 5. Catalog query `backend/app/domains/wealth/queries/catalog_sql.py`

Na branch `_registered_us_branch()`, mudar o JOIN para usar `sec_fund_classes`:

**Antes**: 1 row por `sec_registered_funds` row (por CIK)
**Depois**: 1 row por `sec_fund_classes` row (por share class)

```sql
-- De:
SELECT ... FROM sec_registered_funds LEFT JOIN sec_managers ...

-- Para:
SELECT
    'registered_us' as universe,
    f.cik as external_id,
    COALESCE(c.class_name || ' - ' || f.fund_name, f.fund_name) as name,
    COALESCE(c.ticker, f.ticker) as ticker,
    ...
    c.series_id,
    c.series_name,
    c.class_id,
    c.class_name,
    m.firm_name as manager_name,
    m.crd_number as manager_id,
    ...
FROM sec_registered_funds f
LEFT JOIN sec_fund_classes c ON f.cik = c.cik
LEFT JOIN sec_managers m ON f.crd_number = m.crd_number
WHERE f.aum_below_threshold = FALSE
```

Fundos SEM classes na tabela (ETFs single-class, ou classes ainda não populadas) devem aparecer com `c.*` NULL — o LEFT JOIN garante isso.

Para as branches `_private_us_branch()` e `_ucits_eu_branch()`, adicionar `NULL::text as series_id, NULL::text as series_name, NULL::text as class_id, NULL::text as class_name` ao UNION ALL.

### 6. Facets (opcional)

Se o screener tiver facets, adicionar `series_name` e `class_name` como facets filtráveis. Ver `CatalogFacets` em `catalog.py` e `_build_facets_query` em `catalog_sql.py`.

## Regras

- Tabela `sec_fund_classes` é GLOBAL (sem `organization_id`, sem RLS) — igual a `sec_registered_funds`
- O worker `nport_fund_discovery` já tem rate limiting EDGAR (8 req/s) — não muda
- O filing header SGML já é fetched pelo worker — só precisa parsear mais campos
- Use `ON CONFLICT (cik, series_id, class_id) DO UPDATE` para idempotência
- `COALESCE` no ticker/names para não perder dados existentes
- Testes: adicionar teste para `_parse_series_class_header` com o SGML de exemplo acima
- Rodar `python scripts/generate_manifests.py` após mudar schemas (se o endpoint mudar)
- Rodar `make check` (excluir `test_instrument_ingestion.py` que tem falha pré-existente)

## Validação

Após implementar, rodar:
```bash
# Aplicar migration
cd backend && alembic upgrade head

# Rodar worker para popular classes
python -m app.workers.cli nport_fund_discovery

# Verificar via Tiger CLI
SELECT COUNT(*) FROM sec_fund_classes;
SELECT cik, series_name, class_name, ticker FROM sec_fund_classes LIMIT 20;

# Verificar catalog retorna classes
# GET /api/v1/screener/catalog?limit=10 deve ter series_id/class_id populados
```
