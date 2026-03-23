-- ESMA_Funds
-- Tabela: fundos UCITS do registro ESMA
-- Relaciona com: ESMA_Managers via [esma_manager_id]
--               ESMA_Tickers via [isin]
-- Filtro: apenas fundos com ticker resolvido (operáveis)

SELECT
    f.isin,
    f.fund_name,
    f.esma_manager_id,
    f.domicile,
    f.fund_type,
    f.host_member_states,
    f.yahoo_ticker,
    f.ticker_resolved_at,
    f.data_fetched_at
FROM public.esma_funds f
INNER JOIN public.esma_isin_ticker_map t
    ON f.isin = t.isin
    AND t.is_tradeable = TRUE
ORDER BY f.fund_name
