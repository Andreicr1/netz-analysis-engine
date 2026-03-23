-- IMF_Forecasts
-- Tabela: projeções WEO do FMI (GDP, inflação, fiscal, dívida)
-- Standalone — filtrar por country_code e indicator
-- Indicators: NGDP_RPCH (GDP), PCPIPCH (inflação),
--             GGXCNL_NGDP (fiscal), GGXWDG_NGDP (dívida)

SELECT
    country_code,
    indicator,
    year,
    value,
    edition,
    created_at
FROM public.imf_weo_forecasts
WHERE year >= EXTRACT(YEAR FROM CURRENT_DATE)::INT - 2
ORDER BY country_code, indicator, year
