-- Benchmark_NAV
-- Tabela: séries de NAV de benchmarks (ETFs/índices)
-- Standalone — filtrar por ticker
-- Filtro: últimos 3 anos

SELECT
    ticker,
    time,
    close,
    volume,
    source
FROM public.benchmark_nav
WHERE time >= (CURRENT_DATE - INTERVAL '3 years')
ORDER BY ticker, time DESC
