# Netz Analysis Engine — Power BI Data Model
# ============================================================
# Como usar:
# 1. Get Data → ODBC → DSN netz_engine → Advanced options
# 2. Cole o conteúdo de cada arquivo .sql no campo "SQL statement"
# 3. Dê o nome da tabela conforme indicado em cada arquivo
# 4. Após carregar, vá em Model View e configure os relacionamentos
# ============================================================

## Tabelas a importar

| Arquivo                   | Nome no Power BI   |
|---------------------------|--------------------|
| queries/sec_managers.sql  | SEC_Managers       |
| queries/sec_holdings.sql  | SEC_Holdings       |
| queries/sec_diffs.sql     | SEC_Diffs          |
| queries/esma_funds.sql    | ESMA_Funds         |
| queries/esma_managers.sql | ESMA_Managers      |
| queries/esma_tickers.sql  | ESMA_Tickers       |
| queries/esma_nav.sql      | ESMA_NAV           |
| queries/macro_data.sql    | Macro_Data         |
| queries/imf_forecasts.sql | IMF_Forecasts      |
| queries/bis_statistics.sql| BIS_Statistics     |
| queries/benchmark_nav.sql | Benchmark_NAV      |
| queries/treasury_data.sql | Treasury_Data      |

## Relacionamentos no Model View

### Bloco SEC (Managers → Holdings → Diffs)
- SEC_Managers[cik]          → SEC_Holdings[cik]       (1:N)
- SEC_Managers[cik]          → SEC_Diffs[cik]          (1:N)
- SEC_Holdings[holdings_key] → SEC_Diffs[holdings_key] (1:N, coluna calculada)

### Bloco ESMA (Managers → Funds → Tickers → NAV)
- ESMA_Managers[esma_id]     → ESMA_Funds[esma_manager_id] (1:N)
- ESMA_Funds[isin]           → ESMA_Tickers[isin]          (1:1)
- ESMA_Tickers[isin]         → ESMA_NAV[isin]              (1:N)

### Tabelas standalone (sem relacionamento direto)
- Macro_Data    — filtrar por series_id
- IMF_Forecasts — filtrar por country_code + indicator
- BIS_Statistics— filtrar por country_code + indicator
- Benchmark_NAV — filtrar por ticker
- Treasury_Data — filtrar por series_name
