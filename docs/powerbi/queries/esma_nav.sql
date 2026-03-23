-- ESMA_NAV
-- Tabela: histórico de NAV dos fundos UCITS com ticker
-- Relaciona com: ESMA_Tickers via [isin]
-- Filtro: últimos 3 anos

SELECT
    isin,
    yahoo_ticker,
    nav_date,
    nav_value,
    source
FROM public.esma_nav_history
WHERE nav_date >= (CURRENT_DATE - INTERVAL '3 years')
ORDER BY isin, nav_date DESC
