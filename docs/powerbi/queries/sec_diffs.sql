-- SEC_Diffs
-- Tabela: variações quarter-over-quarter de holdings
-- Relaciona com: SEC_Managers via [cik]
--               SEC_Holdings via [holdings_key] (cik|cusip)
-- Filtro: últimos 8 trimestres

SELECT
    cik,
    cusip,
    issuer_name,
    quarter_from,
    quarter_to,
    shares_before,
    shares_after,
    shares_delta,
    value_before,
    value_after,
    action,          -- NEW_POSITION | INCREASED | DECREASED | EXITED | UNCHANGED
    weight_before,
    weight_after,
    -- Chave composta para relacionamento com SEC_Holdings
    cik || '|' || cusip AS holdings_key
FROM public.sec_13f_diffs
WHERE quarter_to >= (CURRENT_DATE - INTERVAL '2 years')
ORDER BY cik, quarter_to DESC, ABS(shares_delta) DESC NULLS LAST
