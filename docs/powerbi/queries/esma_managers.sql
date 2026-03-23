-- ESMA_Managers
-- Tabela: gestoras europeias do registro ESMA
-- Relaciona com: ESMA_Funds via [esma_id]

SELECT
    esma_id,
    lei,
    company_name,
    country,
    authorization_status,
    fund_count,
    data_fetched_at
FROM public.esma_managers
WHERE company_name NOT LIKE 'Manager %'  -- exclui placeholders do seed anterior
ORDER BY fund_count DESC NULLS LAST
