-- Treasury_Data
-- Tabela: dados do Tesouro americano
-- Standalone — filtrar por series_name
-- Filtro: últimos 5 anos

SELECT
    series_name,
    time,
    value,
    unit,
    source
FROM public.treasury_data
WHERE time >= (CURRENT_DATE - INTERVAL '5 years')
ORDER BY series_name, time DESC
