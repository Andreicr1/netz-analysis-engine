-- SEC_Holdings
-- Tabela: holdings trimestrais 13F por gestora
-- Relaciona com: SEC_Managers via [cik]
-- Filtro: últimos 8 trimestres para manter volume gerenciável

SELECT
    cik,
    report_date,
    filing_date,
    accession_number,
    cusip,
    issuer_name,
    asset_class,
    shares,
    market_value,
    discretion,
    -- Chave composta para relacionamento com SEC_Diffs
    cik || '|' || cusip AS holdings_key
FROM public.sec_13f_holdings
WHERE report_date >= (CURRENT_DATE - INTERVAL '2 years')
ORDER BY cik, report_date DESC, market_value DESC NULLS LAST
