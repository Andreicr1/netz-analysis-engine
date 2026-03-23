-- Macro_Data
-- Tabela: séries macro do FRED (~45 séries)
-- Standalone — filtrar por series_id no Power BI
-- Filtro: últimos 5 anos

SELECT
    series_id,
    time,
    value,
    vintage_date
FROM public.macro_data
WHERE time >= (CURRENT_DATE - INTERVAL '5 years')
ORDER BY series_id, time DESC
