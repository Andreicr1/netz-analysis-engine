-- BIS_Statistics
-- Tabela: estatísticas do BIS (44 países, trimestral)
-- Standalone — filtrar por country_code e indicator
-- Indicators: credit_to_gdp_gap, debt_service_ratio, property_prices

SELECT
    country_code,
    indicator,
    period,
    value,
    dataset
FROM public.bis_statistics
WHERE period >= (CURRENT_DATE - INTERVAL '10 years')
ORDER BY country_code, indicator, period DESC
