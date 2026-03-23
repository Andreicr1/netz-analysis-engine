-- ESMA_Tickers
-- Tabela: mapa ISIN → Yahoo Finance ticker (via OpenFIGI)
-- Relaciona com: ESMA_Funds via [isin]
--               ESMA_NAV via [isin]
-- Filtro: apenas tickers operáveis

SELECT
    isin,
    yahoo_ticker,
    exchange,
    resolved_via,
    is_tradeable,
    last_verified_at
FROM public.esma_isin_ticker_map
WHERE is_tradeable = TRUE
ORDER BY isin
