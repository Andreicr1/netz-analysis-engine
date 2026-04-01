# Prompt G — P0 Estabilização: Global Instruments Refactor (#53-#55)

## Contexto

Sessão 2026-03-29 realizou o Global Instruments Refactor (migrations 0068-0069) +
Universe Sync + N-PORT bulk + RR1 prospectus. 30+ arquivos alterados.

Este prompt valida que o refactor não quebrou nada e sincroniza o Alembic.

**DEVE rodar antes do próximo deploy Railway.**

Backend local: D:\Projetos\netz-analysis-engine\backend
Python: D:\Projetos\netz-analysis-engine\backend\.venv\Scripts\python.exe
DB: usar DIRECT_DATABASE_URL do .env (porta 5432)

## Pré-leitura obrigatória

Antes de qualquer código, leia:
- D:\Projetos\netz-analysis-engine\docs\reference\deploy-checklist.md  (seções 0.2, 0.3, 3.3)
- D:\Projetos\netz-analysis-engine\backend\app\domains\wealth\models\instrument.py
- D:\Projetos\netz-analysis-engine\backend\app\domains\wealth\models\instrument_org.py
- D:\Projetos\netz-analysis-engine\backend\app\core\db\migrations\versions\  (últimas 5 migrations)

## O que NÃO fazer

- Não criar migrations sem verificar o estado atual do Alembic
- Não rodar `alembic downgrade` — só `upgrade head`
- Não alterar modelos ORM sem rodar `make check` depois
- Não fazer `alembic revision --autogenerate` sem checar drift primeiro
- Não assumir que testes passam — rodar explicitamente

---

## Etapa 1 — Verificar estado do DB (SQL direto)

```python
import asyncio, asyncpg, os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path("D:/Projetos/netz-analysis-engine/backend/.env"))

DB = os.environ["DIRECT_DATABASE_URL"].replace(
    "postgresql+asyncpg://", "postgresql://"
).replace("postgresql+psycopg://", "postgresql://")

async def check_db():
    conn = await asyncpg.connect(DB)

    print("=== #53 — Global Instruments Refactor ===")

    # instruments_universe deve ser global (sem RLS)
    r = await conn.fetchrow("""
        SELECT rowsecurity FROM pg_tables
        WHERE tablename = 'instruments_universe' AND schemaname = 'public'
    """)
    iu_rls = r["rowsecurity"] if r else None
    print(f"instruments_universe RLS: {iu_rls}  (esperado: False)")

    # instruments_org deve ter RLS
    r = await conn.fetchrow("""
        SELECT rowsecurity FROM pg_tables
        WHERE tablename = 'instruments_org' AND schemaname = 'public'
    """)
    io_rls = r["rowsecurity"] if r else None
    print(f"instruments_org RLS:      {io_rls}  (esperado: True)")

    # nav_timeseries deve ser global (sem RLS)
    r = await conn.fetchrow("""
        SELECT rowsecurity FROM pg_tables
        WHERE tablename = 'nav_timeseries' AND schemaname = 'public'
    """)
    nt_rls = r["rowsecurity"] if r else None
    print(f"nav_timeseries RLS:       {nt_rls}  (esperado: False)")

    # instruments_universe nao deve ter organization_id
    cols = await conn.fetch("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'instruments_universe' AND table_schema = 'public'
        ORDER BY ordinal_position
    """)
    col_names = [r["column_name"] for r in cols]
    has_org_id = "organization_id" in col_names
    print(f"instruments_universe.organization_id: {has_org_id}  (esperado: False)")
    print(f"instruments_universe colunas: {col_names}")

    # nav_timeseries nao deve ter organization_id
    cols_nav = await conn.fetch("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'nav_timeseries' AND table_schema = 'public'
        ORDER BY ordinal_position
    """)
    nav_col_names = [r["column_name"] for r in cols_nav]
    has_nav_org = "organization_id" in nav_col_names
    print(f"nav_timeseries.organization_id: {has_nav_org}  (esperado: False)")
    print(f"nav_timeseries colunas: {nav_col_names}")

    go_53 = (
        iu_rls is False and
        io_rls is True and
        nt_rls is False and
        not has_org_id and
        not has_nav_org
    )
    print(f"GO #53: {go_53}")

    print()
    print("=== #54 — Alembic sync (migration 0070 pendente) ===")

    # Verificar migration head atual
    head = await conn.fetchrow("SELECT version_num FROM alembic_version")
    current = head["version_num"] if head else None
    print(f"Alembic current: {current}")

    # Verificar se tabelas criadas via Tiger CLI existem
    tables_check = await conn.fetch("""
        SELECT tablename FROM pg_tables
        WHERE tablename IN (
            'instruments_org',
            'sec_fund_prospectus_returns',
            'sec_fund_prospectus_stats'
        ) AND schemaname = 'public'
    """)
    existing = sorted([r["tablename"] for r in tables_check])
    print(f"Tabelas no DB: {existing}")
    print(f"Esperado: ['instruments_org', 'sec_fund_prospectus_returns', 'sec_fund_prospectus_stats']")

    # Verificar se series_id existe em sec_nport_holdings
    nport_cols = await conn.fetch("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'sec_nport_holdings' AND table_schema = 'public'
        AND column_name = 'series_id'
    """)
    has_series_id = len(nport_cols) > 0
    print(f"sec_nport_holdings.series_id existe: {has_series_id}")

    await conn.close()
    return current, existing, has_series_id

current, existing, has_series_id = asyncio.run(check_db())
```

---

## Etapa 2 — Criar migration 0070 (stub Alembic sync)

Se as tabelas existem no DB mas não no Alembic, criar migration stub:

```powershell
cd D:\Projetos\netz-analysis-engine\backend

# Verificar estado do Alembic
python -m alembic current
python -m alembic heads

# Se current != heads OU se tabelas novas nao estao no chain:
# Criar migration stub — tabelas ja existem, so registrar no chain
python -m alembic revision `
    --rev-id "0070_global_instruments_sync" `
    -m "sync_global_instruments_nport_prospectus"
```

O arquivo gerado em `app/core/db/migrations/versions/0070_global_instruments_sync.py`
deve ter `upgrade()` e `downgrade()` **vazios** — as tabelas ja existem:

```python
"""sync_global_instruments_nport_prospectus

Revision ID: 0070_global_instruments_sync
Revises: 0069_globalize_instruments_nav
Create Date: 2026-03-29

NOTE: Tables instruments_org, sec_fund_prospectus_returns,
sec_fund_prospectus_stats and column sec_nport_holdings.series_id
were created directly via Tiger CLI (Timescale Cloud console).
This migration is a stub to keep the Alembic chain consistent.
The actual CREATE TABLE / CREATE INDEX / ALTER TABLE were already
executed on Timescale Cloud.
"""
from alembic import op

revision = "0070_global_instruments_sync"
down_revision = "0069_globalize_instruments_nav"  # AJUSTAR para o head atual
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tables already exist — created directly on Timescale Cloud.
    pass


def downgrade() -> None:
    # No-op — tables remain.
    pass
```

```powershell
# Verificar que chain esta linear e sem conflitos
python -m alembic heads     # deve mostrar 1 head
python -m alembic current   # deve mostrar o head
python -m alembic history --verbose | head -20

# Aplicar (no-op para o DB, so registra no alembic_version)
python -m alembic upgrade head
python -m alembic current   # deve mostrar 0070_global_instruments_sync
```

Verificar resultado:

```python
import asyncio, asyncpg, os
from dotenv import load_dotenv; load_dotenv("D:/Projetos/netz-analysis-engine/backend/.env")
DB = os.environ["DIRECT_DATABASE_URL"].replace("postgresql+asyncpg://","postgresql://").replace("postgresql+psycopg://","postgresql://")

async def check():
    conn = await asyncpg.connect(DB)
    head = await conn.fetchrow("SELECT version_num FROM alembic_version")
    print(f"Alembic current: {head['version_num']}")
    go_54 = "0070" in head["version_num"]
    print(f"GO #54: {go_54}")
    await conn.close()

asyncio.run(check())
```

---

## Etapa 3 — make check (#55)

```powershell
cd D:\Projetos\netz-analysis-engine

# Rodar suite completa
make check 2>&1 | Tee-Object -FilePath "D:\Projetos\make_check_output.txt"

# Resumo rapido
Select-String -Path "D:\Projetos\make_check_output.txt" `
    -Pattern "passed|failed|error|FAILED" | Select-Object -Last 20
```

**Interpretar resultado:**

- `X passed, 0 failed` → GO #55
- `X passed, Y failed` → listar os failures e corrigir
- Failures esperados sem DB: `asyncpg.InvalidPasswordError` — aceitáveis
- Failures de `organization_id` em models/queries → regressão do refactor — CORRIGIR

Se houver failures de regressão, padrão de busca:

```powershell
# Encontrar queries que ainda usam organization_id em tabelas globais
Select-String -Path "D:\Projetos\make_check_output.txt" -Pattern "organization_id"

# Encontrar imports de Instrument com organization_id
Select-String -Recurse `
    -Path "D:\Projetos\netz-analysis-engine\backend" `
    -Pattern "Instrument.organization_id|nav_timeseries.*organization_id" `
    -Include "*.py" | Select-Object Filename, LineNumber, Line
```

Registrar resultado:

```python
# Depois de rodar make check, registrar manualmente:
go_55_passed = int(input("Quantos testes passaram? "))
go_55_failed = int(input("Quantos falharam (excluindo asyncpg sem DB)? "))
go_55 = go_55_failed == 0
print(f"GO #55: {go_55}  ({go_55_passed} passed, {go_55_failed} failed)")
```

---

## Resultado Final

```python
print("\n" + "="*55)
print("PROMPT G — P0 Estabilização Go/No-Go (#53-#55)")
print("="*55)

resultados = {
    "#53 Global instruments (RLS correto, org_id removido)": go_53,
    "#54 Migration 0070 Alembic sync":                        None,  # preencher apos etapa 2
    "#55 make check 0 failures":                              None,  # preencher apos etapa 3
}

for item, status in resultados.items():
    label = "✅ GO" if status is True else ("❌ FAIL" if status is False else "⏳ PENDENTE")
    print(f"  {item:<55} {label}")

print()
print("  ⚠️  Itens #54 e #55 requerem execução manual dos comandos acima.")
print("  ⚠️  NÃO fazer deploy Railway antes de todos GO.")
```

## Notas de diagnóstico

**Se `instruments_universe.organization_id` ainda existe:** a migration 0069 não
foi aplicada corretamente. Verificar `alembic history` e re-aplicar.

**Se `instruments_org` não existe:** a tabela foi criada via Tiger CLI mas pode
não existir no ambiente local. Criar via:
```sql
CREATE TABLE instruments_org (
    id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    organization_id  UUID NOT NULL,
    instrument_id    UUID NOT NULL REFERENCES instruments_universe(instrument_id) ON DELETE CASCADE,
    block_id         VARCHAR(80) REFERENCES allocation_blocks(block_id),
    approval_status  VARCHAR(20) NOT NULL DEFAULT 'pending',
    selected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, instrument_id)
);
ALTER TABLE instruments_org ENABLE ROW LEVEL SECURITY;
CREATE POLICY instruments_org_rls ON instruments_org
    USING (organization_id = (SELECT current_setting('app.current_org_id'))::uuid);
```

**Se make check tem failures de `lazy="raise"`:** algum relacionamento novo não
tem `selectinload()`. Localizar via `grep -r "MissingGreenlet\|lazy.*raise" tests/`.

**down_revision correto para 0070:** substituir pelo resultado de
`alembic heads` — pode ser `0069_globalize_instruments_nav` ou outro
dependendo de como o Opus nomeou as migrations do refactor.
